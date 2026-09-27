"""Pruebas de arquitectura: las reglas de dependencia, comprobadas por la suite.

Un documento de arquitectura que nadie comprueba se queda viejo en dos semanas. Estas pruebas leen
los `import` de verdad (con `ast`, no con `grep` sobre el texto, para no confundirse con lo que
dicen los comentarios) y fallan si alguien rompe el reparto de capas.

Reparto que se defiende aquí:

    api/         →  aplicacion/  →  dominio (ledger, informes, modulos)
    infraestructura (apicon, bd, cache, db, auth, trabajos, config) la usan las otras dos

Es decir: la capa HTTP no consulta la base de datos y el dominio no sabe que existe ni FastAPI ni
el ERP. Quien escriba un informe nuevo no necesita saber nada de HTTP, y quien toque un endpoint no
puede saltarse los casos de uso sin que esto salte.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

# Infraestructura y orquestación: la capa HTTP no puede tocarlas directamente.
PROHIBIDO_EN_LA_API = {
    "app.db", "app.bd", "app.cache", "app.apicon", "app.auth", "app.trabajos", "app.servicio",
    "app.esquema", "db", "bd", "cache", "apicon", "auth", "trabajos", "servicio", "esquema",
}

# Lo que el dominio (contabilidad y maquetación) no puede importar nunca.
PROHIBIDO_EN_EL_DOMINIO = {
    "fastapi", "starlette", "httpx", "sqlite3", "psycopg", "app.db", "app.bd", "app.cache",
    "app.apicon", "app.trabajos",
}


def ficheros(patron: str) -> list[Path]:
    return sorted(APP.glob(patron))


def importados(ruta: Path) -> set[str]:
    """Módulos importados por ese fichero, en forma absoluta y en forma corta.

    Los importes relativos se resuelven contra el paquete del fichero (`from ... import db` en
    `app/api/rutas/` es `app.db`). Se devuelven las dos formas —`app.db` y `db`— porque las reglas
    de abajo se escriben de forma natural y así no hay que acordarse de cuál usa cada una.
    """
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    partes = list(ruta.relative_to(APP).parts[:-1])
    nombres: set[str] = set()

    def anotar(modulo: str) -> None:
        if not modulo:
            return
        nombres.add(modulo)
        nombres.add(modulo.split(".")[0])

    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                anotar(alias.name)
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level == 0:
                raiz = nodo.module or ""
            else:
                # `from . import x` (level 1) se queda en el paquete del fichero; cada nivel de más
                # sube un paquete. Todo cuelga de `app`, que es el paquete raíz.
                base = partes[: len(partes) - (nodo.level - 1)] if nodo.level > 1 else partes
                raiz = ".".join(["app", *base, *((nodo.module or "").split(".") if nodo.module else [])])
            anotar(raiz)
            for alias in nodo.names:            # `from X import y` → también X.y
                anotar(f"{raiz}.{alias.name}" if raiz else alias.name)
    return nombres


@pytest.mark.parametrize("ruta", ficheros("api/**/*.py"), ids=lambda p: p.name)
def test_la_capa_http_no_toca_la_infraestructura(ruta: Path) -> None:
    """Ningún endpoint (ni una dependencia) consulta la base de datos: se lo pide a la aplicación."""
    infractores = importados(ruta) & PROHIBIDO_EN_LA_API
    assert not infractores, (
        f"{ruta.relative_to(APP)} importa {sorted(infractores)}: los datos se piden a "
        f"app/aplicacion/ (casos de uso), no a la infraestructura"
    )


@pytest.mark.parametrize("ruta", [APP / "ledger.py", APP / "informes.py", *ficheros("modulos/*.py")],
                         ids=lambda p: p.name)
def test_el_dominio_no_depende_de_la_infraestructura(ruta: Path) -> None:
    """El cálculo de un informe no sabe nada de HTTP, del ERP ni de la base de datos."""
    infractores = importados(ruta) & PROHIBIDO_EN_EL_DOMINIO
    assert not infractores, (
        f"{ruta.relative_to(APP)} importa {sorted(infractores)}: el dominio recibe las líneas ya "
        f"cargadas y devuelve números"
    )


def test_el_errores_no_depende_del_transporte() -> None:
    """`app/errores.py` lo usa la capa de aplicación: no puede importar FastAPI."""
    assert not (importados(APP / "errores.py") & {"fastapi", "starlette"}), \
        "el vocabulario de errores es de la aplicación, no del transporte"


def test_la_capa_http_no_define_sus_propios_errores() -> None:
    """Las excepciones se declaran una vez (`app/errores.py`); la capa HTTP sólo las traduce.

    Ojo con la diferencia: `RespuestaError` (en `api/esquemas.py`) es el **modelo de respuesta** que
    documenta la forma del error, y eso sí le corresponde. Lo que no puede es inventarse excepciones.
    """
    bases_de_excepcion = {"Exception", "ErrorPlataforma", "ValueError", "RuntimeError"}
    for ruta in ficheros("api/**/*.py"):
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        propias = [
            nodo.name for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.ClassDef)
            and any((getattr(b, "id", None) or getattr(b, "attr", None)) in bases_de_excepcion
                    for b in nodo.bases)
        ]
        assert not propias, (
            f"{ruta.relative_to(APP)} declara excepciones propias ({propias}): van en app/errores.py, "
            f"que es lo que comparten la capa HTTP y la de aplicación"
        )


def test_la_aplicacion_no_depende_de_la_capa_http() -> None:
    """El caso de uso se tiene que poder ejecutar desde un cron o un test, sin HTTP de por medio.

    Ojo al comparar nombres: es `app.api` o `app.api.<algo>`, **no** `startswith("app.api")`, que
    también atraparía a `app.apicon` (el cliente del ERP), que la aplicación sí puede usar.
    """
    for ruta in ficheros("aplicacion/*.py"):
        infractores = {i for i in importados(ruta)
                       if i == "app.api" or i.startswith("app.api.")}
        assert not infractores, f"{ruta.relative_to(APP)} depende de la capa HTTP: {infractores}"


def test_la_composicion_es_fina() -> None:
    """`main.py` monta routers y manejadores; si crece, es que hay lógica en el sitio equivocado."""
    lineas = (APP / "main.py").read_text(encoding="utf-8").splitlines()
    assert len(lineas) < 120, (
        f"main.py tiene {len(lineas)} líneas: la lógica va en app/aplicacion/ y los endpoints en "
        f"app/api/rutas/"
    )
