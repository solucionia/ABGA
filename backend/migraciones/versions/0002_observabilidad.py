"""Observabilidad: identificador de petición en las ejecuciones y avisos con estado.

Revision ID: 0002_observabilidad
Revises: 0001_esquema_inicial
Create Date: 2026-09-27

Qué añade y por qué:

* `ejecuciones.id_peticion` — sin esto, un informe registrado y las líneas del registro de ese
  momento no se podían atar (con dos personas usando el portal, «el informe falló» y «la ejecución
  que falló» eran dos cosas distintas que había que emparejar a mano por la hora).
* `ejecuciones.cobertura` — el veredicto en claro (`completa`, `parcial`…) junto al texto libre de
  `detalle`: así «cuántos informes salieron incompletos» es una consulta y no una búsqueda de texto.
* La tabla `avisos` — lo que no puede pasar desapercibido, con estado (pendiente/atendido) y contador
  para agrupar los repetidos.

En producción la base ya tenía datos: los dos `ADD COLUMN` van con valor por defecto y sólo se
ejecutan si la columna no está, igual que en la 0001 (en PostgreSQL un `ADD COLUMN NOT NULL DEFAULT ''`
no reescribe la tabla).
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "0002_observabilidad"
down_revision = "0001_esquema_inicial"
branch_labels = None
depends_on = None

TABLAS = """
CREATE TABLE IF NOT EXISTS avisos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    cod_empresa TEXT NOT NULL,
    ejercicio INTEGER NOT NULL DEFAULT 0,
    modulo TEXT NOT NULL DEFAULT '',
    detalle TEXT,
    origen TEXT NOT NULL DEFAULT 'portal',
    email TEXT,
    id_peticion TEXT NOT NULL DEFAULT '',
    primero TEXT NOT NULL,
    ultimo TEXT NOT NULL,
    veces INTEGER NOT NULL DEFAULT 1,
    atendido INTEGER NOT NULL DEFAULT 0,
    atendido_por TEXT,
    atendido_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_avisos_pendientes ON avisos (atendido, ultimo DESC);
"""

COLUMNAS_ANADIDAS = (
    ("ejecuciones", "id_peticion", "ALTER TABLE ejecuciones ADD COLUMN id_peticion TEXT NOT NULL DEFAULT ''"),
    ("ejecuciones", "cobertura", "ALTER TABLE ejecuciones ADD COLUMN cobertura TEXT NOT NULL DEFAULT ''"),
)


def _tiene_columna(tabla: str, columna: str) -> bool:
    inspector = inspect(op.get_bind())
    return columna in {c["name"] for c in inspector.get_columns(tabla)}


def _ddl(motor: str) -> str:
    """El SQL escrito una vez para los dos motores (`AUTOINCREMENT` es de SQLite)."""
    if motor == "postgresql":
        return TABLAS.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    return TABLAS


def upgrade() -> None:
    for sentencia in [s.strip() for s in _ddl(op.get_bind().dialect.name).split(";") if s.strip()]:
        op.execute(sentencia)
    for tabla, columna, sentencia in COLUMNAS_ANADIDAS:
        # Se pregunta antes de tocar: `ALTER TABLE` pide bloqueo exclusivo y con otra transacción
        # abierta dejó la aplicación colgada (ya pasó en producción).
        if not _tiene_columna(tabla, columna):
            op.execute(sentencia)


def downgrade() -> None:
    """Quita lo que añade esta migración (los avisos se pierden: son un registro de incidencias,
    no datos del cliente)."""
    op.execute("DROP TABLE IF EXISTS avisos")
    for tabla, columna, _ in COLUMNAS_ANADIDAS:
        if _tiene_columna(tabla, columna):
            op.execute(f"ALTER TABLE {tabla} DROP COLUMN {columna}")
