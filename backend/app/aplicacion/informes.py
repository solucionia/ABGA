"""Casos de uso de los informes: generar, exportar, panel y relectura del ERP.

`app/servicio.py` ya era la capa de aplicación del cálculo (cargar años → calcular → maquetar →
registrar). Lo que estaba en el router era la **decisión sobre el resultado**: qué hacer cuando el
módulo no está, qué significa un error (¿es del ERP o del cálculo?) y cuándo no se puede tocar el
ERP. Eso es lo que vive aquí.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import apicon, cache, db, modulos, servicio, trabajos
from .. import exportar as exportador
from ..config import cargar_config
from ..errores import Conflicto, EntradaInvalida, ErrorDelErp, NoEncontrado, SinPermiso


@dataclass
class Exportacion:
    contenido: bytes
    fichero: str
    mime: str
    n_tablas: int


def _resultado(modulo: str, *, cod_empresa: str, year: int, params: dict[str, Any],
               email: str, origen: str, forzar: bool = False,
               con_html: bool = True) -> servicio.Resultado:
    """Ejecuta el informe y traduce el fallo: el ERP es un 502, el resto es un 400."""
    r = servicio.ejecutar(modulo, cod_empresa=cod_empresa, year=year, params=params,
                          email=email, origen=origen, forzar=forzar, con_html=con_html)
    if r.status != "ok":
        mensaje = r.error or f"No se pudo generar el informe {modulo}."
        if r.tipo == "erp":
            raise ErrorDelErp(mensaje)
        if r.tipo == "no_disponible":
            raise NoEncontrado(mensaje)
        raise EntradaInvalida(mensaje)
    return r


def modulo_pedido(nombre: str, *, es_interno: bool) -> modulos.Definicion:
    """Comprueba que el módulo existe y que quien lo pide puede verlo.

    404 si no existe o no está implementado; 403 si es de uso interno de ABGA y quien pregunta es un
    cliente (la conciliación sí se le enseña; los duplicados, no).
    """
    definicion = modulos.obtener(nombre)
    if not definicion.disponible:
        raise NoEncontrado(definicion.error or "Módulo desconocido.")
    if definicion.interno and not es_interno:
        raise SinPermiso("Informe de uso interno de ABGA.")
    return definicion


def ejecutar(nombre: str, *, cod_empresa: str, year: int, params: dict[str, Any] | None = None,
             email: str, origen: str = "portal", forzar: bool = False,
             es_interno: bool = False, con_html: bool = True) -> servicio.Resultado:
    modulo_pedido(nombre, es_interno=es_interno)
    return _resultado(nombre, cod_empresa=cod_empresa, year=year, params=params or {},
                      email=email, origen=origen, forzar=forzar, con_html=con_html)


def analisis(cod_empresa: str, year: int, *, familia: str | None = None, nivel: str | None = None,
             email: str, es_interno: bool = False) -> servicio.Resultado:
    """El semáforo de «Análisis y alertas» **sin el HTML**, para que el panel lo pinte.

    El informe (POST /api/informe) ya devolvía los números en `data`, pero con el HTML al lado, y
    una pantalla que quiere 33 fichas con su semáforo no necesita maquetar el informe entero. Aquí
    se devuelve sólo el dato, y se admite el recorte por familia y por nivel.

    Las familias y los niveles válidos los declara el propio módulo (`FAMILIAS`, `NIVELES`): si
    mañana se añade una familia, esta validación la admite sin tocar nada.
    """
    definicion = modulo_pedido("analisis", es_interno=es_interno)
    familias = {clave for clave, _ in getattr(definicion.modulo, "FAMILIAS", [])}
    niveles = set(getattr(definicion.modulo, "NIVELES", ()))
    if familia and familia not in familias:
        raise EntradaInvalida(
            f"Familia desconocida: {familia}. Válidas: {', '.join(sorted(familias))}.")
    if nivel and nivel not in niveles:
        raise EntradaInvalida(
            f"Nivel desconocido: {nivel}. Válidos: {', '.join(sorted(niveles))}.")
    params = {k: v for k, v in (("familia", familia), ("nivel", nivel)) if v}
    return _resultado("analisis", cod_empresa=cod_empresa, year=year, params=params, email=email,
                      origen="panel", con_html=False)


def exportar(nombre: str, *, cod_empresa: str, year: int, params: dict[str, Any] | None = None,
             email: str, es_interno: bool = False) -> Exportacion:
    """Descarga del informe para trabajarlo fuera del portal.

    Se exportan las tablas del propio informe, así que lo que se descarga el cliente es exactamente
    lo que está viendo. El PDF lo hace el navegador al imprimir: no se mete un motor de PDF en el
    servidor.
    """
    modulo_pedido(nombre, es_interno=es_interno)
    r = _resultado(nombre, cod_empresa=cod_empresa, year=year, params=params or {}, email=email,
                   origen="exportar")
    contenido, fichero, mime = exportador.a_excel(r.html, base=f"{nombre}_{cod_empresa}_{year}")
    return Exportacion(contenido=contenido, fichero=fichero, mime=mime,
                       n_tablas=int(exportador.resumen(r.html)["n_tablas"]))


def dashboard(cod_empresa: str, year: int, *, forzar: bool = False,
              es_interno: bool = False) -> dict[str, Any]:
    """KPIs y series del panel, agregados (los apuntes crudos no salen del servidor)."""
    modulo_pedido("dashboard", es_interno=es_interno)
    try:
        r = servicio.datos_dashboard(cod_empresa, year, forzar=forzar)
    except apicon.ErrorErp as e:
        raise ErrorDelErp(str(e)) from e
    if r.get("status") != "ok":
        raise EntradaInvalida(str(r.get("error") or "No se pudo cargar el panel."))
    r["avisos"] = (r.get("data") or {}).get("avisos") or []
    return r


def lanzar_refresco(cod_empresa: str, year: int, *, modulos_pedidos: list[str] | None = None,
                    forzar: bool = True, email: str) -> trabajos.Trabajo:
    """Relee el ejercicio del ERP en segundo plano, con progreso consultable."""
    if cargar_config().solo_cache:
        raise Conflicto(
            f"Este ejercicio ({cod_empresa}/{year}) no está cargado y la plataforma está en modo "
            f"solo-caché, así que no se le pide al ERP. Hay que quitar APICON_SOLO_CACHE.")
    return trabajos.lanzar_carga(cod_empresa, year, modulos_pedidos=modulos_pedidos,
                                 forzar=forzar, email=email)


def ejercicios(cod_empresa: str) -> dict[str, Any]:
    """Ejercicios de la empresa y cuáles tienen datos ya cargados.

    El portal lo usa para abrir por el último ejercicio **con datos** en vez del año en curso (que a
    mitad de año aparece vacío y llena la pantalla de avisos que no vienen a cuento).
    """
    cfg = cargar_config()
    en_cache = {int(c["ejercicio"]): c for c in cache.info_cache(cod_empresa)}
    lista = []
    for y in sorted(cfg.ejercicios_disponibles, reverse=True):
        c = en_cache.get(y)
        lista.append({
            "year": y,
            "en_cache": c is not None,
            "n_asientos": c["n_asientos"] if c else None,
            "cobertura": c["cobertura"] if c else None,
            "tiene_datos": (c["n_asientos"] > 0) if c else None,
            "actualizado": c["actualizado"] if c else None,
        })
    return {"empresa": db.nombre_empresa(cod_empresa), "cod_empresa": cod_empresa,
            "ejercicios": lista}
