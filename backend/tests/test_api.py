"""Pruebas de la API: sesión real, permisos por empresa, contrato de informes y caché.

Todo con el ERP simulado y una base temporal, así que no tocan el ERP real ni los datos del
cliente: lo que se comprueba aquí es el comportamiento del portal (que es donde estaban los
defectos graves del sistema anterior: login decorativo y datos de otra empresa).
"""

from __future__ import annotations

import pytest

from tests.conftest import (
    CLAVE_CLIENTE,
    CLIENTE,
    EMPRESA,
    EMPRESA_AJENA,
    ENTORNO_DE_PRUEBA,
    Portal,
    escribir_env,
)

# ---------------------------------------------------------------- sesión

def test_sin_sesion_no_hay_datos(portal: Portal) -> None:
    """La fuga del modo demo: con la variable activa, cualquiera veía las 391 empresas."""
    for metodo, ruta in (("get", "/api/yo"), ("get", "/api/empresas"), ("get", "/api/modulos"),
                         ("get", f"/api/dashboard?cod_empresa={EMPRESA}&year=2025"),
                         ("get", f"/api/ejercicios?cod_empresa={EMPRESA}")):
        assert getattr(portal.api, metodo)(ruta).status_code == 401, ruta
    assert portal.api.post("/api/informe", json={"modulo": "pyg", "cod_empresa": EMPRESA,
                                                "year": 2025}).status_code == 401


def test_login_incorrecto_no_revela_nada(portal: Portal) -> None:
    r = portal.entrar(CLIENTE, "clave-que-no-es")
    assert r.status_code == 401
    assert "error" in r.json()


@pytest.mark.parametrize("cod,esperado", [
    ("", 400),            # falta el número de empresa
    ("9999", 404),        # esa empresa no está en la asesoría
    (EMPRESA_AJENA, 403),  # existe, pero este usuario no tiene acceso
])
def test_el_codigo_de_empresa_forma_parte_del_acceso(portal: Portal, cod: str,
                                                     esperado: int) -> None:
    assert portal.entrar(CLIENTE, CLAVE_CLIENTE, cod).status_code == esperado


def test_login_correcto_abre_la_empresa_pedida(portal: Portal) -> None:
    r = portal.entrar_como_cliente()
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["status"] == "ok"
    assert cuerpo["cod_empresa"] == EMPRESA and cuerpo["empresa"] == "MB Dommo, S.L."
    assert "sesion" in r.cookies or r.cookies.get("sesion")
    # el token no puede llevar la lista de empresas dentro: nginx devolvía 502 por cabecera grande
    assert len(r.headers.get("set-cookie", "")) < 1_024
    assert portal.api.get("/api/yo").status_code == 200


def test_logout_cierra_la_sesion(portal: Portal) -> None:
    portal.entrar_como_cliente()
    assert portal.api.post("/api/logout").status_code == 200
    assert portal.api.get("/api/yo").status_code == 401


# ---------------------------------------------------------------- permisos

def test_el_cliente_solo_ve_sus_empresas(portal: Portal) -> None:
    portal.entrar_como_cliente()
    empresas = portal.api.get("/api/empresas").json()["empresas"]
    assert [e["cod_empresa"] for e in empresas] == [EMPRESA]
    assert portal.api.get(f"/api/dashboard?cod_empresa={EMPRESA_AJENA}&year=2025").status_code == 403
    assert portal.informe("pyg", cod_empresa=EMPRESA_AJENA).status_code == 403


def test_los_informes_internos_no_salen_al_cliente(portal: Portal) -> None:
    portal.entrar_como_cliente()
    assert portal.informe("duplicados").status_code == 403
    nombres = [m["nombre"] for m in portal.api.get("/api/modulos").json()["modulos"]]
    assert "duplicados" not in nombres
    assert "pyg" in nombres


def test_el_usuario_interno_si_ve_los_informes_internos(portal: Portal) -> None:
    portal.entrar_como_admin()
    nombres = [m["nombre"] for m in portal.api.get("/api/modulos").json()["modulos"]]
    assert "duplicados" in nombres
    r = portal.informe("duplicados")
    assert r.status_code == 200 and r.json()["html"].lstrip().startswith("<div")


def test_el_panel_interno_es_solo_para_abga(portal: Portal) -> None:
    portal.entrar_como_cliente()
    assert portal.api.get("/api/interno/resumen").status_code == 403
    portal.entrar_como_admin()
    assert portal.api.get("/api/interno/resumen").status_code == 200


# ---------------------------------------------------------------- informes y caché

def test_el_informe_respeta_el_contrato(portal: Portal) -> None:
    portal.entrar_como_cliente()
    r = portal.informe("pyg")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["status"] == "ok"
    assert cuerpo["html"].lstrip().startswith("<div")
    assert cuerpo["data"], "los números del informe van en `data`, no dentro del HTML"
    assert cuerpo["meta"]["modulo"] == "pyg" and cuerpo["meta"]["year"] == 2025
    assert cuerpo["meta"]["empresa"] == "MB Dommo, S.L."


