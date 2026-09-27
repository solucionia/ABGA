"""Endpoints de sesión: entrar, darse de alta, salir y saber quién soy.

El router no decide nada: valida el formato (Pydantic), llama al caso de uso y traduce.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response

from ...aplicacion import sesion as casos
from ...aplicacion import sesion as casos_sesion
from ..cookies import poner_cookie, quitar_cookie
from ..dependencias import usuario_actual
from ..esquemas import (
    PeticionLogin,
    PeticionRegistro,
    RespuestaError,
    RespuestaLogin,
    RespuestaOk,
    RespuestaValidacion,
    RespuestaYo,
)

router = APIRouter(prefix="/api", tags=["sesión"])

ERRORES: dict[int | str, dict[str, Any]] = {
    400: {"model": RespuestaError}, 401: {"model": RespuestaError},
    403: {"model": RespuestaError}, 404: {"model": RespuestaError},
    409: {"model": RespuestaError}, 422: {"model": RespuestaValidacion},
    429: {"model": RespuestaError},
}


@router.post("/login", response_model=RespuestaLogin, responses=ERRORES,
             summary="Acceso al portal")
def login(peticion: PeticionLogin, respuesta: Response) -> RespuestaLogin:
    """Entra con correo, contraseña **y el número de empresa**.

    El número de empresa forma parte del acceso, no es un filtro posterior: el cliente entra con su
    código y se abre directamente su panel. Se comprueba después de validar la contraseña, así que
    el código no sirve para averiguar qué empresas existen.
    """
    sesion = casos.entrar(peticion.email, peticion.password, peticion.cod_empresa)
    poner_cookie(respuesta, sesion.token)
    return RespuestaLogin(token=sesion.token, usuario=sesion.usuario,
                          cod_empresa=sesion.cod_empresa, empresa=sesion.empresa)


@router.post("/logout", response_model=RespuestaOk, summary="Cerrar la sesión")
def logout(respuesta: Response) -> RespuestaOk:
    quitar_cookie(respuesta)
    return RespuestaOk()


@router.post("/registro", response_model=RespuestaLogin, responses=ERRORES,
             summary="Alta del cliente con el PIN de la asesoría")
def registro(peticion: PeticionRegistro, respuesta: Response) -> RespuestaLogin:
    """Crea la cuenta del cliente y entra directo en su panel.

    El código de empresa son cuatro dígitos y son adivinables: por sí solo **no** vale como
    credencial, hace falta el PIN que entrega la asesoría (guardado hasheado, se enseña una vez).
    """
    sesion = casos.alta_cliente(peticion.email, peticion.nombre, peticion.password,
                                peticion.cod_empresa, peticion.pin)
    poner_cookie(respuesta, sesion.token)
    return RespuestaLogin(token=sesion.token, usuario=sesion.usuario,
                          cod_empresa=sesion.cod_empresa, empresa=sesion.empresa)


@router.get("/yo", response_model=RespuestaYo, responses=ERRORES, summary="Quién soy")
def yo(us: dict[str, Any] = Depends(usuario_actual)) -> RespuestaYo:
    return RespuestaYo(usuario=us, interno=casos_sesion.es_interno(us))
