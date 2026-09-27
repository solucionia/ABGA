"""Pruebas de la Fase 2: el estado que estaba en memoria del proceso pasa a la base de datos.

Lo que se defiende aquí:

* los intentos de acceso (PIN y contraseña) **cuentan de verdad**: sobreviven a un reinicio, no se
  multiplican por proceso y caducan con la ventana;
* los trabajos en segundo plano **dejan su estado en la base**, así que el progreso se ve desde
  cualquier proceso y no se pierde al reiniciar (y lo que quedó a medias se marca como interrumpido
  en vez de quedarse «en curso» para siempre).
"""

from __future__ import annotations

import time

import pytest

from app import bd, cache, db, trabajos
from app.aplicacion import sesion as casos
from tests.conftest import CLAVE_CLIENTE, CLIENTE, EMPRESA, Portal


def _insertar_intento_viejo(clave: str, segundos: int) -> None:
    """Mete un intento con fecha pasada para poder probar la ventana sin esperar 15 minutos."""
    from datetime import UTC, datetime, timedelta

    instante = (datetime.now(UTC) - timedelta(seconds=segundos)).isoformat(timespec="seconds")
    con = cache.conectar()
    con.execute("INSERT INTO intentos (clave, instante) VALUES (?, ?)", (clave, instante))
    con.commit()


# ---------------------------------------------------------------- intentos de acceso

def test_los_intentos_viven_en_la_base_y_no_en_el_proceso(portal: Portal) -> None:
    """Antes eran un diccionario: un reinicio los borraba y con dos procesos el límite valía doble."""
    db.registrar_intento("pin:6091")
    db.registrar_intento("pin:6091")

    # «Otro proceso»: conexión nueva y sin nada en memoria. El dato sigue ahí.
    bd.reiniciar()
    assert casos.intentos_recientes("pin:6091") == 2

    filas = cache.conectar().execute("SELECT COUNT(*) AS n FROM intentos").fetchone()
    assert filas["n"] == 2, "los intentos tienen que estar en la tabla, no sólo en memoria"


def test_los_intentos_caducan_con_la_ventana(portal: Portal) -> None:
    _insertar_intento_viejo("pin:6091", int(casos.VENTANA_INTENTOS) + 60)
    assert casos.intentos_recientes("pin:6091") == 0, "un intento de hace 16 minutos ya no cuenta"

    db.registrar_intento("pin:6091")
    assert casos.intentos_recientes("pin:6091") == 1


def test_el_login_tiene_limite_de_intentos(portal: Portal) -> None:
    """No había ninguno: se podía probar un diccionario entero contra una cuenta sin freno."""
    codigos = []
    for _ in range(casos.INTENTOS_LOGIN_MAX + 1):
        codigos.append(portal.entrar(CLIENTE, "clave-que-no-es").status_code)
    assert codigos[0] == 401
    assert codigos[-1] == 429, f"el intento {len(codigos)} tenía que cortarse por límite: {codigos}"

    r = portal.entrar(CLIENTE, "clave-que-no-es")
    assert r.json()["codigo"] == "limite_alcanzado"

    # Ni siquiera con la contraseña buena: el límite es del acceso, no de la contraseña.
    assert portal.entrar(CLIENTE, CLAVE_CLIENTE).status_code == 429


def test_un_acceso_correcto_limpia_los_intentos(portal: Portal) -> None:
    for _ in range(3):
        portal.entrar(CLIENTE, "clave-que-no-es")
    assert casos.intentos_recientes(f"login:{CLIENTE}") == 3

    assert portal.entrar_como_cliente().status_code == 200
    assert casos.intentos_recientes(f"login:{CLIENTE}") == 0


def test_el_limite_no_sirve_para_descubrir_correos(portal: Portal) -> None:
    """Un correo que no existe cuenta igual: la respuesta es la misma (401, luego 429)."""
    assert portal.entrar("no-existe@abga.example", "lo-que-sea").status_code == 401
    assert casos.intentos_recientes("login:no-existe@abga.example") == 1


def test_el_pin_de_la_empresa_tiene_su_propio_contador(portal: Portal) -> None:
    """El PIN y la contraseña no comparten contador: son ataques y defensas distintas."""
    db.registrar_intento("pin:6091")
    assert casos.intentos_recientes("pin:6091") == 1
    assert casos.intentos_recientes("login:cliente@mbdommo.com") == 0


# ---------------------------------------------------------------- trabajos en segundo plano

def _esperar(portal: Portal, tid: str, segundos: float = 10.0) -> dict:
    limite = time.time() + segundos
    while time.time() < limite:
        t = portal.api.get(f"/api/trabajos/{tid}").json()["trabajo"]
        if t["estado"] != "en_curso":
            return t
        time.sleep(0.05)
    raise AssertionError("el trabajo no terminó a tiempo")


def test_el_trabajo_deja_su_estado_en_la_base(portal: Portal) -> None:
    """El progreso se ve desde cualquier proceso, y se puede auditar qué pasó."""
    portal.entrar_como_cliente()
    r = portal.api.post("/api/refrescar", json={"cod_empresa": EMPRESA, "year": 2025})
    assert r.status_code == 200
    tid = r.json()["trabajo"]["id"]

    t = _esperar(portal, tid)
    assert t["estado"] == "hecho" and t["progreso"] == 1.0
    assert t["resultado"]["ejercicios"], "el trabajo guarda por dónde iba"

    fila = cache.conectar().execute("SELECT * FROM trabajos WHERE id=?", (tid,)).fetchone()
    assert fila is not None and fila["estado"] == "hecho"
    assert trabajos.obtener(tid) is not None
    assert any(x["id"] == tid for x in trabajos.listar(20))


