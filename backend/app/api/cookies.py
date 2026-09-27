"""La cookie de sesión, en un solo sitio.

El token va en cookie `httpOnly` (el JavaScript del portal no lo lee) y también en el cuerpo, para
los clientes que prefieren cabecera `Authorization`. `samesite="lax"` es lo que impide que otro
sitio use la cookie del cliente para consultar su contabilidad.
"""

from __future__ import annotations

from fastapi import Response

from ..aplicacion.sesion import SEGUNDOS_DE_SESION

NOMBRE_COOKIE = "sesion"


def poner_cookie(respuesta: Response, token: str) -> None:
    respuesta.set_cookie(NOMBRE_COOKIE, token, httponly=True, samesite="lax",
                         max_age=SEGUNDOS_DE_SESION)


def quitar_cookie(respuesta: Response) -> None:
    respuesta.delete_cookie(NOMBRE_COOKIE)
