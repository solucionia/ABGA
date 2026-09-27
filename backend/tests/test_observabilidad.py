"""Fase 4: identificador de petición, métricas de uso y avisos.

Lo que se comprueba aquí es lo que hace que la plataforma se pueda mirar: que cada petición se pueda
seguir por su identificador (en la respuesta, en el registro y en la fila de `ejecuciones`), que las
métricas salgan de datos reales y no de suposiciones, y que un informe incompleto o fallido **deje
aviso** en vez de quedarse en una tabla que nadie abre.

Nada de esto toca el ERP: el cliente se sustituye por el doble de `conftest` igual que en el resto de
la suite.
"""

from __future__ import annotations

import json
import logging

import pytest

from tests.conftest import EMPRESA

# ---------------------------------------------------------------- identificador de petición

def test_la_respuesta_devuelve_su_identificador(portal) -> None:
    """Se puede preguntar por una petición concreta: la cabecera trae de vuelta lo que se mandó."""
    r = portal.api.get("/api/yo", headers={"X-Request-ID": "prueba-123"})
    assert r.headers["X-Request-ID"] == "prueba-123"


def test_sin_cabecera_el_identificador_es_propio(portal) -> None:
    """Si el cliente no lo manda, se inventa uno (y no se repite entre peticiones)."""
    primero = portal.api.get("/api/yo").headers["X-Request-ID"]
    segundo = portal.api.get("/api/yo").headers["X-Request-ID"]
    assert primero and segundo and primero != segundo
    assert len(primero) == 12 and all(c in "0123456789abcdef" for c in primero)


def test_la_cabecera_traida_se_sanea(portal) -> None:
    """Lo que llega del cliente no puede romper una línea de registro: si trae basura, se ignora."""
    r = portal.api.get("/api/yo", headers={"X-Request-ID": "lo que sea\ncon salto"})
    assert r.headers["X-Request-ID"] != "lo que sea\ncon salto"
    assert "\n" not in r.headers["X-Request-ID"]


def test_el_identificador_aparece_en_las_lineas_de_registro() -> None:
    """La pieza que lo mete en cada línea, sin tocar las llamadas a `log.info(...)`."""
    from app.observabilidad import ID_PETICION, FiltroIdPeticion, FormatoJson

    testigo = ID_PETICION.set("abc123")
    try:
        registro = logging.LogRecord("abga.prueba", logging.INFO, __file__, 1,
                                     "algo pasó: %s", ("con dato",), None)
        assert FiltroIdPeticion().filter(registro) is True
        assert getattr(registro, "id_peticion", None) == "abc123"
        linea = json.loads(FormatoJson().format(registro))
    finally:
        ID_PETICION.reset(testigo)
    assert linea["id_peticion"] == "abc123"
    assert linea["mensaje"] == "algo pasó: con dato"
    assert linea["nivel"] == "INFO" and linea["registro"] == "abga.prueba"


def test_el_formato_de_texto_lleva_el_identificador() -> None:
    """En texto también: si no, con el registro de siempre no se sabría de qué petición es."""
    from app.observabilidad import FORMATO_TEXTO, ID_PETICION, FiltroIdPeticion

    testigo = ID_PETICION.set("abc123")
    try:
        registro = logging.LogRecord("abga.prueba", logging.WARNING, __file__, 1, "ojo", (), None)
        FiltroIdPeticion().filter(registro)
        linea = logging.Formatter(FORMATO_TEXTO).format(registro)
    finally:
        ID_PETICION.reset(testigo)
    assert "[abc123]" in linea and "ojo" in linea


def test_el_identificador_de_la_peticion_queda_en_la_ejecucion(portal) -> None:
    """La fila de `ejecuciones` y las líneas de registro de esa misma petición, atadas."""
    from app import db

    portal.entrar_como_admin()
    # Se pide el informe por HTTP con un identificador conocido, como haría el frontal.
    r = portal.api.post("/api/informe", json={"modulo": "pyg", "cod_empresa": EMPRESA, "year": 2025},
                        headers={"X-Request-ID": "prueba-ejecucion"})
    assert r.status_code == 200

    ultima = db.ejecuciones(limite=1)[0]
    assert ultima["modulos"] == "pyg"
    assert ultima["id_peticion"] == "prueba-ejecucion"
    assert r.headers["X-Request-ID"] == "prueba-ejecucion"
    assert ultima["cobertura"] == "completa"


# ---------------------------------------------------------------- métricas