def test_lo_que_quedo_a_medias_se_marca_como_interrumpido(portal: Portal) -> None:
    """Si el proceso muere a mitad, el trabajo no puede quedarse «en curso» para siempre."""
    portal.entrar_como_cliente()
    tid = portal.api.post("/api/refrescar", json={"cod_empresa": EMPRESA, "year": 2025}
                          ).json()["trabajo"]["id"]
    _esperar(portal, tid)

    con = cache.conectar()
    con.execute("UPDATE trabajos SET estado='en_curso', fin=NULL WHERE id=?", (tid,))
    con.commit()

    assert trabajos.marcar_interrumpidos() == 1
    t = portal.api.get(f"/api/trabajos/{tid}").json()["trabajo"]
    assert t["estado"] == "interrumpido" and "reinició" in t["mensaje"]


def test_no_se_lanzan_dos_cargas_del_mismo_ejercicio(portal: Portal) -> None:
    """La comprobación se hacía con un diccionario en memoria: con dos procesos, se duplicaba."""
    portal.entrar_como_cliente()
    trabajos.lanzar_carga(EMPRESA, 2025, forzar=True)
    primera = trabajos.trabajo_en_curso(EMPRESA, 2025)
    assert primera is not None

    segunda = trabajos.lanzar_carga(EMPRESA, 2025, forzar=True)
    assert segunda.id == primera.id, "no puede haber dos cargas del mismo ejercicio a la vez"

    # Una vez terminada, un ejercicio viejo ya no bloquea nada.
    cache.conectar().execute("UPDATE trabajos SET inicio=? WHERE id=?",
                             (time.time() - (trabajos.HORAS_VIGENCIA + 1) * 3600, primera.id))
    cache.conectar().commit()
    assert trabajos.trabajo_en_curso(EMPRESA, 2025) is None


def test_el_panel_interno_ve_los_trabajos(portal: Portal) -> None:
    portal.entrar_como_cliente()
    tid = portal.api.post("/api/refrescar", json={"cod_empresa": EMPRESA, "year": 2025}
                          ).json()["trabajo"]["id"]
    _esperar(portal, tid)
    portal.entrar_como_admin()
    resumen = portal.api.get("/api/interno/resumen").json()
    assert any(t["id"] == tid for t in resumen["trabajos"])


def test_un_trabajo_que_no_existe_da_404(portal: Portal) -> None:
    portal.entrar_como_cliente()
    r = portal.api.get("/api/trabajos/no-existe")
    assert r.status_code == 404 and r.json()["codigo"] == "no_encontrado"


def test_la_configuracion_de_salud_declara_el_proceso_unico(portal: Portal) -> None:
    """La restricción se dice donde la mira quien opera, no sólo en el documento."""
    r = portal.api.get("/api/salud")
    assert r.status_code == 200
    assert r.json()["proceso"]["workers"] == 1
    assert "hilos" in r.json()["proceso"]["nota"]


# ---------------------------------------------------------------- el arranque

def _cargar_arranque():
    """Carga `scripts/arranque.py` como módulo: es el punto de entrada del contenedor."""
    import importlib.util
    from pathlib import Path

    ruta = Path(__file__).resolve().parents[2] / "backend" / "scripts" / "arranque.py"
    especificacion = importlib.util.spec_from_file_location("arranque_de_prueba", ruta)
    assert especificacion and especificacion.loader
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


def test_el_arranque_se_niega_a_correr_con_varios_procesos(entorno, monkeypatch) -> None:
    """Es una decisión de arquitectura, así que se comprueba y no se supone.

    Con varios procesos, un trabajo lanzado en uno no lo ve el otro y el progreso que enseña el
    portal dependería de a qué proceso le tocara la petición. Antes de eso, se arranca con uno.
    """
    import os

    arranque = _cargar_arranque()

    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(SystemExit) as salida:
        arranque.comprobar_procesos()
    assert salida.value.code == 1

    monkeypatch.delenv("WEB_CONCURRENCY")
    arranque.comprobar_procesos()          # con uno, arranca sin quejarse
    assert os.environ.get("WEB_CONCURRENCY") is None


def test_el_arranque_exige_la_secret_key(entorno, monkeypatch) -> None:
    """Un despliegue sin `SECRET_KEY` no puede arrancar firmando sesiones con una clave conocida."""
    from app import config
    from tests.conftest import ENTORNO_DE_PRUEBA, escribir_env

    escribir_env(entorno, **{**ENTORNO_DE_PRUEBA, "SECRET_KEY": "corta"})
    config.cargar_config.cache_clear()
    with pytest.raises(RuntimeError) as error:
        config.cargar_config()
    assert "SECRET_KEY" in str(error.value)

    escribir_env(entorno, **ENTORNO_DE_PRUEBA)
    config.cargar_config.cache_clear()
    config.cargar_config()                 # con una clave larga, carga
