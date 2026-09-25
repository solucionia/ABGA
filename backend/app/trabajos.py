"""Trabajos en segundo plano: actualizar desde el ERP sin dejar al usuario esperando.

Traer un ejercicio completo del ERP son ~15 consultas de 7-9 s (el ERP limita el ritmo),
así que la carga inicial se hace como trabajo en curso con progreso consultable, y a partir
de ahí el portal se sirve de la caché.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import apicon, db, modulos, servicio

log = logging.getLogger("abga.trabajos")


@dataclass
class Trabajo:
    id: str
    tipo: str
    cod_empresa: str
    year: int
    estado: str = "en_curso"          # en_curso | hecho | error
    mensaje: str = "Iniciando…"
    progreso: float = 0.0
    pasos: list[dict[str, Any]] = field(default_factory=list)
    resultado: dict[str, Any] = field(default_factory=dict)
    inicio: float = field(default_factory=time.time)
    fin: float | None = None
    hilo: threading.Thread | None = None

    def como_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "tipo": self.tipo, "estado": self.estado, "mensaje": self.mensaje,
            "progreso": round(self.progreso, 3), "pasos": self.pasos, "resultado": self.resultado,
            "cod_empresa": self.cod_empresa, "year": self.year,
            "segundos": round((self.fin or time.time()) - self.inicio, 2),
        }


_trabajos: dict[str, Trabajo] = {}
_lock = threading.Lock()
_ultimo: dict[str, str] = {}   # (empresa:year) -> id del último trabajo


def obtener(tid: str) -> Trabajo | None:
    return _trabajos.get(tid)


def listar(limite: int = 20) -> list[dict[str, Any]]:
    with _lock:
        ordenados = sorted(_trabajos.values(), key=lambda t: t.inicio, reverse=True)
    return [t.como_json() for t in ordenados[:limite]]


def trabajo_en_curso(cod_empresa: str, year: int) -> Trabajo | None:
    clave = f"{cod_empresa}:{year}"
    with _lock:
        tid = _ultimo.get(clave)
    t = _trabajos.get(tid) if tid else None
    return t if t and t.estado == "en_curso" else None


def lanzar_carga(cod_empresa: str, year: int, *, modulos_pedidos: list[str] | None = None,
                 forzar: bool = False, email: str | None = None) -> Trabajo:
    """Carga (o recarga) los ejercicios que necesitan los módulos pedidos."""
    existente = trabajo_en_curso(cod_empresa, year)
    if existente:
        return existente

    nombres = modulos_pedidos or [d.nombre for d in modulos.listar_todos() if d.disponible] or ["pyg"]
    anios: set[int] = set()
    for n in nombres:
        anios.update(modulos.anios_necesarios(n, int(year)))

    t = Trabajo(id=uuid.uuid4().hex[:12], tipo="carga", cod_empresa=str(cod_empresa), year=int(year))
    with _lock:
        _trabajos[t.id] = t
        _ultimo[f"{cod_empresa}:{year}"] = t.id

    def correr() -> None:
        cli = apicon.cliente()
        try:
            total = len(anios)
            for i, y in enumerate(sorted(anios), start=1):
                t.mensaje = f"Leyendo el ejercicio {y} del ERP…"
                t.pasos.append({"ejercicio": y, "estado": "en_curso", "inicio": time.time()})
                info = cli.apuntes(str(cod_empresa), y, forzar=forzar)
                t.pasos[-1].update({
                    "estado": "hecho", "n_asientos": info["n_asientos"], "n_lineas": info["n_lineas"],
                    "cobertura": info.get("cobertura"), "desde_cache": bool(info.get("desde_cache")),
                    "segundos": round(time.time() - t.pasos[-1]["inicio"], 1),
                    "peticiones": info.get("peticiones"),
                })
                t.progreso = i / total
            t.estado = "hecho"
            t.mensaje = "Datos actualizados"
            t.resultado = {"ejercicios": t.pasos}
        except Exception as e:  # se informa en el propio trabajo, sin romper la petición
            log.exception("fallo cargando %s/%s", cod_empresa, year)
            t.estado = "error"
            t.mensaje = str(e)
            t.resultado = {"error": str(e)}
            db.registrar_ejecucion(cod_empresa=str(cod_empresa), ejercicio=int(year), modulos="carga_erp",
                                   origen="trabajo", email=email, segundos=time.time() - t.inicio,
                                   estado="error_erp", desde_cache=False, detalle=str(e))
        finally:
            t.fin = time.time()

    t.hilo = threading.Thread(target=correr, name=f"carga-{t.id}", daemon=True)
    t.hilo.start()
    return t


def lanzar_informe(nombre_modulo: str, *, cod_empresa: str, year: int, params: dict[str, Any] | None = None,
                   email: str | None = None) -> Trabajo:
    """Genera un informe en segundo plano (útil para los lentos: Autodespro, Proyecciones)."""
    t = Trabajo(id=uuid.uuid4().hex[:12], tipo="informe", cod_empresa=str(cod_empresa), year=int(year))
    with _lock:
        _trabajos[t.id] = t

    def correr() -> None:
        try:
            t.mensaje = f"Generando {nombre_modulo}…"
            r = servicio.ejecutar(nombre_modulo, cod_empresa=str(cod_empresa), year=int(year),
                                  params=params, email=email, origen="trabajo")
            t.progreso = 1.0
            if r.status == "ok":
                t.estado, t.mensaje = "hecho", "Informe listo"
                t.resultado = {"html": r.html, "meta": r.meta, "avisos": r.avisos}
            else:
                t.estado, t.mensaje = "error", r.error or "error"
                t.resultado = {"error": r.error}
        except Exception as e:
            log.exception("fallo generando %s", nombre_modulo)
            t.estado, t.mensaje, t.resultado = "error", str(e), {"error": str(e)}
        finally:
            t.fin = time.time()

    t.hilo = threading.Thread(target=correr, name=f"informe-{t.id}", daemon=True)
    t.hilo.start()
    return t