def test_las_metricas_cuentan_lo_que_paso(portal) -> None:
    """Dos informes: uno bien y otro con el ERP caído. Las cuentas tienen que reflejarlo."""
    from app import apicon

    portal.entrar_como_admin()
    assert portal.informe("pyg").status_code == 200
    # El ejercicio 2024 no está en caché, así que esta vez sí se le pide al ERP… y falla.
    portal.erp.fallos[(EMPRESA, 2024)] = apicon.ErrorErp("el ERP no responde")
    assert portal.informe("pyg", year=2024).status_code == 502

    r = portal.api.get("/api/interno/metricas?dias=7")
    assert r.status_code == 200
    m = r.json()
    # El inicio de sesión también se registra (es uso de la plataforma): 3 filas, 1 de ellas el login.
    assert m["total"] == 3
    assert m["por_estado"] == {"ok": 2, "error_erp": 1}
    assert m["errores"] == 1
    assert m["informes_parciales"] == 0
    assert m["desde_cache"]["n"] == 0, "el primer informe de cada ejercicio lee del ERP, no de caché"
    pyg = [x for x in m["por_modulo"] if x["modulo"] == "pyg"][0]
    assert pyg["n"] == 2 and pyg["errores"] == 1 and pyg["en_cache"] == 0
    assert m["avisos_pendientes"] == 1
    assert m["por_empresa"][0]["cod_empresa"] == EMPRESA
    assert m["por_empresa"][0]["errores"] == 1


def test_las_metricas_no_se_enseñan_sin_sesion_interna(portal) -> None:
    """El uso de la plataforma es cosa de ABGA, no de un cliente."""
    assert portal.api.get("/api/interno/metricas").status_code == 401
    portal.entrar_como_cliente()
    assert portal.api.get("/api/interno/metricas").status_code == 403


def test_un_informe_de_cache_se_cuenta_como_de_cache(portal) -> None:
    """El segundo informe del mismo ejercicio sale de la caché, y las métricas lo dicen."""
    portal.entrar_como_admin()
    portal.informe("pyg")
    portal.informe("pyg")

    m = portal.api.get("/api/interno/metricas").json()
    pyg = [x for x in m["por_modulo"] if x["modulo"] == "pyg"][0]
    assert pyg["n"] == 2 and pyg["en_cache"] == 1
    assert m["desde_cache"] == {"n": 1, "porcentaje": round(100 / 3, 1)}


# ---------------------------------------------------------------- avisos

