"""Endpoints de lectura: empresas del usuario, catálogo de módulos, ejercicios y diagnóstico."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ...aplicacion import catalogo, informes
from ..dependencias import empresa_permitida, usuario_actual
from ..esquemas import (
    RespuestaCache,
    RespuestaEjercicios,
    RespuestaEmpresas,
    RespuestaError,
    RespuestaModulos,
    RespuestaSalud,
    RespuestaValidacion,
)

router = APIRouter(prefix="/api", tags=["catálogo"])

ERRORES: dict[int | str, dict[str, Any]] = {
    400: {"model": RespuestaError}, 401: {"model": RespuestaError},
    403: {"model": RespuestaError}, 422: {"model": RespuestaValidacion},
}


@router.get("/empresas", response_model=RespuestaEmpresas, responses=ERRORES,
            summary="Empresas que puede ver el usuario")
def empresas(us: dict[str, Any] = Depends(usuario_actual)) -> RespuestaEmpresas:
    return RespuestaEmpresas(empresas=catalogo.empresas_visibles(us))


@router.get("/modulos", response_model=RespuestaModulos, responses=ERRORES,
            summary="Informes disponibles para ese usuario")
def modulos_disponibles(us: dict[str, Any] = Depends(usuario_actual)) -> RespuestaModulos:
    """Los informes de uso interno de ABGA no aparecen para un usuario de cliente."""
    return RespuestaModulos(**catalogo.modulos_visibles(us))


@router.get("/ejercicios", response_model=RespuestaEjercicios, responses=ERRORES,
            summary="Ejercicios de la empresa y cuáles están cargados")
def ejercicios(cod_empresa: str = Query(...), us: dict[str, Any] = Depends(usuario_actual)
               ) -> RespuestaEjercicios:
    cod = empresa_permitida(us, cod_empresa)
    return RespuestaEjercicios(**informes.ejercicios(cod))


@router.get("/cache", response_model=RespuestaCache, responses=ERRORES,
            summary="Qué ejercicios hay en caché")
def estado_cache(cod_empresa: str | None = Query(None),
                 us: dict[str, Any] = Depends(usuario_actual)) -> RespuestaCache:
    if cod_empresa is not None:
        cod_empresa = empresa_permitida(us, cod_empresa)
    return RespuestaCache(cache=catalogo.estado_cache(cod_empresa))


@router.get("/salud", response_model=RespuestaSalud, summary="Diagnóstico de la plataforma")
def salud() -> RespuestaSalud:
    """Sin sesión: sirve para saber si la plataforma está viva y con qué configuración."""
    return RespuestaSalud(**catalogo.salud())
