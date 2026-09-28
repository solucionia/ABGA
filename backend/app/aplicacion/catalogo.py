"""Casos de uso de lectura del catálogo y del panel interno.

Todo lo que el router hacía consultando la base directamente: qué empresas ve un usuario, qué
módulos puede pedir, el resumen del panel de ABGA. Aquí, sin HTTP de por medio, se puede probar
llamándolo con un usuario cualquiera.
"""

from __future__ import annotations

import time
from typing import Any

from .. import VERSION, alertas, auth, bd, cache, db, modulos, servicio, trabajos
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
    """Módulos que puede pedir ese usuario, con los menús y los ejercicios configurados.

    `ocultos` es la lista de los que **no** puede ver. No es redundante: a un cliente
    `/api/modulos` no le enseña los internos, así que sin este complemento el frontal no sabe qué
    pantallas tienen que dejar de aparecer en su menú — y le salía «Duplicados», que ABGA no
    quiere que el cliente vea nunca.
    """
    interno = auth.es_interno(us)
    salida = []
    ocultos = []
    for d in modulos.listar_todos():
        if d.interno and not interno:
            ocultos.append(d.nombre)
            continue
        if not d.disponible:
            continue
        salida.append({
            "nombre": d.nombre, "titulo": d.titulo, "interno": d.interno,
            "menu": d.menu, "ejercicios": d.desplazamientos, "parametros": d.parametros,
        })
    return {
        "modulos": salida,
        "ocultos": ocultos,
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


def diagnostico_cache(cfg: Any) -> dict[str, Any]:
    """En qué motor está la caché (y dónde, si es un fichero).

    El motor se deduce de `DATABASE_URL`, que es lo mismo que decide dónde se escribe. Antes esto
    publicaba el nombre del fichero de desarrollo siempre: en producción, con la caché en el
    PostgreSQL de Coolify, decía «abga.sqlite3» y en un incidente eso sólo confunde.
    """
    en_postgres = bd.es_postgres()
    return {
        "motor": "postgresql" if en_postgres else "sqlite",
        "ubicacion": ("el PostgreSQL de la plataforma" if en_postgres
                      else str(cfg.cache_db.name)),
        "ttl_apuntes": cfg.ttl_apuntes,
    }


def salud() -> dict[str, Any]:
    """Diagnóstico público: versión, ERP configurado, caché y módulos disponibles.

    Incluye **cuántos avisos hay sin atender**, que es el dato que hace que una monitorización sirva
    de algo: si eso sube, hay informes saliendo incompletos o fallando. El número es inocuo (no dice
    de qué empresa ni de qué módulo): el detalle se ve en el panel interno, con sesión.
    """
    cfg = cargar_config()
    return {
        "status": "ok",
        "version": VERSION,
        "erp": cfg.apicon_base,
        "cache": diagnostico_cache(cfg),
        "proceso": {"workers": 1,
                    "nota": "un solo proceso: los trabajos en segundo plano corren en hilos de este "
                            "proceso (su estado y los intentos de acceso, en la base de datos)"},
        "modulos": [{"nombre": d.nombre, "disponible": d.disponible, "error": d.error}
                    for d in modulos.listar_todos()],
        "ejercicios": list(cfg.ejercicios_disponibles),
        "avisos": {"pendientes": alertas.contar()},
    }


def metricas(*, dias: int = 7) -> dict[str, Any]:
    """Uso y salud de la plataforma, para el panel interno.

    Se calcula **desde `ejecuciones`**, que ya se escribía: lo nuevo es mirarlo de frente (cuántos
    informes salieron, cuántos de caché, qué módulo falla, qué empresa) en vez de tener que leer la
    tabla a mano.
    """
    datos = db.metricas_ejecuciones(dias)
    datos["avisos_pendientes"] = alertas.contar()
    datos["avisos"] = alertas.pendientes(limite=20)
    return datos


def avisos(*, incluir_atendidos: bool = False, limite: int = 200) -> list[dict[str, Any]]:
    return alertas.historico(limite=limite) if incluir_atendidos else alertas.pendientes(limite=limite)


def atender_aviso(identificador: int, actor: str) -> dict[str, Any]:
    """Marca un aviso como atendido. Si ya lo estaba (o no existe), se dice, no se finge."""
    if not alertas.atender(identificador, actor):
        raise NoEncontrado("El aviso no existe o ya estaba atendido.")
    return {"id": int(identificador), "atendido_por": actor}


def cartera(*, year: int, limite: int = 30, desde: int = 0) -> dict[str, Any]:
    """El semáforo de análisis de **todos** los clientes, ordenado por gravedad.

    Es la vista que faltaba para trabajar de asesoría y no de despacho: en vez de abrir cliente por
    cliente a ver cómo va, una lista con quién tiene rojos y por cuánto.

    Dos decisiones que hacen que esto se pueda usar con 391 clientes:

    * **No se le pide nada al ERP.** Sólo se miran los ejercicios que ya están en la caché
      (`servicio.ejecutar_solo_cache`). Con el ERP en medio serían horas y un 429 garantizado. Los
      clientes cuyo ejercicio no está cargado se cuentan en `sin_el_ejercicio`, no se inventan.
    * **Se hace por tandas.** `limite`/`desde` recorren la lista de clientes en el orden en que
      vienen, así que la respuesta dice cuántos quedan pendientes y el panel puede seguir pidiendo.
    """
    inicio = time.perf_counter()
    year = int(year)
    fichas = {str(e["cod_empresa"]) for e in db.listar_empresas()}
    en_cache = {str(c["empresa"]) for c in cache.info_cache()}
    candidatas = sorted({str(c["empresa"]) for c in cache.info_cache()
                         if int(c["ejercicio"]) == year})
    desde = max(0, int(desde))
    tanda = candidatas[desde:desde + max(1, int(limite))]

    filas: list[dict[str, Any]] = []
    fallos: list[dict[str, Any]] = []
    for cod in tanda:
        r = servicio.ejecutar_solo_cache("analisis", cod_empresa=cod, year=year, origen="cartera")
        if r.status != "ok":
            fallos.append({"cod_empresa": cod, "empresa": db.nombre_empresa(cod),
                           "error": r.error or "no se pudo calcular"})
            continue
        datos = r.data or {}
        res = datos.get("resumen") or {}
        filas.append({
            "cod_empresa": cod, "empresa": db.nombre_empresa(cod),
            "nivel_global": res.get("nivel_global", ""),
            "n_rojo": res.get("n_rojo", 0), "n_naranja": res.get("n_naranja", 0),
            "n_verde": res.get("n_verde", 0), "n_no_evaluable": res.get("n_no_evaluable", 0),
            "n_total": res.get("n_total", 0),
            "importe_riesgo": res.get("importe_riesgo", 0.0),
            "rojos": [str(h.get("titulo")) for h in datos.get("hallazgos") or []
                      if h.get("nivel") == "alerta"][:8],
        })
    filas.sort(key=lambda f: (0 if f["n_rojo"] else (1 if f["n_naranja"] else 2),
                              -float(f["importe_riesgo"] or 0.0), f["cod_empresa"]))

    return {
        "year": year,
        "filas": filas,
        "fallos": fallos,
        "totales": {
            "candidatas": len(candidatas), "analizadas": len(filas), "pendientes":
                max(0, len(candidatas) - (desde + len(tanda))),
            "en_rojo": sum(1 for f in filas if f["n_rojo"]),
            "en_naranja": sum(1 for f in filas if not f["n_rojo"] and f["n_naranja"]),
            "importe_riesgo": round(sum(float(f["importe_riesgo"] or 0.0) for f in filas), 2),
            "sin_el_ejercicio": len(en_cache - set(candidatas)),
            "sin_datos": len(fichas - en_cache),
        },
        "desde": desde, "limite": max(1, int(limite)),
        "segundos": round(time.perf_counter() - inicio, 2),
        "avisos": [
            f"Cartera calculada sólo con los {len(candidatas)} clientes que tienen el ejercicio "
            f"{year} cargado en la caché: no se ha pedido nada al ERP.",
            f"{len(en_cache - set(candidatas))} cliente(s) tienen datos de otros ejercicios y "
            f"{len(fichas - en_cache)} no tienen ningún ejercicio cargado; para incluirlos hay que "
            "cargar el ejercicio desde el panel de la empresa.",
        ],
    }