class ErpIncompleto:
    """Doble del ERP que devuelve el ejercicio a medias, como cuando se corta una descarga."""

    def __init__(self, base) -> None:
        self.base = base

    def apuntes(self, empresa: str, ejercicio: int, *, forzar: bool = False, ttl=None):
        from app import cache
        from tests.sintetico import anio

        asientos = anio(ejercicio)
        mitad = asientos[: max(1, len(asientos) // 2)]
        cache.guardar_apuntes(empresa, ejercicio, mitad, resultados_totales=len(asientos),
                              cobertura=f"parcial ({len(mitad)} de {len(asientos)} asientos)",
                              segundos=1.0)
        return {"empresa": empresa, "year": ejercicio, "asientos": mitad, "n_asientos": len(mitad),
                "n_lineas": sum(len(a.get("Detalles") or []) for a in mitad),
                "resultados_totales": len(asientos),
                "cobertura": f"parcial ({len(mitad)} de {len(asientos)} asientos)",
                "segundos": 1.0, "desde_cache": False, "actualizado": cache.ahora()}


def test_un_informe_incompleto_avisa_aunque_salga(portal, monkeypatch: pytest.MonkeyPatch) -> None:
    """El caso que motivó todo esto: el informe sale, pero con medio ejercicio leído."""
    from app import alertas, apicon

    monkeypatch.setattr(apicon, "_cliente", ErpIncompleto(portal.erp))
    portal.entrar_como_admin()
    r = portal.informe("pyg")
    assert r.status_code == 200, "el informe sale; el aviso es sobre su calidad, no sobre el fallo"

    pendientes = alertas.pendientes()
    assert len(pendientes) == 1
    aviso = pendientes[0]
    assert aviso["tipo"] == "cobertura_parcial"
    assert aviso["cod_empresa"] == EMPRESA and aviso["modulo"] == "pyg"
    assert "parcial" in aviso["detalle"]
    assert aviso["veces"] == 1 and aviso["atendido"] == 0

    # El diagnóstico público lo cuenta (para poder monitorizarlo) y no dice de quién es.
    salud = portal.api.get("/api/salud").json()
    assert salud["avisos"]["pendientes"] == 1

    # Y el panel interno lo enseña con detalle, sólo con sesión interna.
    listado = portal.api.get("/api/interno/avisos").json()["avisos"]
    assert [a["id"] for a in listado] == [aviso["id"]]
    assert portal.api.get("/api/interno/metricas").json()["informes_parciales"] == 1


def test_un_error_del_erp_deja_aviso(portal) -> None:
    """Si el ERP no responde, el aviso queda: si no, nadie se enteraría hasta que llamara el cliente."""
    from app import alertas, apicon

    portal.entrar_como_admin()
    portal.erp.fallos[(EMPRESA, 2025)] = apicon.ErrorErp("timeout del ERP")
    assert portal.informe("pyg").status_code == 502

    pendientes = alertas.pendientes()
    assert [a["tipo"] for a in pendientes] == ["error_erp"]
    assert "timeout" in pendientes[0]["detalle"]


def test_los_avisos_repetidos_se_agrupan(portal) -> None:
    """Si el ERP se cae una tarde, no puede dejar 200 avisos: uno con contador."""
    from app import alertas

    primero = alertas.avisar("error_calculo", cod_empresa=EMPRESA, ejercicio=2025, modulo="pyg",
                             detalle="ValueError: primera vez")
    segundo = alertas.avisar("error_calculo", cod_empresa=EMPRESA, ejercicio=2025, modulo="pyg",
                             detalle="ValueError: otra vez")
    otro = alertas.avisar("error_calculo", cod_empresa=EMPRESA, ejercicio=2025, modulo="tesoreria",
                          detalle="ValueError: otro módulo")

    pendientes = alertas.pendientes()
    assert len(pendientes) == 2, "el mismo fallo repetido es un aviso; otro módulo, otro aviso"
    assert primero == segundo and otro != primero
    repetido = [a for a in pendientes if a["id"] == primero][0]
    assert repetido["veces"] == 2
    assert "otra vez" in repetido["detalle"], "el detalle es el último, no el primero"


def test_un_tipo_de_aviso_desconocido_no_se_apunta(portal) -> None:
    """Mejor no apuntar nada que inventarse un tipo que luego nadie sabe interpretar."""
    from app import alertas

    assert alertas.avisar("lo_que_sea", cod_empresa=EMPRESA) is None
    assert alertas.pendientes() == []


def test_atender_un_aviso_lo_saca_de_la_lista(portal) -> None:
    """Atender es dejar constancia de quién lo miró, y sólo se puede hacer una vez."""
    from app import alertas

    portal.entrar_como_admin()
    identificador = alertas.avisar("error_erp", cod_empresa=EMPRESA, ejercicio=2025, modulo="pyg",
                                   detalle="el ERP no responde")
    assert portal.api.get("/api/interno/avisos").json()["avisos"]

    r = portal.api.post("/api/interno/avisos/atender", json={"id": identificador})
    assert r.status_code == 200 and r.json()["atendido_por"]
    assert portal.api.get("/api/interno/avisos").json()["avisos"] == []
    assert portal.api.get("/api/interno/avisos?incluir_atendidos=true").json()["avisos"]

    # Repetirlo no vuelve a tener efecto, y se dice: 404, no un ok falso.
    assert portal.api.post("/api/interno/avisos/atender", json={"id": identificador}).status_code == 404
    assert portal.api.post("/api/interno/avisos/atender", json={"id": 999999}).status_code == 404


def test_atender_un_aviso_pide_sesion_interna(portal) -> None:
    from app import alertas

    identificador = alertas.avisar("error_erp", cod_empresa=EMPRESA, detalle="x")
    assert portal.api.post("/api/interno/avisos/atender",
                           json={"id": identificador}).status_code == 401
    portal.entrar_como_cliente()
    assert portal.api.post("/api/interno/avisos/atender",
                           json={"id": identificador}).status_code == 403
    assert alertas.contar() == 1, "un cliente no puede cerrar los avisos de ABGA"


# ---------------------------------------------------------------- el esquema

def test_una_base_nueva_ya_trae_lo_de_observabilidad(entorno) -> None:
    """Las columnas y la tabla de avisos las pone la migración, no el código al conectar."""
    from app import bd

    con = bd.conectar()
    columnas = {f["name"] for f in con.execute("PRAGMA table_info(ejecuciones)").fetchall()}
    assert {"id_peticion", "cobertura"} <= columnas
    tablas = {f["name"] for f in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "avisos" in tablas
