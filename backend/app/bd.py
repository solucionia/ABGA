"""Capa de datos portable: SQLite en local, PostgreSQL en producción (Coolify).

El mismo SQL sirve para los dos motores porque SQLite (≥3.24) y PostgreSQL comparten
`INSERT … ON CONFLICT`. Las únicas diferencias que quedan son dos, y se resuelven aquí:

1. los marcadores: SQLite usa `?` y PostgreSQL `%s`;
2. el autoincremental: `INTEGER PRIMARY KEY AUTOINCREMENT` vs `BIGSERIAL PRIMARY KEY`.

No se usan funciones de fecha del motor: las fechas se guardan en ISO y se comparan como
texto (`TEXT` contra `timestamptz` no es comparable en PostgreSQL).

El motor se elige con `DATABASE_URL`: si empieza por `postgres://` o `postgresql://` se usa
PostgreSQL; si está vacía o es una ruta (o `sqlite:///…`) se usa SQLite. Así el desarrollo
local no necesita infraestructura y producción corre en el Postgres de Coolify cambiando
una sola variable.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any, Sequence

from .config import cargar_config

_local = threading.local()

_PREFIJOS_PG = ("postgres://", "postgresql://", "postgres+")

# Bases que ya tienen el esquema asegurado en este proceso (clave = motor + url). Evita repetir
# `CREATE TABLE IF NOT EXISTS` y, sobre todo, `ALTER TABLE` en cada conexión.
_esquema_asegurado: set[tuple[str, str]] = set()


def reiniciar() -> None:
    """Cierra la conexión del hilo actual (lo usan las pruebas para cambiar de motor)."""
    con = getattr(_local, "con", None)
    if con is not None:
        try:
            con.close()
        except Exception:
            pass
    _local.con = None
    _local.clave = None
    _esquema_asegurado.clear()


def url() -> str:
    """DATABASE_URL del entorno manda; si no, la del `.env`."""
    return (os.environ.get("DATABASE_URL") or cargar_config().database_url or "").strip()


def es_postgres() -> bool:
    return url().lower().startswith(_PREFIJOS_PG)


def _clave_conexion() -> tuple[str, str]:
    return ("postgres" if es_postgres() else "sqlite", url())


# ---------------------------------------------------------------- traducción de SQL

def traducir(sql: str) -> str:
    """Adapta SQL escrito una sola vez a los dos motores."""
    if not es_postgres():
        return sql
    sql = sql.replace("%", "%%")               # literales % (no usamos %s en el SQL escrito)
    sql = sql.replace("?", "%s")
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    return sql


class Cursor:
    """Envoltura mínima: sólo lo que usa el proyecto (fetchone/fetchall/rowcount)."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cur.fetchall()

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount


class Conexion:
    """Envoltura de conexión con las filas siempre accesibles por nombre."""

    def __init__(self, con: Any, postgres: bool) -> None:
        self._con = con
        self.postgres = postgres

    def execute(self, sql: str, args: Sequence[Any] = ()) -> Cursor:
        return Cursor(self._con.execute(traducir(sql), tuple(args)))

    def executescript(self, sql: str) -> None:
        if not self.postgres:
            self._con.executescript(sql)
            return
        for sentencia in [s.strip() for s in sql.split(";") if s.strip()]:
            self._con.execute(traducir(sentencia))

    def commit(self) -> None:
        self._con.commit()

    def rollback(self) -> None:
        try:
            self._con.rollback()
        except Exception:
            pass

    def close(self) -> None:
        self._con.close()


def conectar() -> Conexion:
    """Conexión por hilo, con el esquema garantizado."""
    from . import esquema  # import diferido: evita ciclo con cache

    clave = _clave_conexion()
    con = getattr(_local, "con", None)
    if con is not None and getattr(_local, "clave", None) == clave:
        return con

    if es_postgres():
        import psycopg
        from psycopg.rows import dict_row

        con = Conexion(psycopg.connect(url(), row_factory=dict_row), postgres=True)
    else:
        ruta = _ruta_sqlite()
        crudo = sqlite3.connect(ruta, timeout=30, check_same_thread=False)
        crudo.row_factory = sqlite3.Row
        crudo.execute("PRAGMA journal_mode=WAL")
        crudo.execute("PRAGMA synchronous=NORMAL")
        con = Conexion(crudo, postgres=False)

    # El esquema y las migraciones se aseguran UNA vez por proceso y base. Hacerlo en cada conexión
    # no sólo es más lento: `ALTER TABLE` necesita bloqueo exclusivo y, con otra transacción abierta,
    # dejaba la aplicación colgada (visto probando en modo producción).
    if clave not in _esquema_asegurado:
        con.executescript(esquema.ESQUEMA)
        con.commit()
        esquema.migrar(con)
        _esquema_asegurado.add(clave)
    _local.con, _local.clave = con, clave
    return con


def _ruta_sqlite() -> str:
    u = url()
    if u.startswith("sqlite:///"):
        return u[len("sqlite:///"):]
    if u.startswith("sqlite://"):
        return u[len("sqlite://"):]
    if u:
        return u
    return str(cargar_config().cache_db)


# ---------------------------------------------------------------- ayudas de escritura

def _columnas_sql(columnas: Sequence[str]) -> str:
    return ", ".join(columnas)


def upsert(tabla: str, columnas: Sequence[str], clave: Sequence[str], args: Sequence[Any]) -> None:
    """INSERT … ON CONFLICT: válido tal cual en SQLite y en PostgreSQL."""
    marcadores = ", ".join("?" for _ in columnas)
    actualiza = ", ".join(f"{c}=excluded.{c}" for c in columnas if c not in set(clave))
    sql = (f"INSERT INTO {tabla} ({_columnas_sql(columnas)}) VALUES ({marcadores})"
           f" ON CONFLICT ({_columnas_sql(clave)})")
    sql += f" DO UPDATE SET {actualiza}" if actualiza else " DO NOTHING"
    con = conectar()
    con.execute(sql, args)
    con.commit()


def insertar_ignorando(tabla: str, columnas: Sequence[str], args: Sequence[Any]) -> None:
    marcadores = ", ".join("?" for _ in columnas)
    con = conectar()
    con.execute(f"INSERT INTO {tabla} ({_columnas_sql(columnas)}) VALUES ({marcadores})"
                " ON CONFLICT DO NOTHING", args)
    con.commit()


def insertar_devolviendo_id(tabla: str, columnas: Sequence[str], args: Sequence[Any]) -> int:
    """Devuelve el id generado; funciona en los dos motores con RETURNING (SQLite ≥3.35)."""
    marcadores = ", ".join("?" for _ in columnas)
    fila = conectar().execute(
        f"INSERT INTO {tabla} ({_columnas_sql(columnas)}) VALUES ({marcadores}) RETURNING id",
        args,
    ).fetchone()
    if fila is None:
        return 0
    conectar().commit()
    return int(fila["id"])
