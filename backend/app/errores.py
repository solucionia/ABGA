"""Errores de la plataforma: un solo vocabulario para toda la aplicación.

Viven fuera de la capa HTTP a propósito: los usa la capa de aplicación (que no sabe nada de
FastAPI) y la capa HTTP sólo los traduce a respuestas. Si estuvieran en `app/api/`, la aplicación
dependería del transporte y tendríamos la inversión que la Fase 1 viene a corregir.

Cada error lleva su estado HTTP y un **código estable** que no cambia aunque cambie el mensaje: es
lo que se puede vigilar en los registros.
"""

from __future__ import annotations

from typing import Any

# Código estable por estado HTTP.
CODIGO_POR_ESTADO: dict[int, str] = {
    400: "entrada_invalida",
    401: "no_autenticado",
    403: "sin_permiso",
    404: "no_encontrado",
    405: "metodo_no_permitido",
    409: "conflicto",
    413: "demasiado_grande",
    422: "entrada_invalida",
    429: "limite_alcanzado",
    500: "error_interno",
    502: "erp",
    503: "no_disponible",
}


class ErrorPlataforma(Exception):
    """Error de la aplicación con su estado HTTP y su código de negocio."""

    estado: int = 500
    codigo: str = "error_interno"

    def __init__(self, mensaje: str, *, detalle: list[dict[str, str]] | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle or []


class EntradaInvalida(ErrorPlataforma):
    estado, codigo = 400, "entrada_invalida"


class NoAutenticado(ErrorPlataforma):
    estado, codigo = 401, "no_autenticado"


class SinPermiso(ErrorPlataforma):
    estado, codigo = 403, "sin_permiso"


class NoEncontrado(ErrorPlataforma):
    estado, codigo = 404, "no_encontrado"


class Conflicto(ErrorPlataforma):
    estado, codigo = 409, "conflicto"


class LimiteAlcanzado(ErrorPlataforma):
    estado, codigo = 429, "limite_alcanzado"


class ErrorDelErp(ErrorPlataforma):
    """El ERP no responde, limita las peticiones o rechaza las credenciales: no es culpa del cliente."""

    estado, codigo = 502, "erp"


def cuerpo(estado: int, mensaje: str, codigo: str | None = None,
           detalle: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """El cuerpo único de error. El portal lee `error`; `codigo` es para quien depura."""
    salida: dict[str, Any] = {
        "status": "error",
        "error": mensaje,
        "codigo": codigo or CODIGO_POR_ESTADO.get(estado, "error"),
    }
    if detalle:
        salida["detalle"] = detalle
    return salida
