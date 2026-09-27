"""Identificador de petición y formato de los registros.

Hasta ahora cada línea del registro decía **qué** había pasado pero no **de qué petición**: con dos
personas usando el portal a la vez, un error de cálculo y la fila de `ejecuciones` que lo registra no
se podían atar. Aquí se resuelve lo mínimo para eso:

* un identificador por petición —el que traiga el cliente en `X-Request-ID` o uno propio—, guardado
  en una variable de contexto para que lo vea cualquier capa sin pasarlo de mano en mano;
* una línea por petición con método, ruta, estado y milisegundos, y el mismo identificador en la
  cabecera de la respuesta (para poder pedirle a quien informa del fallo «¿qué id te salió?»);
* texto para leer a mano y `LOG_FORMATO=json` para que lo pueda consumir otro programa.

No hace falta inventar nada: el `codigo` de los errores ya era estable y la tabla `ejecuciones` ya
existía. Esto sólo los une.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import secrets
import sys
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger("abga.peticion")

CABECERA = "X-Request-ID"
ID_PETICION: contextvars.ContextVar[str] = contextvars.ContextVar("id_peticion", default="-")

# Rutas que se piden solas cada pocos segundos (monitorización): a nivel INFO llenarían el registro
# de ruido y taparían lo que importa.
RUIDO = ("/api/salud",)

FORMATO_TEXTO = "%(asctime)s %(levelname)s [%(id_peticion)s] %(name)s: %(message)s"


def id_actual() -> str:
    """El identificador de la petición en curso (`-` si no hay: scripts, trabajos de fondo)."""
    return ID_PETICION.get()


def _identificador(peticion: Request) -> str:
    """El que venga del cliente, saneado, o uno nuevo."""
    traido = (peticion.headers.get(CABECERA) or "").strip()
    # Se recorta y se acepta sólo lo que se puede imprimir sin romper una línea de registro.
    if traido and len(traido) <= 64 and all(c.isalnum() or c in "-_.:" for c in traido):
        return traido
    return secrets.token_hex(6)


class MiddlewarePeticion(BaseHTTPMiddleware):
    """Pone el identificador, mide la petición y lo devuelve en la respuesta."""

    # Los parámetros se llaman como en la clase base (`request`, `call_next`) y no traducidos: con
    # otro nombre, los comprobadores de tipos lo leen como una sobreescritura incompatible.
    async def dispatch(self, request: Request,
                       call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        identificador = _identificador(request)
        testigo = ID_PETICION.set(identificador)
        inicio = time.perf_counter()
        try:
            respuesta = await call_next(request)
        except Exception:
            # El manejador de errores ya deja constancia; aquí queda que la petición no terminó.
            log.exception("%s %s -> sin respuesta en %.0f ms",
                          request.method, request.url.path, (time.perf_counter() - inicio) * 1000)
            raise
        else:
            milisegundos = (time.perf_counter() - inicio) * 1000
            respuesta.headers[CABECERA] = identificador
            (log.debug if request.url.path in RUIDO else log.info)(
                "%s %s -> %s en %.0f ms", request.method, request.url.path,
                respuesta.status_code, milisegundos)
            return respuesta
        finally:
            ID_PETICION.reset(testigo)


class FiltroIdPeticion(logging.Filter):
    """Añade el identificador a **cada** registro, sin tocar las llamadas a `log.info(...)`."""

    # El parámetro se llama `record` y no `registro` porque es lo que espera la clase base: con otro
    # nombre, mypy lo marca como una sobreescritura incompatible.
    def filter(self, record: logging.LogRecord) -> bool:
        record.id_peticion = id_actual()
        return True


class FormatoJson(logging.Formatter):
    """Una línea JSON por registro, para que la lea un programa en vez de una persona."""

    def format(self, record: logging.LogRecord) -> str:
        datos = {
            "instante": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "nivel": record.levelname,
            "registro": record.name,
            "id_peticion": getattr(record, "id_peticion", "-"),
            "mensaje": record.getMessage(),
        }
        if record.exc_info:
            datos["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(datos, ensure_ascii=False)


class ManejadorSalida(logging.StreamHandler):
    """Escribe siempre en el `sys.stderr` de ese momento, no en el que había al construirlo.

    Un `StreamHandler` normal se queda con el flujo que existía al crearlo. Al ejecutar las pruebas,
    ese flujo lo cierra pytest al terminar y cualquier registro posterior (pgserver apagándose, por
    ejemplo) acaba en «I/O operation on closed file» en vez de escribirse. Resolviéndolo en cada
    emisión, el registro nunca se queda apuntando a un flujo muerto.
    """

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


def configurar_logs() -> str:
    """Deja el registro de la aplicación en un solo manejador y devuelve el formato usado.

    Se hace a mano en vez de con `logging.basicConfig()` porque hace falta el filtro del
    identificador en **todas** las líneas, y `basicConfig` no acepta filtros.
    """
    formato = (os.environ.get("LOG_FORMATO") or "texto").strip().lower()
    if formato not in {"texto", "json"}:
        formato = "texto"
    nivel = getattr(logging, (os.environ.get("LOG_NIVEL") or "INFO").strip().upper(), logging.INFO)

    raiz = logging.getLogger()
    for manejador in list(raiz.handlers):
        raiz.removeHandler(manejador)
    manejador = ManejadorSalida()
    manejador.addFilter(FiltroIdPeticion())
    manejador.setFormatter(FormatoJson() if formato == "json" else logging.Formatter(FORMATO_TEXTO))
    raiz.addHandler(manejador)
    raiz.setLevel(nivel)

    # uvicorn trae sus propios manejadores: se quitan para que **todo** salga por el mismo sitio y
    # con el identificador de la petición. Su registro de accesos se silencia porque el middleware ya
    # escribe una línea por petición, con el id y los milisegundos; dos líneas por petición no
    # ayudan a nadie.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    for nombre in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger_uvicorn = logging.getLogger(nombre)
        logger_uvicorn.handlers = []
        logger_uvicorn.propagate = True
    return formato
