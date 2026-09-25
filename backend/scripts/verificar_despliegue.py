"""Prueba de despliegue: la app tal y como correrá en Coolify.

Recorre lo que de verdad se rompe al desplegar y que en local no se ve, porque en local siempre está
el `.env` y casi siempre SQLite:

  1. **Sin `.env`**: durante la prueba se aparta, para que todo tenga que entrar por variables de
     entorno como en el contenedor. Al terminar se restaura y se comprueba que quedó igual.
  2. **PostgreSQL de verdad**: se levanta el embebido de `pgserver` (misma ruta que producción).
  3. **Arranque de contenedor**: se lanza `backend/scripts/arranque.py`, que crea el esquema y el
     usuario interno desde el entorno.
  4. **Sin datos de prueba**: en una base nueva no puede haber ni clientes demo ni empresas de
     ejemplo; el panel tiene que responder con la lista vacía, no con invenciones.
  5. **Reinicio seguro**: al volver a arrancar no duplica ni pisa el usuario interno.
  6. **El panel y la API**: exigen sesión, y con ella se entra.

    ./.venv/bin/python backend/scripts/verificar_despliegue.py
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

import httpx  # noqa: E402

PUERTO = "8021"
BASE = f"http://127.0.0.1:{PUERTO}"
CLAVE_INTERNO = "clave-de-prueba-despliegue-2026"
FALLOS: list[str] = []


def check(cond: bool, texto: str, detalle: str = "") -> None:
    print(("  OK   " if cond else "  FALLO") + f" {texto}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLOS.append(texto)


def huella(ruta: pathlib.Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else ""


def entorno(database_url: str) -> dict[str, str]:
    """El entorno del contenedor: nada de `.env`, todo por variables (y sin tocar el ERP)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("APICON_")}
    env.update({
        "DATABASE_URL": database_url,
        "ADMIN_BOOTSTRAP_PASSWORD": CLAVE_INTERNO,
        "SECRET_KEY": "clave-de-firma-solo-para-esta-prueba",
        "APICON_SOLO_CACHE": "1",          # la prueba NUNCA llama al ERP de ABGA
        "PORT": PUERTO,
        "PATH": os.environ.get("PATH", ""),
        # Credenciales de mentira: la app exige que existan, y con el puerto 9 (descartar) cualquier
        # intento de llegar al ERP falla al instante en vez de salir a internet.
        "APICON_BASE": "http://127.0.0.1:9/apicon-de-prueba",
        "APICON_USERNAME": "prueba",
        "APICON_PASSWORD": "prueba",
        "APICON_CLIENT_ID": "prueba",
        "APICON_CLIENT_SECRET": "prueba",
        "APICON_EMPRESA_DEFECTO": "6091",
    })
    return env


def arrancar(env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, str(RAIZ / "backend/scripts/arranque.py")],
                            cwd=RAIZ, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)


