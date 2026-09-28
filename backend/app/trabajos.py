"""Trabajos en segundo plano: actualizar desde el ERP sin dejar al usuario esperando.

Traer un ejercicio completo del ERP son ~15 consultas de 7-9 s (el ERP limita el ritmo), así que la
carga inicial se hace como trabajo en curso con progreso consultable, y a partir de ahí el portal se
sirve de la caché.

**El estado vive en la tabla `trabajos`, no en un diccionario del proceso** (era así hasta la Fase
2): con el estado en memoria, un reinicio borraba todo y el portal se quedaba mirando el progreso de
un id que ya no existía, y con más de un proceso el trabajo lanzado en uno era invisible en el otro.

Lo que sigue viviendo en el proceso es **el hilo que hace el trabajo**, y por eso la plataforma se
declara de un solo proceso (lo comprueba `scripts/arranque.py`). Si el proceso muere a mitad, el
trabajo queda «en curso» en la base hasta el siguiente arranque, que lo marca como interrumpido
(`marcar_interrumpidos`) en lugar de dejarlo mintiendo para siempre.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import apicon, bd, cache, db, modulos, servicio

log = logging.getLogger("abga.trabajos")

COLUMNAS = ("id", "tipo", "cod_empresa", "ejercicio", "estado", "mensaje", "progreso", "pasos",
            "resultado", "inicio", "fin", "email")

# Un trabajo «en curso» más viejo que esto ya no se considera activo (evita que un reinicio sin
# marcar bloquee un ejercicio para siempre).
HORAS_VIGENCIA = 6

INTERRUMPIDO = "El proceso se reinició mientras este trabajo estaba en curso."


@dataclass
class Trabajo:
    id: str
    tipo: str
    cod_empresa: str
    year: int
    estado: str = "en_curso"          # en_curso | hecho | error | interrumpido
    mensaje: str = "Iniciando…"
    progreso: float = 0.0
    pasos: list[dict[str, Any]] = field(default_factory=list)
    resultado: dict[str, Any] = field(default_factory=dict)
    inicio: float = field(default_factory=time.time)
    fin: float | None = None
    email: str = ""
    hilo: threading.Thread | None = None    # sólo en memoria: es el hilo que lo ejecuta

    def como_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "tipo": self.tipo, "estado": self.estado, "mensaje": self.mensaje,
            "progreso": round(self.progreso, 3), "pasos": self.pasos, "resultado": self.resultado,
            "cod_empresa": self.cod_empresa, "year": self.year,
            "segundos": round((self.fin or time.time()) - self.inicio, 2),
        }


# ---------- persistencia ----------

def _a_fila(t: Trabajo) -> tuple[Any, ...]:
    return (t.id, t.tipo, t.cod_empresa, int(t.year), t.estado, t.mensaje, round(t.progreso, 4),
            json.dumps(t.pasos, ensure_ascii=False), json.dumps(t.resultado, ensure_ascii=False),
            float(t.inicio), t.fin, t.email or "")


def _de_fila(fila: Any) -> Trabajo:
    return Trabajo(
        id=fila["id"], tipo=fila["tipo"], cod_empresa=fila["cod_empresa"], year=int(fila["ejercicio"]),
        estado=fila["estado"], mensaje=fila["mensaje"] or "", progreso=float(fila["progreso"] or 0.0),
        pasos=json.loads(fila["pasos"] or "[]"), resultado=json.loads(fila["resultado"] or "{}"),
        inicio=float(fila["inicio"]), fin=float(fila["fin"]) if fila["fin"] is not None else None,
        email=fila["email"] or "",
    )


def guardar(t: Trabajo) -> None:
    """Escribe el estado del trabajo. Lo llaman los lanzadores tras cada avance."""
    bd.upsert("trabajos", COLUMNAS, ("id",), _a_fila(t))


def obtener(tid: str) -> Trabajo | None:
    fila = cache.conectar().execute("SELECT * FROM trabajos WHERE id=?", (str(tid),)).fetchone()
    return _de_fila(fila) if fila else None


def listar(limite: int = 20) -> list[dict[str, Any]]:
    filas = cache.conectar().execute(
        "SELECT * FROM trabajos ORDER BY inicio DESC LIMIT ?", (int(limite),)).fetchall()
    return [_de_fila(f).como_json() for f in filas]


def trabajo_en_curso(cod_empresa: str, year: int) -> Trabajo | None:
    """El trabajo activo de ese ejercicio, si lo hay (para no lanzar dos veces el mismo)."""
    fila = cache.conectar().execute(
        "SELECT * FROM trabajos WHERE cod_empresa=? AND ejercicio=? AND estado='en_curso'"
        " AND inicio >= ? ORDER BY inicio DESC LIMIT 1",
        (str(cod_empresa), int(year), time.time() - HORAS_VIGENCIA * 3600)).fetchone()
    return _de_fila(fila) if fila else None


def cargas_en_curso() -> int:
    """Cuántas lecturas al ERP están corriendo ahora mismo.

    Sólo sirve para no apilarlas: una lectura son cientos de peticiones y el ERP contesta 429
    si se le machaca, así que el refresco automático espera a que termine la anterior en lugar
    de lanzar otra al lado.
    """
    fila = cache.conectar().execute(
        "SELECT COUNT(*) FROM trabajos WHERE tipo='carga' AND estado='en_curso'").fetchone()
    return int(fila[0] or 0)


def marcar_interrumpidos() -> int:
    """Al arrancar: lo que quedó «en curso» es de un proceso que ya no existe. Devuelve cuántos."""
    con = cache.conectar()
    cur = con.execute("UPDATE trabajos SET estado='interrumpido', mensaje=?, fin=?"
                      " WHERE estado='en_curso'", (INTERRUMPIDO, time.time()))
    con.commit()
    cuantos = int(cur.rowcount or 0)
    if cuantos:
        log.warning("marcados %s trabajos como interrumpidos (quedaron en curso en el proceso anterior)",
                    cuantos)
    return cuantos


# ---------- lanzadores ----------

def _arrancar(t: Trabajo, correr: Any) -> Trabajo:
    guardar(t)
    t.hilo = threading.Thread(target=correr, name=f"{t.tipo}-{t.id}", daemon=True)
    t.hilo.start()
    return t


def lanzar_carga(cod_empresa: str, year: int, *, modulos_pedidos: list[str] | None = None,
                 forzar: bool = False, email: str | None = None,
                 years: list[int] | None = None) -> Trabajo:
    """Carga (o recarga) los ejercicios que necesitan los módulos pedidos.

    Con `years` se refrescan **sólo** esos ejercicios: es lo que usa el refresco automático de
    la caché caducada, que no debe ponerse a leer cinco años porque alguien abrió un panel.
    """
    existente = trabajo_en_curso(cod_empresa, year)
    if existente:
        return existente

    if years:
        anios = {int(y) for y in years}
    else:
        nombres = modulos_pedidos or [d.nombre for d in modulos.listar_todos() if d.disponible] or ["pyg"]
        anios = set()
        for n in nombres:
            anios.update(modulos.anios_necesarios(n, int(year)))

    t = Trabajo(id=uuid.uuid4().hex[:12], tipo="carga", cod_empresa=str(cod_empresa), year=int(year),
                email=email or "")

    def correr() -> None:
        cli = apicon.cliente()
        try:
            total = len(anios)
            for i, y in enumerate(sorted(anios), start=1):
                t.mensaje = f"Leyendo el ejercicio {y} del ERP…"
                t.pasos.append({"ejercicio": y, "estado": "en_curso", "inicio": time.time()})
                guardar(t)
                info = cli.apuntes(str(cod_empresa), y, forzar=forzar)
                t.pasos[-1].update({
                    "estado": "hecho", "n_asientos": info["n_asientos"], "n_lineas": info["n_lineas"],
                    "cobertura": info.get("cobertura"), "desde_cache": bool(info.get("desde_cache")),
                    "segundos": round(time.time() - t.pasos[-1]["inicio"], 1),
                    "peticiones": info.get("peticiones"),
                })
                t.progreso = i / total
                guardar(t)
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
            guardar(t)

    return _arrancar(t, correr)


def lanzar_informe(nombre_modulo: str, *, cod_empresa: str, year: int, params: dict[str, Any] | None = None,
                   email: str | None = None) -> Trabajo:
    """Genera un informe en segundo plano (útil para los lentos: Autodespro, Proyecciones)."""
    t = Trabajo(id=uuid.uuid4().hex[:12], tipo="informe", cod_empresa=str(cod_empresa), year=int(year),
                email=email or "")

    def correr() -> None:
        try:
            t.mensaje = f"Generando {nombre_modulo}…"
            guardar(t)
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
            guardar(t)

    return _arrancar(t, correr)
