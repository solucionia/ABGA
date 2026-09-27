"""Migraciones versionadas del esquema, con alembic.

Una sola vía para crear y cambiar la base:

* una base **nueva** se construye aplicando todas las migraciones;
* una base **vieja** (la de producción) se pone al día aplicando las que le falten, y queda
  marcada con su versión en la tabla `alembic_version`;
* `bd.conectar()` aplica lo que falte la primera vez que el proceso toca una base, así que los
  scripts y las pruebas siguen funcionando sin pasos previos.

La primera migración reproduce el esquema que ya existía, con `CREATE TABLE IF NOT EXISTS` y las
columnas añadidas después: aplicarla a la base de producción no rompe nada y sólo la deja marcada
en la versión inicial.

Para trabajar a mano:

    ./.venv/bin/python backend/scripts/migrar.py             # aplica lo que falte y dice la versión
    ./.venv/bin/python backend/scripts/migrar.py --historial # qué migraciones hay
"""

from __future__ import annotations

import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1]  # …/backend
DIRECTORIO = RAIZ / "migraciones"


def _config():
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(DIRECTORIO))
    cfg.set_main_option("path_separator", "os")
    return cfg


def url_para_alembic() -> str:
    """La misma base que usa la aplicación, con el dialecto que entiende SQLAlchemy.

    Ojo con los prefijos: psycopg acepta `postgres://` y `postgresql://`, pero SQLAlchemy necesita
    `postgresql+psycopg://` para usar psycopg 3 (si no, busca psycopg2 y falla al conectar).
    """
    from . import bd

    destino = (bd.url() or "").strip()
    if not destino:
        # Mismo defecto que la aplicación: SQLite en el fichero de la caché.
        from .config import cargar_config

        destino = f"sqlite:///{cargar_config().cache_db}"
    if destino.startswith("postgres://"):
        destino = "postgresql://" + destino[len("postgres://"):]
    if destino.startswith("postgresql://"):
        destino = "postgresql+psycopg://" + destino[len("postgresql://"):]
    if destino.startswith("sqlite:///"):
        return destino
    if destino.startswith("sqlite://"):
        return "sqlite:///" + destino[len("sqlite://"):]
    return destino


def aplicar() -> None:
    """Pone la base al día con la última migración."""
    from alembic import command

    command.upgrade(_config(), "head")


def version() -> str | None:
    """Versión en la que está la base (`None` si nunca se ha migrado)."""
    from sqlalchemy import create_engine, text

    motor = create_engine(url_para_alembic())
    try:
        with motor.connect() as conexion:
            return conexion.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return None
    finally:
        motor.dispose()


def cabecera() -> str | None:
    """Última versión que conocen las migraciones del repositorio."""
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(_config()).get_current_head()


def historial() -> list[tuple[str, str, str]]:
    """(versión, versión anterior, resumen) de cada migración, de la más vieja a la más nueva."""
    from alembic.script import ScriptDirectory

    guion = ScriptDirectory.from_config(_config())
    filas: list[tuple[str, str, str]] = []
    for revision in guion.walk_revisions():
        anterior = revision.down_revision
        if isinstance(anterior, (list, tuple)):   # una revisión puede venir de varias
            anterior = ",".join(str(a) for a in anterior)
        resumen = (revision.doc or "").strip().splitlines()
        filas.append((str(revision.revision), str(anterior or "-"),
                      resumen[0] if resumen else ""))
    return list(reversed(filas))
