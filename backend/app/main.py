"""Composición de la aplicación: routers, manejadores de error y ficheros estáticos.

Aquí **no hay reglas de negocio ni consultas a la base de datos**. Si este fichero vuelve a crecer,
es que algo se ha ido a la capa equivocada. El reparto es:

    app/api/rutas/       endpoints: validar, autorizar y delegar
    app/aplicacion/      casos de uso (qué se comprueba, en qué orden y con qué consecuencia)
    app/servicio.py      orquestación del cálculo de un informe
    app/modulos/         el cálculo de cada informe (determinista, sin ERP ni SQL)
    app/{apicon,bd,cache,db,auth,trabajos}.py   infraestructura (ERP, persistencia, sesión, trabajos)

Arranque en desarrollo:
    cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import VERSION
from .api import manejadores
from .api.rutas import ROUTERS
from .config import RAIZ_PROYECTO, origenes_cors
from .errores import NoEncontrado

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("abga.api")

FRONTEND = RAIZ_PROYECTO / "frontend"

DESCRIPCION = (
    "Informes financieros y dashboards sobre el ERP apiCON de ABGA Consultores. "
    "Sustituye al portal estático y a los 7 workflows de n8n: aquí hay autenticación real, "
    "permisos por empresa, caché de los apuntes y cálculo determinista (sin IA en las cifras)."
)


def crear_app() -> FastAPI:
    app = FastAPI(title="ABGA · plataforma de informes", version=VERSION, description=DESCRIPCION)

    manejadores.registrar(app)
    for router in ROUTERS:
        app.include_router(router)

    @app.api_route("/api/{resto:path}", methods=["GET", "POST", "HEAD", "OPTIONS"],
                   include_in_schema=False)
    def _ruta_de_api_desconocida(resto: str) -> None:
        """Una ruta de API que no existe responde en el idioma de la API (JSON), no con el 404 del
        servidor de ficheros. Se registra **después** de los routers, así que nunca les quita una
        ruta buena, y antes de los estáticos, que si no se la tragarían."""
        raise NoEncontrado(f"La ruta /api/{resto} no existe en esta plataforma.")

    # CORS: cerrado por defecto, porque el panel se sirve desde el mismo origen que la API. Se abre
    # sólo si `CORS_ORIGENES` trae dominios concretos (nunca `*`, y menos con credenciales).
    origenes = origenes_cors()
    if origenes:
        app.add_middleware(CORSMiddleware, allow_origins=list(origenes), allow_credentials=True,
                           allow_methods=["GET", "POST", "OPTIONS"],
                           allow_headers=["authorization", "content-type"])
        log.info("CORS restringido a: %s", ", ".join(origenes))
    else:
        log.info("CORS cerrado (el panel se sirve desde el mismo origen que la API)")

    if FRONTEND.exists():
        # Al final: los endpoints de arriba tienen prioridad sobre los ficheros estáticos.
        app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
    return app


app = crear_app()