def esperar(proc: subprocess.Popen, segundos: int = 45) -> bool:
    for _ in range(segundos * 4):
        if proc.poll() is not None:
            return False
        try:
            if httpx.get(BASE + "/", timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def salida(proc: subprocess.Popen) -> str:
    try:
        proc.terminate()
        return proc.communicate(timeout=15)[0] or ""
    except Exception:
        proc.kill()
        return ""


def main() -> int:
    env_orig = RAIZ / ".env"
    apartado = RAIZ / ".env.apartado-para-la-prueba"
    h = huella(env_orig)
    proc: subprocess.Popen | None = None
    datos_pg: str | None = None
    logs: list[str] = []
    try:
        print("1) se aparta el .env (en el contenedor no existe)")
        if not env_orig.exists():
            print("  (no había .env: nada que apartar)")
        else:
            env_orig.rename(apartado)
        check(not env_orig.exists(), "el .env no está mientras corre la prueba")

        print("\n2) PostgreSQL real (embebido) en vez de SQLite")
        import pgserver
        datos = tempfile.mkdtemp(prefix="abga-despliegue-pg-")
        datos_pg = datos
        servidor = pgserver.get_server(datos)
        url = servidor.get_uri()
        check(bool(url), "PostgreSQL levantado", url.split("@")[-1])
        env = entorno(url)

        print("\n3) arranque como en el contenedor")
        proc = arrancar(env)
        listo = esperar(proc)
        check(listo, "el servidor arranca y responde")
        if not listo:
            print(salida(proc))
            return 1

        print("\n4) la base se ha creado sola y sin datos de prueba")
        import psycopg
        con = psycopg.connect(url)
        tablas = {f[0] for f in con.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()}
        check({"usuarios", "empresas", "permisos", "apuntes", "tokens", "ejecuciones",
               "calc_cache"} <= tablas, "el esquema se ha creado en PostgreSQL",
              f"{len(tablas)} tablas")
        columnas = {f[0] for f in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='empresas'").fetchall()}
        check("pin_hash" in columnas, "la migración del PIN se aplicó en PostgreSQL")
        n_empresas = con.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
        n_usuarios = con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        check(n_empresas == 0, "ninguna empresa de prueba cargada por el arranque", f"{n_empresas}")
        check(n_usuarios == 1, "solo el usuario interno, ningún cliente demo", f"{n_usuarios}")

        print("\n5) el panel y la API, con sesión")
        anon = httpx.Client(base_url=BASE, timeout=30)
        check(anon.get("/").status_code == 200, "el panel se sirve")
        check(anon.get("/api/yo").status_code == 401, "sin sesión, todo exige credencial")
        r = anon.post("/api/login", json={"email": "admin@abgaconsultores.com", "password": CLAVE_INTERNO})
        check(r.status_code == 200, "se entra con el interno del entorno", f"{r.status_code}")
        check(r.status_code == 200 and r.json()["usuario"]["rol"] == "interno", "y es el rol interno")
        check(anon.get("/api/empresas").status_code == 200, "el listado de empresas responde (vacío)")
        check(anon.get("/api/modulos").status_code == 200, "el catálogo de informes responde")

        print("\n6) al reiniciar no duplica ni pisa el usuario interno")
        primer_texto = salida(proc)
        logs.append(primer_texto)
        check("usuario interno creado" in primer_texto, "el primer arranque lo creó")
        proc = arrancar(env)
        check(esperar(proc), "vuelve a arrancar")
        texto = salida(proc)
        logs.append(texto)
        check("ya existía" in texto, "el segundo arranque no lo recrea")
        con2 = psycopg.connect(url)
        check(con2.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 1,
              "sigue habiendo un solo usuario")
        proc = None

        print("\n7) si falta configuración, el arranque lo dice y no arranca a medias")
        sin_apicon = {k: v for k, v in env.items() if not k.startswith("APICON_")}
        r = subprocess.run([sys.executable, str(RAIZ / "backend/scripts/arranque.py")], cwd=RAIZ,
                           env=sin_apicon, capture_output=True, text=True, timeout=120)
        check(r.returncode != 0, "sale con error en vez de servir 500 en cada petición",
              f"exit={r.returncode}")
        check("ERROR de configuración" in r.stdout, "y el log dice que falta configuración",
              r.stdout.strip().splitlines()[0] if r.stdout.strip() else "sin salida")
    finally:
        if proc is not None:
            salida(proc)
        if apartado.exists():
            apartado.rename(env_orig)
        check(huella(env_orig) == h, "el .env quedó restaurado igual que estaba")
        if datos_pg:
            shutil.rmtree(datos_pg, ignore_errors=True)

    print()
    if FALLOS:
        print(f"  {len(FALLOS)} comprobaciones NO cumplidas:")
        for f in FALLOS:
            print(f"    - {f}")
        if logs:
            print("\n  --- últimas líneas del servidor (para el diagnóstico) ---")
            for linea in logs[0].splitlines()[-25:]:
                print(f"  | {linea}")
        return 1
    print("  Todo listo para desplegar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
