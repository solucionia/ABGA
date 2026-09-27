"""Casos de uso de lectura del catálogo y del panel interno.

Todo lo que el router hacía consultando la base directamente: qué empresas ve un usuario, qué
módulos puede pedir, el resumen del panel de ABGA. Aquí, sin HTTP de por medio, se puede probar
llamándolo con un usuario cualquiera.
"""

from __future__ import annotations

from typing import Any

from .. import VERSION, auth, cache, db, modulos, trabajos
from ..config import cargar_config
from ..errores import NoEncontrado


def empresas_visibles(us: dict[str, Any]) -> list[dict[str, Any]]:
    """Las empresas del usuario (o todas, si es interno), con el aviso de cuáles tienen datos.

    `con_datos` evita que el portal vaya preguntando empresa por empresa cuál tiene datos cargados:
    con las 391 de la asesoría eran cientos de peticiones y el panel parecía que no cargaba nunca.
    """
    permitidas = {str(c) for c in us["empresas"]}
    lista = [e for e in db.listar_empresas() if e["cod_empresa"] in permitidas]
    if not lista and permitidas:  # empresas sin ficha creada todavía
        lista = [{"cod_empresa": c, "nombre": f"Empresa {c}", "ejercicio_inicio": None}
                 for c in sorted(permitidas)]
    con_datos = db.empresas_con_datos()
    for e in lista:
        e["con_datos"] = e["cod_empresa"] in con_datos
    return lista


def modulos_visibles(us: dict[str, Any]) -> dict[str, Any]:
    """Módulos que puede pedir ese usuario, con los menús y los ejercicios configurados."""
    interno = auth.es_interno(us)
    salida = []
    for d in modulos.listar_todos():
        if not d.disponible or (d.interno and not interno):
            continue
        salida.append({
            "nombre": d.nombre, "titulo": d.titulo, "interno": d.interno,
            "menu": d.menu, "ejercicios": d.desplazamientos, "parametros": d.parametros,
        })
    return {
        "modulos": salida,
        "menus": [{"clave": c, "titulo": t} for c, t in modulos.MENUS],
        "pendientes": [{"clave": c, "titulo": t, "menu": m} for c, t, m in modulos.PENDIENTES],
        "ejercicios": list(cargar_config().ejercicios_disponibles),
    }


def estado_cache(cod_empresa: str | None = None) -> list[dict[str, Any]]:
    return cache.info_cache(cod_empresa)


def buscar_empresas(texto: str = "", limite: int = 40) -> dict[str, Any]:
    """Buscador del panel interno: los 391 clientes no caben en un desplegable."""
    t = (texto or "").strip().lower()
    todas = db.listar_empresas()
    if t:
        todas = [e for e in todas
                 if t in str(e["cod_empresa"]).lower() or t in (e["nombre"] or "").lower()]
    return {"total": len(todas), "empresas": todas[:max(1, min(int(limite), 200))]}


def invalidar_cache(*, cod_empresa: str, year: int | None, actor: str) -> dict[str, Any]:
    borrados = cache.invalidar(cod_empresa, year)
    db.registrar_ejecucion(cod_empresa=cod_empresa, ejercicio=year, modulos="invalidar_cache",
                           origen="interno", email=actor, segundos=0.0, estado="ok",
                           desde_cache=False, detalle=f"{borrados} ejercicios borrados de la caché")
    return {"borrados": borrados, "cache": cache.info_cache(cod_empresa)}


def resumen_interno(*, cod_empresa: str | None = None) -> dict[str, Any]:
    """Lo que ve el equipo de ABGA: uso, estado de la caché, trabajo en curso y accesos."""
    return {
        "ejecuciones": db.ejecuciones(cod_empresa=cod_empresa, limite=60),
        "por_estado": db.resumen_ejecuciones(30),
        "cache": cache.info_cache(cod_empresa),
        "trabajos": trabajos.listar(10),
        "empresas": db.listar_empresas(),
        "usuarios": db.listar_usuarios(),
        "modulos": [{"nombre": d.nombre, "titulo": d.titulo, "interno": d.interno,
                     "disponible": d.disponible, "error": d.error} for d in modulos.listar_todos()],
    }


def trabajos_recientes(limite: int = 20) -> list[dict[str, Any]]:
    return trabajos.listar(limite)


def trabajo(tid: str) -> dict[str, Any]:
    """Estado de un trabajo en curso. 404 si no existe (o si el proceso se reinició)."""
    t = trabajos.obtener(tid)
    if not t:
        raise NoEncontrado("Trabajo no encontrado.")
    return t.como_json()


def salud() -> dict[str, Any]:
    """Diagnóstico público: versión, ERP configurado, caché y módulos disponibles."""
    cfg = cargar_config()
    return {
        "status": "ok",
        "version": VERSION,
        "erp": cfg.apicon_base,
        "cache": {"ficheros": str(cfg.cache_db.name), "ttl_apuntes": cfg.ttl_apuntes},
        "proceso": {"workers": 1,
                    "nota": "un solo proceso: los trabajos en segundo plano corren en hilos de este "
                            "proceso (su estado y los intentos de acceso, en la base de datos)"},
        "modulos": [{"nombre": d.nombre, "disponible": d.disponible, "error": d.error}
                    for d in modulos.listar_todos()],
        "ejercicios": list(cfg.ejercicios_disponibles),
    }