def test_la_segunda_consulta_no_vuelve_al_erp(portal: Portal) -> None:
    """La razón de ser de la caché: el ERP tarda ~200 s por ejercicio y limita el ritmo."""
    portal.entrar_como_cliente()
    assert portal.informe("pyg").status_code == 200
    peticiones_tras_la_primera = portal.erp.n_llamadas
    assert peticiones_tras_la_primera > 0

    segunda = portal.informe("pyg")
    assert segunda.status_code == 200
    assert portal.erp.n_llamadas == peticiones_tras_la_primera, \
        "la segunda consulta tiene que servirse de la caché"
    assert segunda.json()["meta"]["desde_cache"] is True


def test_la_cobertura_se_declara_en_el_meta(portal: Portal) -> None:
    """Nunca datos incompletos en silencio, que es lo que hacía el sistema anterior."""
    portal.entrar_como_cliente()
    ejercicios = portal.informe("pyg").json()["meta"]["ejercicios"]
    assert ejercicios
    for info in ejercicios.values():
        assert info["cobertura"], "cada ejercicio leído tiene que declarar su cobertura"
        assert info["n_asientos"] > 0


def test_el_dashboard_manda_datos_agregados(portal: Portal) -> None:
    portal.entrar_como_cliente()
    r = portal.api.get(f"/api/dashboard?cod_empresa={EMPRESA}&year=2025")
    assert r.status_code == 200
    cuerpo = r.json()["data"]
    assert "asientos" not in cuerpo, "los apuntes crudos no se mandan al navegador"
    assert len(r.content) < 200_000
    assert cuerpo["mensual"] and cuerpo["kpis"]


def test_error_del_erp_se_contesta_502(portal: Portal) -> None:
    """Un fallo del ERP no puede dejar al portal girando hasta el timeout (como en n8n)."""
    from app import apicon

    portal.entrar_como_cliente()
    portal.erp.fallos[(EMPRESA, 2025)] = apicon.ErrorErp("El ERP está limitando las peticiones (429).")
    r = portal.informe("pyg")
    assert r.status_code == 502
    assert "429" in r.json()["error"]


def test_refrescar_en_modo_solo_cache_avisa_en_vez_de_fallar(portal: Portal, entorno) -> None:
    from app import config

    escribir_env(entorno, **{**ENTORNO_DE_PRUEBA, "APICON_SOLO_CACHE": "1"})
    config.cargar_config.cache_clear()
    portal.entrar_como_cliente()
    r = portal.api.post("/api/refrescar", json={"cod_empresa": EMPRESA, "year": 2026})
    assert r.status_code == 409
    assert "SOLO_CACHE" in r.json()["error"]


def test_queda_registro_de_cada_ejecucion(portal: Portal) -> None:
    portal.entrar_como_cliente()
    portal.informe("pyg")
    portal.entrar_como_admin()
    resumen = portal.api.get("/api/interno/resumen").json()
    assert resumen["ejecuciones"], "cada informe deja traza (empresa, módulo, estado, segundos)"
    assert {"cod_empresa", "modulos", "estado", "segundos"} <= set(resumen["ejecuciones"][0])


# ---------------------------------------------------------------- alta de clientes

def test_el_alta_exige_pin_y_no_confirma_si_la_empresa_existe(portal: Portal) -> None:
    """El código de empresa son cuatro dígitos: por sí solo no puede ser credencial."""
    from app import auth, db

    db.fijar_pin(EMPRESA, auth.hash_password("4821"))
    alta = {"email": "nuevo@cliente.com", "nombre": "Nuevo Cliente",
            "password": "clave-larga-de-pruebas", "cod_empresa": EMPRESA}

    sin_pin = portal.api.post("/api/registro", json={**alta, "pin": ""})
    pin_malo = portal.api.post("/api/registro", json={**alta, "pin": "0000"})
    empresa_inexistente = portal.api.post("/api/registro", json={**alta, "cod_empresa": "7777", "pin": "0000"})
    assert sin_pin.status_code == pin_malo.status_code == empresa_inexistente.status_code == 403
    assert sin_pin.json()["error"] == empresa_inexistente.json()["error"], \
        "mismo mensaje: a un desconocido no se le confirma qué códigos existen"

    with_pin = portal.api.post("/api/registro", json={**alta, "pin": "4821"})
    assert with_pin.status_code == 200
    assert db.usuario("nuevo@cliente.com") is not None
    assert db.empresas_de("nuevo@cliente.com") == [EMPRESA]


def test_una_cuenta_existente_no_se_puede_reclamar(portal: Portal) -> None:
    from app import auth, db

    db.fijar_pin(EMPRESA, auth.hash_password("4821"))
    r = portal.api.post("/api/registro", json={"email": CLIENTE, "nombre": "Impostor",
                                              "password": "otra-clave-larga", "cod_empresa": EMPRESA,
                                              "pin": "4821"})
    assert r.status_code == 409


