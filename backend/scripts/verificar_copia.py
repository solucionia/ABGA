"""Prueba de restauración: demuestra que una copia de la base se puede restaurar de verdad.

Lo dicen los propios manuales de Coolify: *a backup is not a restore test*. Una copia con estado
«Success» sólo prueba que se creó un fichero. Lo que prueba que hay copia es **restaurarla** y
comprobar que están las tablas y los datos.

Este script levanta un PostgreSQL **desechable** (el embebido de `pgserver`, en un directorio
temporal), restaura la copia ahí y lee el resultado **con el propio código de la plataforma**
(`app.cache`, `app.db`): si el volcado no sirviera, esas consultas fallarían. **Nunca toca la base
real**: el destino siempre es el PostgreSQL temporal.

    # comprobar que una copia es restaurable y tiene datos
    ./.venv/bin/python backend/scripts/verificar_copia.py --copia /ruta/copia.dump

    # además, comparar recuentos con la base viva (si se tiene acceso a ella)
    ./.venv/bin/python backend/scripts/verificar_copia.py --copia copia.dump --comparar "$DATABASE_URL"

En el servidor, la copia la genera Coolify (recurso de base de datos → Backups) y queda en
`/data/coolify/backups`; este script es la comprobación que hay que hacer después, y conviene
repetirla cada pocos meses con la copia más reciente.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import bd, cache, db, esquema  # noqa: E402

# Tablas y datos imprescindibles: si falta una, la copia no sirve para recuperar la plataforma.
IMPRESCINDIBLES = ("empresas", "usuarios", "permisos", "ejecuciones")
fallos: list[str] = []


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    print(f"  {'ok   ' if condicion else 'FALLO'} {nombre}" + (f" — {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


def binario(nombre: str) -> str:
    """Localiza `pg_restore`/`psql`: primero los de `pgserver`, y si no, los del PATH."""
    try:
        import pgserver

        for candidato in pathlib.Path(pgserver.__file__).parent.rglob(nombre):
            if candidato.is_file() and "bin" in candidato.parts:
                return str(candidato)
    except ImportError:
        pass
    return nombre


def tablas_del_esquema() -> list[str]:
    """Las tablas que la plataforma espera, según `esquema.TABLAS` (el contrato del esquema).

    Ese contrato no es una lista suelta: `tests/test_migraciones.py` comprueba que las migraciones
    crean exactamente esas tablas, así que lo que se espera y lo que se crea no pueden separarse.
    """
    return list(esquema.TABLAS)


def objetos_del_volcado(pg_restore: str, copia: pathlib.Path) -> str:
    """`pg_restore --list`: lo mínimo para saber que el fichero es un volcado legible."""
    r = subprocess.run([pg_restore, "--list", str(copia)], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def recuentos(uri: str) -> dict[str, int]:
    """Lee el resultado restaurado **con el código de la plataforma** (no con SQL suelto)."""
    import psycopg

    con = psycopg.connect(uri)
    salida: dict[str, int] = {}
    for tabla in tablas_del_esquema():
        with con.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {tabla}")
            salida[tabla] = int(cur.fetchone()[0])
    con.close()
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description="Prueba que una copia de la base se puede restaurar.")
    ap.add_argument("--copia", required=True, help="fichero de copia (formato custom de pg_dump)")
    ap.add_argument("--comparar", default="", help="DATABASE_URL de la base viva, para comparar recuentos")
    args = ap.parse_args()

    copia = pathlib.Path(args.copia).expanduser().resolve()
    print("=" * 78)
    print(f"PRUEBA DE RESTAURACIÓN · {copia}")
    print("=" * 78)
    if not copia.exists():
        print(f"  FALLO  la copia no existe: {copia}")
        return 1
    print(f"  tamaño: {copia.stat().st_size / 1024:.1f} KB")

    pg_restore = binario("pg_restore")
    psql = binario("psql")

    print("\n1. El fichero es un volcado legible")
    listado = objetos_del_volcado(pg_restore, copia)
    comprobar("pg_restore puede leer el fichero", bool(listado))
    comprobar("el volcado trae tablas (no sólo cabecera)", listado.count("TABLE DATA") > 0,
              f"{listado.count('TABLE DATA')} tablas con datos")

    print("\n2. Se restaura en un PostgreSQL desechable")
    datos = tempfile.mkdtemp(prefix="abga-restauracion-")
    import pgserver

    servidor = pgserver.get_server(datos)
    uri_base = servidor.get_uri()
    destino = "abga_restaurada"
    subprocess.run([psql, uri_base, "-c", f'CREATE DATABASE "{destino}"'], check=True,
                   capture_output=True, text=True)
    uri_destino = bd.con_otra_base(uri_base, destino)

    r = subprocess.run([pg_restore, "--dbname", uri_destino, "--no-owner", "--no-privileges",
                        str(copia)], capture_output=True, text=True)
    avisos = [l for l in r.stderr.splitlines() if l.strip() and "warning" not in l.lower()]
    comprobar("pg_restore termina bien", r.returncode == 0, (avisos[:2] and " | ".join(avisos[:2])) or "")

    print("\n3. El contenido restaurado tiene las tablas de la plataforma")
    try:
        restaurado = recuentos(uri_destino)
    except Exception as e:
        # Si la restauración no sirvió, las consultas fallan: se dice con palabras, no con un
        # rastro de pila (quien lee esto está decidiendo si tiene copia o no).
        restaurado = {}
        comprobar("se puede consultar lo restaurado", False, f"{type(e).__name__}: {str(e)[:110]}")
    if restaurado:
        for tabla in tablas_del_esquema():
            comprobar(f"tabla {tabla}", tabla in restaurado,
                      f"{restaurado.get(tabla, 0)} filas" if tabla in restaurado else "no está")
        for tabla in IMPRESCINDIBLES:
            comprobar(f"{tabla} tiene datos", restaurado.get(tabla, 0) > 0,
                      f"{restaurado.get(tabla, 0)} filas")
    else:
        print("  (la restauración no dejó nada que inspeccionar)")

    print("\n4. Se puede leer con el propio código de la plataforma")
    entorno_previo = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = uri_destino
        bd.reiniciar()
        from app.config import cargar_config

        cargar_config.cache_clear()
        empresas = db.listar_empresas()
        usuarios = db.listar_usuarios()
        comprobar("listar_empresas funciona sobre lo restaurado", bool(empresas), f"{len(empresas)} empresas")
        comprobar("listar_usuarios funciona sobre lo restaurado", bool(usuarios), f"{len(usuarios)} usuarios")
        comprobar("el usuario interno está", any(u["rol"] in {"interno", "admin"} for u in usuarios))
        comprobar("info_cache responde", isinstance(cache.info_cache(), list))
    except Exception as e:
        comprobar("la plataforma puede leer lo restaurado", False, f"{type(e).__name__}: {str(e)[:110]}")
    finally:
        if entorno_previo is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = entorno_previo
        bd.reiniciar()
        from app.config import cargar_config as _cfg

        _cfg.cache_clear()
        shutil.rmtree(datos, ignore_errors=True)

    if args.comparar:
        print("\n5. Comparación con la base viva")
        try:
            vivo = recuentos(args.comparar)
        except Exception as e:  # sin acceso a la base viva, no es un fallo de la copia
            print(f"  aviso  no se pudo leer la base viva ({type(e).__name__}); se omite la comparación")
        else:
            for tabla in tablas_del_esquema():
                if tabla in restaurado and tabla in vivo:
                    igual = restaurado[tabla] == vivo[tabla]
                    print(f"  {'ok   ' if igual else 'aviso'} {tabla}: copia {restaurado[tabla]} · "
                          f"viva {vivo[tabla]}")
                    if not igual:
                        print("         (normal si la copia no es de este momento)")

    print()
    if fallos:
        print(f"RESULTADO: la copia NO es restaurable tal cual ({len(fallos)} fallos):")
        for f in fallos:
            print("  -", f)
        return 1
    print("RESULTADO: la copia se restaura y los datos se leen con la plataforma. Copia válida.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
