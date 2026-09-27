"""Pruebas de lo que protege el portal: CORS, cookie de sesión y forma de la respuesta del panel.

Son los defectos que la revisión de la Fase 1 encontró y arregló, así que se quedan clavados aquí:
si alguien vuelve a abrirlos, esta suite lo dice.
"""

from __future__ import annotations

from tests.conftest import ADMIN, CLAVE_ADMIN, EMPRESA, ENTORNO_DE_PRUEBA, Portal, escribir_env

# ---------------------------------------------------------------- CORS

def test_cors_cerrado_por_defecto(portal: Portal) -> None:
    """El panel se sirve del mismo origen que la API: CORS no hace falta y abrirlo era el defecto.

    Antes `allow_origins=["*"]` con credenciales hacía que Starlette **reflejara** cualquier origen
    y devolviera `access-control-allow-credentials: true`.
    """
    r = portal.api.get("/api/salud", headers={"Origin": "https://sitio-malicioso.example"})
    assert r.status_code == 200
    cabeceras = {k.lower() for k in r.headers}
    assert "access-control-allow-origin" not in cabeceras
    assert "access-control-allow-credentials" not in cabeceras


def test_cors_solo_acepta_los_origenes_declarados(entorno) -> None:
    from app.config import origenes_cors

    escribir_env(entorno, **{**ENTORNO_DE_PRUEBA,
                             "CORS_ORIGENES": "https://panel.abga.example, https://otro.example"})
    assert origenes_cors() == ("https://panel.abga.example", "https://otro.example")


def test_cors_no_admite_comodin(entorno) -> None:
    """`*` con credenciales es exactamente lo que no se puede permitir: se ignora."""
    from app.config import origenes_cors

    escribir_env(entorno, **{**ENTORNO_DE_PRUEBA, "CORS_ORIGENES": "*"})
    assert origenes_cors() == ()
    escribir_env(entorno, **ENTORNO_DE_PRUEBA)
    assert origenes_cors() == ()


# ---------------------------------------------------------------- sesión

def test_la_cookie_de_sesion_no_la_puede_leer_el_navegador(portal: Portal) -> None:
    portal.entrar_como_cliente()
    cookie = portal.api.cookies.get("sesion")
    assert cookie, "el login tiene que dejar la cookie de sesión"
    # El navegador no puede leerla desde JavaScript y no viaja en peticiones de otros sitios.
    r = portal.api.post("/api/login", json={"email": ADMIN, "password": CLAVE_ADMIN,
                                           "cod_empresa": EMPRESA})
    cabecera = r.headers.get("set-cookie", "").lower()
    assert "httponly" in cabecera and "samesite=lax" in cabecera
    assert len(cabecera) < 1_024, "el token no puede llevar la lista de empresas dentro (daba 502)"


# ---------------------------------------------------------------- panel interno

def test_el_panel_de_usuarios_recibe_lo_que_pinta(portal: Portal) -> None:
    """El alta de usuarios devolvía `usuario`, pero el panel pinta `email`, `rol` y `password`.

    Resultado en pantalla: «Usuario undefined creado (undefined)». Se quedó ahí porque el endpoint
    estaba declarado **dos veces** y la versión que respondía no era la que el frontal esperaba.
    """
    portal.entrar_como_admin()
    r = portal.api.post("/api/interno/usuarios", json={"email": "nuevo@abga.example",
                                                       "nombre": "Persona Nueva",
                                                       "rol": "cliente", "empresas": [EMPRESA]})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["email"] == "nuevo@abga.example"
    assert cuerpo["rol"] == "cliente"
    assert cuerpo["password"], "sin contraseña, se genera y se enseña una sola vez"
    assert cuerpo["usuario"]["empresas"] == [EMPRESA]
    assert "no se vuelve a mostrar" in cuerpo["aviso"]


def test_no_hay_rutas_declaradas_dos_veces() -> None:
    """La ruta duplicada es lo que hizo posible el defecto anterior sin que nadie lo notara."""
    import collections

    from app.main import app

    cuenta: collections.Counter[tuple[str, str]] = collections.Counter()
    for ruta in app.routes:
        camino = getattr(ruta, "path", "")
        for metodo in getattr(ruta, "methods", ()) or ():
            if metodo not in {"HEAD", "OPTIONS"}:
                cuenta[(metodo, camino)] += 1
    repetidas = [clave for clave, n in cuenta.items() if n > 1]
    assert not repetidas, f"rutas declaradas más de una vez: {repetidas}"


def test_el_alta_de_un_usuario_que_ya_existe_no_lo_pisa(portal: Portal) -> None:
    """Editar un usuario conserva su contraseña: no se regenera por accidente."""
    from app import auth, db

    portal.entrar_como_admin()
    portal.api.post("/api/interno/usuarios", json={"email": "persona@abga.example",
                                                   "nombre": "Persona", "rol": "cliente",
                                                   "empresas": [EMPRESA]})
    hash_antes = db.hash_de("persona@abga.example")
    r = portal.api.post("/api/interno/usuarios", json={"email": "persona@abga.example",
                                                       "nombre": "Persona Renombrada",
                                                       "rol": "cliente"})
    assert r.status_code == 200
    assert r.json().get("password") in (None, ""), "sin contraseña nueva no se genera otra"
    assert db.hash_de("persona@abga.example") == hash_antes
    assert auth.verificar_password("lo-que-sea", hash_antes) is False
