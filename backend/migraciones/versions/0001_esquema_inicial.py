"""Esquema inicial: el que ya estaba en producción, ahora versionado.

Revision ID: 0001_esquema_inicial
Revises:
Create Date: 2026-09-27

Reproduce el esquema que existía antes de tener migraciones (el que se aplicaba con
`CREATE TABLE IF NOT EXISTS` en cada conexión, más las columnas añadidas después). Se escribe con
`IF NOT EXISTS` y con comprobación de columnas **a propósito**: aplicarla a la base de producción no
toca nada y sólo la deja marcada en la versión inicial, que es justo lo que hace falta para empezar
a versionar sin recrear datos.

A partir de aquí, cada cambio de esquema es un fichero nuevo en esta carpeta (con su `downgrade`), y
el DDL deja de duplicarse en `app/esquema.py`.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "0001_esquema_inicial"
down_revision = None
branch_labels = None
depends_on = None

TABLAS = """
CREATE TABLE IF NOT EXISTS apuntes (
    empresa TEXT NOT NULL,
    ejercicio INTEGER NOT NULL,
    asientos_json TEXT NOT NULL,
    n_asientos INTEGER NOT NULL,
    n_lineas INTEGER NOT NULL,
    resultados_totales INTEGER,
    cobertura TEXT NOT NULL,
    segundos REAL,
    actualizado TEXT NOT NULL,
    PRIMARY KEY (empresa, ejercicio)
);
CREATE TABLE IF NOT EXISTS tokens (
    empresa TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    expira_en TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calc_cache (
    clave TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usuarios (
    email TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    rol TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS empresas (
    cod_empresa TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    ejercicio_inicio INTEGER,
    notas TEXT,
    pin_hash TEXT
);
CREATE TABLE IF NOT EXISTS permisos (
    email TEXT NOT NULL,
    cod_empresa TEXT NOT NULL,
    PRIMARY KEY (email, cod_empresa)
);
CREATE TABLE IF NOT EXISTS ejecuciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instante TEXT NOT NULL,
    cod_empresa TEXT NOT NULL,
    ejercicio INTEGER,
    modulos TEXT NOT NULL,
    origen TEXT NOT NULL,
    email TEXT,
    segundos REAL,
    estado TEXT NOT NULL,
    desde_cache INTEGER NOT NULL DEFAULT 0,
    detalle TEXT,
    importes TEXT
);
CREATE INDEX IF NOT EXISTS idx_ejecuciones_emp ON ejecuciones (cod_empresa, instante DESC);
CREATE TABLE IF NOT EXISTS intentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave TEXT NOT NULL,
    instante TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intentos_clave ON intentos (clave, instante DESC);
CREATE TABLE IF NOT EXISTS trabajos (
    id TEXT PRIMARY KEY,
    tipo TEXT NOT NULL,
    cod_empresa TEXT NOT NULL,
    ejercicio INTEGER NOT NULL,
    estado TEXT NOT NULL,
    mensaje TEXT,
    progreso REAL NOT NULL DEFAULT 0,
    pasos TEXT NOT NULL DEFAULT '[]',
    resultado TEXT NOT NULL DEFAULT '{}',
    inicio REAL NOT NULL,
    fin REAL,
    email TEXT
);
CREATE INDEX IF NOT EXISTS idx_trabajos_inicio ON trabajos (inicio DESC);
"""

# Columnas que se añadieron a tablas que ya existían (antes se aplicaban desde `esquema.MIGRACIONES`).
COLUMNAS_ANADIDAS = (
    ("empresas", "pin_hash", "ALTER TABLE empresas ADD COLUMN pin_hash TEXT"),
)


def _tiene_columna(tabla: str, columna: str) -> bool:
    inspector = inspect(op.get_bind())
    return columna in {c["name"] for c in inspector.get_columns(tabla)}


def _ddl(motor: str) -> str:
    """El SQL escrito una vez para los dos motores.

    `INTEGER PRIMARY KEY AUTOINCREMENT` es de SQLite: en PostgreSQL hay que usar una secuencia.
    Es la misma traducción que aplica `bd.traducir()` en el funcionamiento normal, repetida aquí a
    propósito: una migración tiene que poder ejecutarse sola, sin depender del código de la
    aplicación (que dentro de un año habrá cambiado).
    """
    if motor == "postgresql":
        return TABLAS.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    return TABLAS


def upgrade() -> None:
    for sentencia in [s.strip() for s in _ddl(op.get_bind().dialect.name).split(";") if s.strip()]:
        op.execute(sentencia)
    for tabla, columna, sentencia in COLUMNAS_ANADIDAS:
        # Se pregunta antes de tocar: `ALTER TABLE` pide bloqueo exclusivo y, con otra transacción
        # abierta, dejaba la aplicación colgada (pasó en producción).
        if not _tiene_columna(tabla, columna):
            op.execute(sentencia)


def downgrade() -> None:
    """Tira todas las tablas. Es destructivo y no se usa en producción: existe para poder deshacer
    la migración en una base de pruebas."""
    for tabla in ("trabajos", "intentos", "ejecuciones", "permisos", "empresas", "usuarios",
                  "calc_cache", "tokens", "apuntes"):
        op.execute(f"DROP TABLE IF EXISTS {tabla}")
