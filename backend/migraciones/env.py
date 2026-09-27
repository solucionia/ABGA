"""Entorno de alembic: la base la dice la aplicación, no un fichero de configuración.

No hay `sqlalchemy.url` en ningún fichero: se lee de `app.migraciones.url_para_alembic()`, que a su
vez sale del `DATABASE_URL` (o de la caché SQLite si no hay ninguno), así que las migraciones van
siempre a la misma base que usa la plataforma. Tampoco hay modelos de SQLAlchemy: el esquema se
escribe a mano en las migraciones.
"""

from __future__ import annotations

import pathlib
import sys

from alembic import context
from sqlalchemy import create_engine, pool

RAIZ = pathlib.Path(__file__).resolve().parents[1]  # …/backend
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.migraciones import url_para_alembic  # noqa: E402

target_metadata = None


def run_migrations_offline() -> None:
    """Modo `--sql`: escribe el SQL en lugar de ejecutarlo (para revisarlo a mano)."""
    context.configure(url=url_para_alembic(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    motor = create_engine(url_para_alembic(), poolclass=pool.NullPool)
    with motor.connect() as conexion:
        context.configure(connection=conexion, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    motor.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
