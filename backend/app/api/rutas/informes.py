"""Endpoints de informes: panel, informe, exportación y relectura del ERP."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from ...aplicacion import catalogo
from ...aplicacion import informes as casos
from ...aplicacion import sesion as casos_sesion
from ..dependencias import empresa_permitida, usuario_actual
from ..esquemas import (
    PeticionInforme,
    PeticionRefrescar,
    RespuestaAnalisis,
    RespuestaDashboard,
    RespuestaError,
    RespuestaInforme,
    RespuestaTrabajo,
    RespuestaTrabajos,
    RespuestaValidacion,
)

router = APIRouter(prefix="/api", tags=["informes"])

ERRORES: dict[int | str, dict[str, Any]] = {
    400: {"model": RespuestaError}, 401: {"model": RespuestaError}, 403: {"model": RespuestaError},
    404: {"model": RespuestaError}, 409: {"model": RespuestaError},
    422: {"model": RespuestaValidacion}, 502: {"model": RespuestaError},
}


@router.get("/dashboard", response_model=RespuestaDashboard, responses=ERRORES,
            summary="KPIs y series del panel")
def dashboard(cod_empresa: str = Query(...), year: int = Query(..., ge=2000, le=2100),
              forzar: bool = Query(False), us: dict[str, Any] = Depends(usuario_actual)
              ) -> RespuestaDashboard:
    """Datos agregados para el panel: los apuntes crudos no salen del servidor."""
    cod = empresa_permitida(us, cod_empresa)
    r = casos.dashboard(cod, year, forzar=forzar, es_interno=casos_sesion.es_interno(us))
    return RespuestaDashboard(data=r["data"], meta=r["meta"], avisos=r.get("avisos") or [])


@router.get("/analisis", response_model=RespuestaAnalisis, responses=ERRORES,
            summary="Semáforo de análisis y alertas (JSON, sin el HTML del informe)")
def analisis(cod_empresa: str = Query(...), year: int = Query(..., ge=2000, le=2100),
             familia: str | None = Query(None, description="Recorta a una familia de análisis"),
             nivel: str | None = Query(None, description="Recorta a un nivel del semáforo"),
             solo_cache: bool = Query(False, description="No pedir nada al ERP: sólo la caché"),
             us: dict[str, Any] = Depends(usuario_actual)) -> RespuestaAnalisis:
    """El catálogo de comprobaciones con su semáforo, en JSON, para pintar una pantalla.

    `data.hallazgos` trae todas las comprobaciones y `data.seleccion` las que pasan el filtro: el
    resumen (`data.resumen`) cuenta siempre todas, para que el semáforo no se recorte con el filtro.

    Con `solo_cache=true` no se le pide nada al ERP: los ejercicios que no estén cargados salen en
    `meta.faltantes` y en los avisos. Es lo que hay que usar para consultar producción (o un año sin
    cargar) sin arriesgar una espera larga o un 429, y lo que usan la cartera y la previsualización.
    """
    cod = empresa_permitida(us, cod_empresa)
    r = casos.analisis(cod, year, familia=familia, nivel=nivel, email=us["email"],
                       es_interno=casos_sesion.es_interno(us), solo_cache=solo_cache)
    return RespuestaAnalisis(**{k: v for k, v in r.como_json().items()
                                if k in RespuestaAnalisis.model_fields})


@router.post("/informe", response_model=RespuestaInforme, responses=ERRORES,
             summary="Generar un informe")
def informe(peticion: PeticionInforme, us: dict[str, Any] = Depends(usuario_actual)
            ) -> RespuestaInforme:
    """Devuelve los números en `data`, el HTML en `html` y la traza de la lectura en `meta`.

    La cobertura del ejercicio va siempre declarada en `meta`: si el ERP no dejó leerlo entero, el
    informe lo dice en lugar de dar cifras incompletas en silencio.
    """
    cod = empresa_permitida(us, peticion.cod_empresa)
    r = casos.ejecutar(peticion.modulo, cod_empresa=cod, year=peticion.year,
                       params=peticion.parametros(), email=us["email"], origen="portal",
                       forzar=peticion.forzar, es_interno=casos_sesion.es_interno(us))
    return RespuestaInforme(**{k: v for k, v in r.como_json().items()
                               if k in RespuestaInforme.model_fields})


@router.post("/informe/exportar", responses={**ERRORES, 200: {"content": {
    "application/zip": {}, "text/csv": {}}, "description": "CSV (o ZIP con varias hojas)"}},
    summary="Descargar el informe para Excel/CSV", response_class=Response)
def exportar(peticion: PeticionInforme, us: dict[str, Any] = Depends(usuario_actual)) -> Response:
    """Exporta las tablas del propio informe: lo que se descarga es lo que se está viendo.

    El PDF lo hace el navegador al imprimir, para no meter un motor de PDF en el servidor.
    """
    cod = empresa_permitida(us, peticion.cod_empresa)
    e = casos.exportar(peticion.modulo, cod_empresa=cod, year=peticion.year,
                       params=peticion.parametros(), email=us["email"],
                       es_interno=casos_sesion.es_interno(us))
    return Response(content=e.contenido, media_type=e.mime,
                    headers={"Content-Disposition": f'attachment; filename="{e.fichero}"',
                             "X-Tablas": str(e.n_tablas)})


@router.post("/refrescar", response_model=RespuestaTrabajo, responses=ERRORES,
             summary="Releer el ejercicio del ERP en segundo plano")
def refrescar(peticion: PeticionRefrescar, us: dict[str, Any] = Depends(usuario_actual)
              ) -> RespuestaTrabajo:
    cod = empresa_permitida(us, peticion.cod_empresa)
    t = casos.lanzar_refresco(cod, peticion.year, modulos_pedidos=peticion.modulos,
                              forzar=peticion.forzar, email=us["email"])
    return RespuestaTrabajo(trabajo=t.como_json())


@router.get("/trabajos", response_model=RespuestaTrabajos, responses=ERRORES,
            summary="Trabajos de esta sesión")
def lista_trabajos(us: dict[str, Any] = Depends(usuario_actual)) -> RespuestaTrabajos:
    return RespuestaTrabajos(trabajos=catalogo.trabajos_recientes())


@router.get("/trabajos/{tid}", response_model=RespuestaTrabajo, responses=ERRORES,
            summary="Progreso de un trabajo")
def estado_trabajo(tid: str, us: dict[str, Any] = Depends(usuario_actual)) -> RespuestaTrabajo:
    return RespuestaTrabajo(trabajo=catalogo.trabajo(tid))
