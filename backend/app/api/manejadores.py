"""Traducción de errores a respuestas HTTP.

Los errores en sí están en `app/errores.py` (los comparte la capa de aplicación); aquí sólo se
instalan los manejadores.

Antes convivían tres convenciones a la vez:

* `{"status": "error", "error": …}` — la que el portal sabe leer;
* `HTTPException(detail=…)` — **que el portal no leía**: el mensaje se perdía y el usuario veía el
  texto genérico del frontal («respuesta no válida»);
* `Resultado.como_json()` para los informes.

Ahora todas salen con la misma forma. Y cualquier excepción no prevista se registra y se devuelve
como 500 con mensaje genérico: nunca se filtra un rastro de pila al navegador.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as ErrorHTTP

from ..errores import ErrorPlataforma, cuerpo

log = logging.getLogger("abga.errores")


def registrar(app: FastAPI) -> None:
    """Instala los manejadores. Se llama una vez, al montar la aplicación."""

    @app.exception_handler(ErrorPlataforma)
    def _error_plataforma(_: Request, exc: ErrorPlataforma) -> JSONResponse:
        if exc.estado >= 500:
            log.error("%s: %s", exc.codigo, exc.mensaje)
        return JSONResponse(cuerpo(exc.estado, exc.mensaje, exc.codigo, exc.detalle),
                            status_code=exc.estado)

    @app.exception_handler(ErrorHTTP)
    def _error_http(_: Request, exc: ErrorHTTP) -> JSONResponse:
        # Cubre los 404 de ruta y los que levanta FastAPI por su cuenta (p. ej. el 405).
        return JSONResponse(cuerpo(exc.status_code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    def _error_validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
        detalle = [{"campo": ".".join(str(p) for p in e.get("loc", ()) if p != "body"),
                    "mensaje": str(e.get("msg", ""))} for e in exc.errors()]
        return JSONResponse(
            cuerpo(422, "La petición no tiene el formato esperado.", "entrada_invalida", detalle),
            status_code=422,
        )

    @app.exception_handler(Exception)
    def _error_no_previsto(_: Request, exc: Exception) -> JSONResponse:
        log.exception("fallo no previsto: %s", exc)
        return JSONResponse(cuerpo(500, "Error interno de la plataforma. Queda registrado."),
                            status_code=500)
