"""Criterios de análisis ajustados por cliente.

Revision ID: 0003_umbrales_empresa
Revises: 0002_observabilidad
Create Date: 2026-09-27

El catálogo de análisis juzga con unos umbrales generales (los del 35% de concentración, los 90 días
de antigüedad, los límites de auditoría…). Valen para casi toda la cartera, pero no para todos: una
empresa estacional no aguanta el mismo saldo viejo que una industrial, y discutir un rojo con el
cliente exige poder decir «se le mide con el criterio que pactamos, no con el general».

La tabla guarda **sólo lo que se aparta del general**, una fila por empresa y criterio, con quién y
cuándo lo cambió. Sin fila, se aplica el valor general: así una base vieja sigue funcionando igual
después de migrar y añadir un criterio nuevo al catálogo no obliga a rellenar nada.

El índice único es el que sostiene el `INSERT … ON CONFLICT (cod_empresa, clave)` del upsert: sin él,
ajustar el mismo criterio dos veces duplicaría la fila y el valor aplicado dependería del orden.
"""

from __future__ import annotations

from alembic import op

revision = "0003_umbrales_empresa"
down_revision = "0002_observabilidad"
branch_labels = None
depends_on = None

TABLAS = """
CREATE TABLE IF NOT EXISTS umbrales_empresa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cod_empresa TEXT NOT NULL,
    clave TEXT NOT NULL,
    valor DOUBLE PRECISION NOT NULL,
    actualizado TEXT NOT NULL DEFAULT '',
    actualizado_por TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_umbrales_empresa ON umbrales_empresa (cod_empresa, clave);
"""


def _ddl(motor: str) -> str:
    """El SQL escrito una vez para los dos motores (`AUTOINCREMENT` es de SQLite)."""
    if motor == "postgresql":
        return TABLAS.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    return TABLAS


def upgrade() -> None:
    for sentencia in [s.strip() for s in _ddl(op.get_bind().dialect.name).split(";") if s.strip()]:
        op.execute(sentencia)


def downgrade() -> None:
    """Se pierden los ajustes (son criterios de trabajo, no datos del cliente): se vuelve al general."""
    op.execute("DROP TABLE IF EXISTS umbrales_empresa")
