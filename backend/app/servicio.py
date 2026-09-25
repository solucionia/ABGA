"""Orquestación: coger los ejercicios, calcular, maquetar y registrar la ejecución.

Este fichero es el sustituto del armazón que n8n repetía en los 7 workflows
(Webhook → Preparar Parámetros → Auth → GET Apuntes → Code → Agente → Respuesta).
Aquí no hay agente LLM en el camino de los números: los informes son deterministas y
salen en el tiempo que tarda el ERP, no en el que tarde un modelo.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from . import apicon, cache, db, informes, modulos
from .ledger import Linea, detectar_cierre, fmt, lineas_de_asientos
from .modulos import Definicion

log = logging.getLogger("abga.servicio")

MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                "septiembre", "octubre", "noviembre", "diciembre"]


@dataclass
class Resultado:
    status: str
    html: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    avisos: list[str] = field(default_factory=list)

    def como_json(self) -> dict[str, Any]:
        salida: dict[str, Any] = {"status": self.status, "meta": self.meta}
        if self.html:
            salida["html"] = self.html
        if self.data:
            salida["data"] = self.data
        if self.avisos:
            salida["avisos"] = self.avisos
        if self.error:
            salida["error"] = self.error
        return salida


def _contexto(definicion: Definicion, *, cod_empresa: str, year: int, params: dict[str, Any]) -> dict[str, Any]:
    hoy = time.localtime()
    combinados = dict(definicion.parametros)
    combinados.update({k: v for k, v in (params or {}).items() if v not in (None, "")})
    return {
        "empresa": db.nombre_empresa(cod_empresa),
        "cod_empresa": str(cod_empresa),
        "year": int(year),
        "year_anterior": int(year) - 1,
        "nombre_mes": MESES_LARGOS[hoy.tm_mon - 1],
        "trimestre": (hoy.tm_mon - 1) // 3 + 1,
        **combinados,
    }


def _aviso_cierre(datos: dict[str, Any], traza: dict[str, Any]) -> None:
    """Añade a los avisos del módulo que el ejercicio está cerrado y con qué resultado del libro.

    Un ejercicio cerrado tiene el asiento de regularización y el de cierre, que no son actividad:
    se apartan (ver `cargar_ejercicios`) y hay que avisarlo, porque si no el cliente ve un
    resultado distinto del de su contabilidad y no sabe por qué.
    """
    avisos = datos.setdefault("avisos", [])
    if traza.get("omitidos_por_alta"):
        años = ", ".join(str(y) for y in traza["omitidos_por_alta"])
        avisos.append(
            f"No se incluyen los ejercicios {años}: son anteriores al alta de la empresa en la "
            "asesoría, así que no hay datos que mostrar (no es un error del informe).")
    for y in traza.get("cerrados") or []:
        ej = traza["ejercicios"].get(y) or {}
        avisos.append(
            f"Ejercicio {y} cerrado: se han apartado {ej.get('lineas_cierre', 0)} líneas del asiento "
            f"de regularización y del de cierre, que no son actividad. Resultado según la "
            f"contabilidad (cuenta 129): {fmt(ej.get('resultado_libro', 0.0))}.")


def cargar_ejercicios(cod_empresa: str, years: list[int], *, forzar: bool = False,
                      ttl: int | None = None) -> tuple[dict[int, list[Linea]], dict[str, Any]]:
    """Trae los ejercicios pedidos (caché primero) y los convierte en líneas contables.

    Si el ejercicio está **cerrado**, se apartan el asiento de regularización y el de cierre
    (ver `ledger.detectar_cierre`): no son actividad y, si se suman, dejan los gastos e ingresos
    a cero y el panel de un ejercicio cerrado aparece vacío sin explicar por qué.
    """
    cli = apicon.cliente()
    por_anio: dict[int, list[Linea]] = {}
    traza: dict[str, Any] = {"ejercicios": {}, "desde_cache": True, "segundos_erp": 0.0,
                             "cerrados": [], "omitidos_por_alta": []}

    # No se piden ejercicios anteriores al alta de la empresa: no existen, el ERP los devuelve
    # vacíos y hacían fallar a los módulos largos (autodespro pide 5 años, proyecciones 4) en
    # empresas jóvenes como la 6221, dada de alta en 2024.
    alta = (db.empresa(cod_empresa) or {}).get("ejercicio_inicio")
    if alta:
        traza["omitidos_por_alta"] = sorted(y for y in years if y < int(alta))
        years = sorted(y for y in years if y >= int(alta))

    for y in years:
        info = cli.apuntes(cod_empresa, y, forzar=forzar, ttl=ttl)
        crudo = lineas_de_asientos(info["asientos"])
        cierre = detectar_cierre(crudo)
        por_anio[y] = cierre["lineas_operativas"] if cierre["cerrado"] else crudo
        if cierre["cerrado"]:
            traza["cerrados"].append(y)
        traza["ejercicios"][y] = {
            "n_asientos": info["n_asientos"], "n_lineas": info["n_lineas"],
            "desde_cache": bool(info.get("desde_cache")), "cobertura": info.get("cobertura"),
            "actualizado": info.get("actualizado"), "segundos": info.get("segundos"),
            "resultados_totales": info.get("resultados_totales"),
            "cerrado": cierre["cerrado"], "resultado_libro": cierre["resultado_libro"],
            "lineas_cierre": cierre["n_lineas_fuera"],
        }
        if not info.get("desde_cache"):
            traza["desde_cache"] = False
            traza["segundos_erp"] += float(info.get("segundos") or 0)
    return por_anio, traza


def ejecutar(nombre_modulo: str, *, cod_empresa: str, year: int, params: dict[str, Any] | None = None,
             email: str | None = None, origen: str = "portal", forzar: bool = False,
             con_html: bool = True) -> Resultado:
    """Calcula un módulo de principio a fin, con los errores controlados."""
    inicio = time.perf_counter()
    definicion = modulos.obtener(nombre_modulo)
    if not definicion.disponible:
        msg = definicion.error or f"El módulo {nombre_modulo} no está disponible."
        db.registrar_ejecucion(cod_empresa=cod_empresa, ejercicio=year, modulos=nombre_modulo,
                               origen=origen, email=email, segundos=time.perf_counter() - inicio,
                               estado="error", desde_cache=False, detalle=msg)
        return Resultado(status="error", error=msg, meta={"modulo": nombre_modulo})

    ctx = _contexto(definicion, cod_empresa=cod_empresa, year=year, params=params or {})
    try:
        por_anio, traza = cargar_ejercicios(cod_empresa, modulos.anios_necesarios(nombre_modulo, year),
                                            forzar=forzar)
        datos = definicion.calcular(por_anio, ctx)
        datos.setdefault("avisos", [])
        _aviso_cierre(datos, traza)
        html = definicion.informe_html(datos, ctx) if con_html else ""
        if con_html and not html.lstrip().startswith("<div"):
            raise ValueError("el módulo no devolvió HTML empezando por <div>")
        metricas = definicion.metricas_dashboard(datos)
    except apicon.ErrorErp as e:
        segundos = time.perf_counter() - inicio
        db.registrar_ejecucion(cod_empresa=cod_empresa, ejercicio=year, modulos=nombre_modulo,
                               origen=origen, email=email, segundos=segundos, estado="error_erp",
                               desde_cache=False, detalle=str(e))
        log.warning("error del ERP en %s/%s: %s", cod_empresa, nombre_modulo, e)
        return Resultado(status="error", error=str(e), meta={"modulo": nombre_modulo, "segundos": round(segundos, 2)})
    except Exception as e:  # cualquier fallo de cálculo se registra y se devuelve controlado
        segundos = time.perf_counter() - inicio
        log.exception("fallo calculando %s/%s", cod_empresa, nombre_modulo)
        db.registrar_ejecucion(cod_empresa=cod_empresa, ejercicio=year, modulos=nombre_modulo,
                               origen=origen, email=email, segundos=segundos, estado="error_calculo",
                               desde_cache=False, detalle=f"{type(e).__name__}: {e}")
        return Resultado(status="error", error=f"No se pudo generar el informe: {e}",
                         meta={"modulo": nombre_modulo, "segundos": round(segundos, 2)})

    segundos = time.perf_counter() - inicio
    db.registrar_ejecucion(
        cod_empresa=cod_empresa, ejercicio=year, modulos=nombre_modulo, origen=origen, email=email,
        segundos=segundos, estado="ok", desde_cache=bool(traza["desde_cache"]),
        detalle=f"cobertura={traza['ejercicios']}", importes=metricas,
    )
    return Resultado(
        status="ok", html=html, data=datos, avisos=datos.get("avisos") or [],
        meta={
            "modulo": nombre_modulo, "titulo": definicion.titulo, "interno": definicion.interno,
            "empresa": ctx["empresa"], "cod_empresa": ctx["cod_empresa"], "year": ctx["year"],
            "segundos": round(segundos, 2), "desde_cache": bool(traza["desde_cache"]),
            "segundos_erp": round(traza["segundos_erp"], 2), "ejercicios": traza["ejercicios"],
            "cerrados": traza.get("cerrados") or [],
            "generado": cache.ahora(),
        },
    )


def datos_dashboard(cod_empresa: str, year: int, *, forzar: bool = False) -> dict[str, Any]:
    """KPIs y series del panel, en JSON agregado (nada de mandar los apuntes al navegador)."""
    definicion = modulos.obtener("dashboard")
    if not definicion.disponible:
        return {"status": "error", "error": definicion.error}
    ctx = _contexto(definicion, cod_empresa=cod_empresa, year=year, params={})
    por_anio, traza = cargar_ejercicios(cod_empresa, modulos.anios_necesarios("dashboard", year),
                                        forzar=forzar)
    datos = definicion.calcular(por_anio, ctx)
    _aviso_cierre(datos, traza)
    return {"status": "ok", "data": datos, "meta": {
        "empresa": ctx["empresa"], "cod_empresa": ctx["cod_empresa"], "year": ctx["year"],
        "desde_cache": bool(traza["desde_cache"]), "ejercicios": traza["ejercicios"],
        "cerrados": traza.get("cerrados") or [],
        "generado": cache.ahora(),
    }}


def informe_a_html_suelto(nombre_modulo: str, *, cod_empresa: str, year: int,
                          params: dict[str, Any] | None = None, email: str | None = None,
                          origen: str = "programado") -> str:
    r = ejecutar(nombre_modulo, cod_empresa=cod_empresa, year=year, params=params,
                 email=email, origen=origen)
    if r.status != "ok":
        return informes.envoltura(titulo="No se pudo generar el informe",
                                  cuerpo=informes.aviso(r.error or "error desconocido", tipo="error"),
                                  empresa=db.nombre_empresa(cod_empresa), ejercicio=year)
    return r.html