def test_el_pin_tiene_limite_de_intentos(portal: Portal) -> None:
    """Sin límite, los 10.000 PIN posibles se prueban en un rato."""
    from app import auth, db

    db.fijar_pin(EMPRESA, auth.hash_password("4821"))
    alta = {"email": "otro@cliente.com", "nombre": "Otro", "password": "clave-larga-de-pruebas",
            "cod_empresa": EMPRESA, "pin": "0000"}
    codigos = [portal.api.post("/api/registro", json=alta).status_code for _ in range(9)]
    assert codigos[0] == 403
    assert 429 in codigos, f"debería cortar por intentos: {codigos}"


# ---------------------------------------------------------------- diagnóstico

def test_salud_responde_sin_sesion(portal: Portal) -> None:
    r = portal.api.get("/api/salud")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["status"] == "ok" and cuerpo["version"]
    assert {m["nombre"] for m in cuerpo["modulos"]} >= {"pyg", "dashboard"}


@pytest.mark.parametrize("year_malo", ["dos-mil-veinticinco", "2025-2026", "", None, 1999])
def test_un_anio_invalido_se_rechaza_con_422(portal: Portal, year_malo) -> None:
    """Antes reventaba con 500 (`int("dos-mil")`). El formato lo valida el esquema, no el código."""
    portal.entrar_como_cliente()
    r = portal.api.post("/api/informe", json={"modulo": "pyg", "cod_empresa": EMPRESA,
                                             "year": year_malo})
    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["status"] == "error" and cuerpo["codigo"] == "entrada_invalida"
    assert cuerpo["detalle"], "el error tiene que decir qué campo está mal"


def test_un_campo_de_mas_se_rechaza(portal: Portal) -> None:
    """Un campo mal escrito (p. ej. `anio` por `year`) es un error, no un silencio."""
    portal.entrar_como_cliente()
    r = portal.api.post("/api/informe", json={"modulo": "pyg", "cod_empresa": EMPRESA,
                                             "year": 2025, "anio": 2025})
    assert r.status_code == 422
    assert any(d["campo"] == "anio" for d in r.json()["detalle"])


def test_todos_los_errores_hablan_el_mismo_idioma(portal: Portal) -> None:
    """Un solo formato de error: `{status, error, codigo}`.

    Antes convivían tres (el `{"status":"error"}`, el `detail` de FastAPI —que el portal no leía— y
    el de los informes), así que la mitad de los mensajes no llegaban a la pantalla.
    """
    portal.entrar_como_cliente()
    respuestas = [
        portal.api.get("/api/interno/resumen"),                                  # 403 (rol cliente)
        portal.api.get(f"/api/empresas/{EMPRESA_AJENA}"),                        # 404 de ruta
        portal.api.post("/api/informe", json={"modulo": "no-existe", "cod_empresa": EMPRESA,
                                              "year": 2025}),                    # 404 de módulo
        portal.api.post("/api/informe", json={"modulo": "pyg", "cod_empresa": "",
                                              "year": 2025}),                    # 400
        portal.api.post("/api/informe", json={"modulo": "pyg", "cod_empresa": EMPRESA_AJENA,
                                              "year": 2025}),                    # 403
        portal.api.get(f"/api/dashboard?cod_empresa={EMPRESA}&year=2025"),       # 200
    ]
    for r in respuestas[:-1]:
        cuerpo = r.json()
        assert r.status_code >= 400, r.url
        assert cuerpo.get("status") == "error" and cuerpo.get("error") and cuerpo.get("codigo"), \
            f"{r.url} no sigue el formato de error: {cuerpo}"
    assert respuestas[-1].json()["status"] == "ok"


def test_la_api_documenta_sus_esquemas() -> None:
    """El contrato tiene que estar publicado: es lo que hace utilizable `/docs`."""
    from app.api import esquemas
    from app.main import app

    documento = app.openapi()
    declarados = set(documento.get("components", {}).get("schemas", {}))
    # Se excluyen las bases (`BaseModel`, `_Peticion`): existen para heredar, no para publicarse.
    publicados = {m.__name__ for m in vars(esquemas).values()
                  if isinstance(m, type) and issubclass(m, esquemas.BaseModel)
                  and m.__name__ not in {"BaseModel"} and not m.__name__.startswith("_")}
    assert len(declarados) > 20, "cada petición y cada respuesta tiene que estar descrita"
    assert publicados <= declarados, f"sin publicar: {sorted(publicados - declarados)}"

    # Toda petición POST con cuerpo declara su esquema de entrada.
    for ruta, operaciones in documento["paths"].items():
        for operacion in operaciones.values():
            if operacion.get("requestBody"):
                contenido = list(operacion["requestBody"]["content"].values())[0]["schema"]
                assert "$ref" in contenido, f"{ruta} no declara el esquema de su petición"
