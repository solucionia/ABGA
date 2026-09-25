"""Caché de apuntes por (empresa, ejercicio), tokens y resultados de cálculo.

Motivo: el ERP tarda 6-11 s por página y devuelve 429 si se le machaca. Traer un
ejercicio completo cuesta ~8 peticiones, así que se guarda y se reutiliza.

El motor (SQLite en local, PostgreSQL en producción) lo elige `bd.py` con `DATABASE_URL`;
aquí sólo se escribe SQL portable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import bd
from .config import cargar_config


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conectar() -> bd.Conexion:
    """Conexión por hilo con el esquema garantizado (la elige `bd` según DATABASE_URL)."""
    return bd.conectar()



# ---------- apuntes ----------

def leer_apuntes(empresa: str, ejercicio: int, ttl: int | None = None) -> dict[str, Any] | None:
    cfg = cargar_config()
    ttl = cfg.ttl_apuntes if ttl is None else ttl
    fila = conectar().execute(
        "SELECT * FROM apuntes WHERE empresa=? AND ejercicio=?", (empresa, ejercicio)
    ).fetchone()
    if not fila:
        return None
    edad = (datetime.now(timezone.utc) - datetime.fromisoformat(fila["actualizado"])).total_seconds()
    if ttl >= 0 and edad > ttl:
        return None
    return {
        "empresa": fila["empresa"],
        "year": fila["ejercicio"],
        "asientos": json.loads(fila["asientos_json"]),
        "n_asientos": fila["n_asientos"],
        "n_lineas": fila["n_lineas"],
        "resultados_totales": fila["resultados_totales"],
        "cobertura": fila["cobertura"],
        "segundos": fila["segundos"],
        "actualizado": fila["actualizado"],
        "edad_segundos": round(edad),
        "desde_cache": True,
    }


def guardar_apuntes(empresa: str, ejercicio: int, asientos: list[dict], *, resultados_totales: int | None,
                   cobertura: str, segundos: float) -> None:
    bd.upsert(
        "apuntes",
        ("empresa", "ejercicio", "asientos_json", "n_asientos", "n_lineas", "resultados_totales",
         "cobertura", "segundos", "actualizado"),
        ("empresa", "ejercicio"),
        (empresa, ejercicio, json.dumps(asientos, ensure_ascii=False), len(asientos),
         sum(len(a.get("Detalles") or []) for a in asientos), resultados_totales, cobertura,
         round(segundos, 2), ahora()),
    )


def info_cache(empresa: str | None = None) -> list[dict[str, Any]]:
    sql = ("SELECT empresa, ejercicio, n_asientos, n_lineas, resultados_totales, cobertura,"
           " segundos, actualizado FROM apuntes")
    args: tuple = ()
    if empresa:
        sql += " WHERE empresa=?"
        args = (empresa,)
    sql += " ORDER BY empresa, ejercicio"
    return [dict(f) for f in conectar().execute(sql, args).fetchall()]


def invalidar(empresa: str, ejercicio: int | None = None) -> int:
    con = conectar()
    if ejercicio is None:
        cur = con.execute("DELETE FROM apuntes WHERE empresa=?", (empresa,))
    else:
        cur = con.execute("DELETE FROM apuntes WHERE empresa=? AND ejercicio=?", (empresa, ejercicio))
    con.commit()
    return cur.rowcount


# ---------- tokens ----------

def leer_token(empresa: str) -> dict[str, Any] | None:
    fila = conectar().execute("SELECT * FROM tokens WHERE empresa=?", (empresa,)).fetchone()
    if not fila:
        return None
    if datetime.fromisoformat(fila["expira_en"]) <= datetime.now(timezone.utc):
        return None
    return {"access_token": fila["access_token"], "expira_en": fila["expira_en"]}


def guardar_token(empresa: str, access_token: str, expira_en: str) -> None:
    bd.upsert(
        "tokens",
        ("empresa", "access_token", "expira_en", "actualizado"),
        ("empresa",),
        (empresa, access_token, expira_en, ahora()),
    )


# ---------- resultados de cálculo ----------

def leer_calc(clave: str, ttl: int | None = None) -> Any | None:
    fila = conectar().execute("SELECT * FROM calc_cache WHERE clave=?", (clave,)).fetchone()
    if not fila:
        return None
    if ttl is not None and ttl >= 0:
        edad = (datetime.now(timezone.utc) - datetime.fromisoformat(fila["actualizado"])).total_seconds()
        if edad > ttl:
            return None
    return json.loads(fila["payload"])


def guardar_calc(clave: str, payload: Any) -> None:
    bd.upsert(
        "calc_cache",
        ("clave", "payload", "actualizado"),
        ("clave",),
        (clave, json.dumps(payload, ensure_ascii=False), ahora()),
    )
