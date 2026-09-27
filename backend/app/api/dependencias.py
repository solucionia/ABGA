"""Dependencias de la API: quién es el usuario y a qué empresa puede entrar.

Estaba dentro de `main.py`, mezclado con los endpoints. Aquí sólo se resuelve la petición HTTP
(cookie, cabecera, identificador) y se delega en los casos de uso: la capa HTTP no consulta la base
de datos.
"""

from __future__ import annotations

from typing import Any

from fastapi import Cookie, Depends, Request

from ..aplicacion import sesion as casos
from ..errores import EntradaInvalida, NoAutenticado, SinPermiso

COOKIE_SESION = "sesion"


def token_de(request: Request, sesion: str | None = Cookie(default=None)) -> str | None:
    """El token viene en la cabecera `Authorization: Bearer …` o en la cookie de sesión."""
    cabecera = request.headers.get("authorization") or ""
    if cabecera.lower().startswith("bearer "):
        return cabecera[7:].strip()
    return sesion


def usuario_actual(request: Request, sesion: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Usuario de la petición, o 401."""
    us = casos.usuario_de_token(token_de(request, sesion))
    if us:
        return us
    # Modo demostración (previsualizaciones): sin sesión se entra como el usuario de ejemplo.
    demo = casos.usuario_de_demostracion()
    if demo:
        return demo
    raise NoAutenticado("Sesión no válida o caducada.")


def usuario_interno(us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    """Sólo el equipo de ABGA: es lo que protege los informes y el panel internos."""
    if not casos.es_interno(us):
        raise SinPermiso("Esta sección es de uso interno de ABGA.")
    return us


def empresa_permitida(us: dict[str, Any], cod_empresa: Any) -> str:
    """Normaliza el código de empresa y comprueba el permiso.

    400 si falta, 403 si el usuario no tiene acceso a ella. Es una regla de negocio, así que vive
    aquí y no repetida en cada endpoint.
    """
    cod = str(cod_empresa or "").strip()
    if not cod:
        raise EntradaInvalida("Falta el código de empresa.")
    if not casos.tiene_acceso(us["email"], cod):
        raise SinPermiso(f"Tu usuario no tiene acceso a la empresa {cod}.")
    return cod
