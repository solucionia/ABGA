"""Pone la base al día con las migraciones versionadas (alembic).

Es lo que se ejecuta al arrancar la aplicación (lo hace `bd.conectar()` sin que nadie se acuerde) y
lo que conviene poder lanzar a mano antes de un despliegue:

    ./.venv/bin/python backend/scripts/migrar.py              # aplica lo que falte
    ./.venv/bin/python backend/scripts/migrar.py --estado     # en qué versión está la base
    ./.venv/bin/python backend/scripts/migrar.py --historial  # qué migraciones hay

Usa la misma base que la plataforma: `DATABASE_URL` del entorno o del `.env`.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import migraciones  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Migraciones del esquema.")
    ap.add_argument("--estado", action="store_true", help="sólo dice en qué versión está la base")
    ap.add_argument("--historial", action="store_true", help="lista las migraciones del repositorio")
    args = ap.parse_args()

    destino = migraciones.url_para_alembic()
    # La contraseña fuera del mensaje: se enseña sólo el tipo de motor y la base.
    visible = destino.split("://")[0] + "://…/" + destino.rsplit("/", 1)[-1] if "://" in destino else destino
    print(f"base: {visible}")

    if args.historial:
        for revision, anterior, resumen in migraciones.historial():
            print(f"  {revision}  (viene de {anterior})  {resumen}")
        return 0

    antes = migraciones.version()
    print(f"versión antes: {antes or '(sin migrar)'}")

    if not args.estado:
        migraciones.aplicar()

    despues = migraciones.version()
    cabecera = migraciones.cabecera()
    print(f"versión después: {despues or '(sin migrar)'}   ·   última del repositorio: {cabecera}")
    if despues != cabecera:
        print("FALLO: la base no está en la última versión")
        return 1
    print("ok: la base está al día")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
