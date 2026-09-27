"""Endpoints del panel interno de ABGA: uso, accesos, PIN y caché.

Todos exigen rol interno (`usuario_interno`). Aquí vivía el endpoint duplicado:
`POST /api/interno/usuarios` estaba declarado dos veces y la segunda versión —la que devolvía
`email` y `rol`, que es lo que el panel pinta— era **inalcanzable**. Ahora hay uno solo, con la
forma que el panel espera.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ...aplicacion import catalogo
from ...aplicacion import usuarios as casos
from ...errores import EntradaInvalida
from ..dependencias import usuario_interno
from ..esquemas import (
    PeticionCache,
    PeticionEliminarUsuario,
    PeticionEmpresa,
    PeticionEmpresasDeUsuario,
    PeticionPin,
    PeticionUsuario,
    RespuestaCacheBorrada,
    RespuestaEliminado,
    RespuestaEmpresaCreada,
    RespuestaEmpresasBuscadas,
    RespuestaError,
    RespuestaPin,
    RespuestaResumenInterno,
    RespuestaUsuario,
    RespuestaUsuarios,
    RespuestaValidacion,
)

router = APIRouter(prefix="/api/interno", tags=["interno ABGA"])

ERRORES: dict[int | str, dict[str, Any]] = {
    400: {"model": RespuestaError}, 401: {"model": RespuestaError}, 403: {"model": RespuestaError},
    404: {"model": RespuestaError}, 409: {"model": RespuestaError},
    422: {"model": RespuestaValidacion},
}


@router.get("/resumen", response_model=RespuestaResumenInterno, responses=ERRORES,
            summary="Panel de ABGA")
def resumen(cod_empresa: str | None = Query(None),
            us: dict[str, Any] = Depends(usuario_interno)) -> RespuestaResumenInterno:
    return RespuestaResumenInterno(**catalogo.resumen_interno(cod_empresa=cod_empresa))


@router.get("/empresas", response_model=RespuestaEmpresasBuscadas, responses=ERRORES,
            summary="Buscador de empresas")
def buscar_empresas(q: str = Query(""), limite: int = Query(40, ge=1, le=200),
                    us: dict[str, Any] = Depends(usuario_interno)) -> RespuestaEmpresasBuscadas:
    """391 clientes no caben en un desplegable: se busca por código o por nombre."""
    return RespuestaEmpresasBuscadas(**catalogo.buscar_empresas(q, limite))


@router.post("/empresas", response_model=RespuestaEmpresaCreada, responses=ERRORES,
             summary="Alta de una empresa")
def crear_empresa(peticion: PeticionEmpresa,
                  us: dict[str, Any] = Depends(usuario_interno)) -> RespuestaEmpresaCreada:
    empresa = casos.crear_empresa(cod_empresa=peticion.cod_empresa, nombre=peticion.nombre,
                                  ejercicio_inicio=peticion.ejercicio_inicio, notas=peticion.notas,
                                  actor=us["email"])
    return RespuestaEmpresaCreada(empresa=empresa)


@router.post("/pin", response_model=RespuestaPin, responses=ERRORES,
             summary="Generar el PIN de una empresa")
def generar_pin(peticion: PeticionPin,
                us: dict[str, Any] = Depends(usuario_interno)) -> RespuestaPin:
    """El PIN se enseña **una sola vez**: no se guarda en claro en ningún sitio."""
    return RespuestaPin(**casos.generar_pin(peticion.cod_empresa, us["email"]))


@router.get("/usuarios", response_model=RespuestaUsuarios, responses=ERRORES,
            summary="Usuarios y sus permisos")
def listar_usuarios(us: dict[str, Any] = Depends(usuario_interno)) -> RespuestaUsuarios:
    return RespuestaUsuarios(usuarios=casos.listar())


@router.post("/usuarios", response_model=RespuestaUsuario, responses=ERRORES,
             summary="Crear o editar un usuario")
def guardar_usuario(peticion: PeticionUsuario,
                    us: dict[str, Any] = Depends(usuario_interno)) -> RespuestaUsuario:
    """Sin contraseña, se genera y se devuelve una sola vez (no se vuelve a poder consultar)."""
    r = casos.guardar(email=peticion.email, nombre=peticion.nombre, rol=peticion.rol,
                      activo=peticion.activo, password=peticion.password,
                      empresas=peticion.empresas, actor=us["email"])
    return RespuestaUsuario(usuario=r.usuario, email=r.usuario.get("email", peticion.email),
                            rol=r.usuario.get("rol", peticion.rol),
                            password=r.password or None, aviso=r.aviso or None,
                            cambio=r.cambio or None)


@router.post("/usuarios/empresas", response_model=RespuestaUsuario, responses=ERRORES,
             summary="Asignar empresas a un usuario")
def asignar_empresas(peticion: PeticionEmpresasDeUsuario,
                     us: dict[str, Any] = Depends(usuario_interno)) -> RespuestaUsuario:
    """Deja al usuario exactamente con esas empresas (marcar y desmarcar)."""
    r = casos.asignar_empresas(email=peticion.email, empresas=peticion.empresas, actor=us["email"])
    return RespuestaUsuario(usuario=r.usuario, email=r.usuario.get("email", peticion.email),
                            rol=r.usuario.get("rol", "cliente"), cambio=r.cambio)


@router.post("/usuarios/eliminar", response_model=RespuestaEliminado, responses=ERRORES,
             summary="Eliminar un usuario")
def eliminar_usuario(peticion: PeticionEliminarUsuario,
                     us: dict[str, Any] = Depends(usuario_interno)) -> RespuestaEliminado:
    casos.eliminar(email=peticion.email, actor=us["email"])
    return RespuestaEliminado(eliminado=peticion.email.lower())


@router.post("/cache", response_model=RespuestaCacheBorrada, responses=ERRORES,
             summary="Borrar la caché de una empresa")
def borrar_cache(peticion: PeticionCache,
                 us: dict[str, Any] = Depends(usuario_interno)) -> RespuestaCacheBorrada:
    if not peticion.cod_empresa:
        raise EntradaInvalida("Falta el código de empresa.")
    return RespuestaCacheBorrada(**catalogo.invalidar_cache(cod_empresa=peticion.cod_empresa,
                                                            year=peticion.year, actor=us["email"]))
