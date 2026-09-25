"""Arranque del contenedor de la plataforma ABGA.

Qué hace, en orden y por qué:

1. **Comprueba la base de datos.** Si `DATABASE_URL` está mal o la base no responde, el contenedor
   falla aquí, al arrancar, y no en la primera petición de un cliente. Además crea el esquema y
   aplica las migraciones pendientes (es idempotente).
2. **Crea el usuario interno de ABGA si no existe.** La contraseña llega por variable de entorno;
   sin ella no se crea nada. No crea ningún cliente ni dato de prueba: en producción los clientes
   entran con su código y su PIN, o los da de alta ABGA desde el panel.
3. **Lanza uvicorn con `exec`**, para que sea el proceso principal y reciba las señales de Docker
   (parada limpia al desplegar una versión nueva).

Todo entra por variables de entorno porque la imagen **no lleva `.env`** (no está en git y no debe
estarlo):

    DATABASE_URL                postgres://...   (obligatoria en producción)
    ADMIN_BOOTSTRAP_PASSWORD    contraseña del usuario interno (si falta, no se crea)
    ADMIN_EMAIL                 por defecto admin@abgaconsultores.com
    ADMIN_FORZAR_PASSWORD=1     reescribe la contraseña del interno aunque ya exista
    APICON_*                    credenciales del ERP
    SECRET_KEY                  firma de las cookies de sesión
    PORT                        por defecto 8000
"""
from __future__ import annotations

import os
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import auth, bd, cache, db  # noqa: E402
from app.config import cargar_config  # noqa: E402


def comprobar_config() -> None:
    """Falla al arrancar si falta configuración, en vez de dar 500 en cada petición.

    Sin las credenciales del ERP, `cargar_config()` lanza una excepción en cuanto alguien entra (la
    primera llamada que la necesita): el contenedor arrancaría, el panel se vería y todo lo demás
    devolvería 500 sin decir por qué. Mejor que el despliegue falle aquí y el log diga qué variable
    falta.
    """
    try:
        cargar_config()
    except RuntimeError as e:
        print(f"[arranque] ERROR de configuración: {e}", flush=True)
        print("[arranque] revisa las variables de entorno del despliegue; no se arranca a medias.",
              flush=True)
        raise SystemExit(1) from None


def comprobar_base() -> None:
    """Falla pronto y claro si la base no está: es lo primero que se rompe al desplegar."""
    con = cache.conectar()
    con.execute("SELECT 1").fetchone()
    motor = "PostgreSQL" if bd.es_postgres() else f"SQLite ({bd.url() or 'por defecto'})"
    print(f"[arranque] base de datos lista: {motor}", flush=True)
    print(f"[arranque] empresas: {len(db.listar_empresas())} · usuarios: {len(db.listar_usuarios())}",
          flush=True)


def preparar_interno() -> None:
    email = os.environ.get("ADMIN_EMAIL", "admin@abgaconsultores.com").strip().lower()
    password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "").strip()
    forzar = os.environ.get("ADMIN_FORZAR_PASSWORD", "").strip() == "1"
    if not password:
        print("[arranque] sin ADMIN_BOOTSTRAP_PASSWORD: no se toca el usuario interno.", flush=True)
        return
    if db.usuario_bruto(email) is None:
        db.crear_usuario(email, "ABGA · administración", auth.hash_password(password), "interno")
        print(f"[arranque] usuario interno creado: {email}", flush=True)
    elif forzar:
        db.cambiar_password(email, auth.hash_password(password))
        print("[arranque] contraseña del usuario interno actualizada (ADMIN_FORZAR_PASSWORD=1)",
              flush=True)
    else:
        print(f"[arranque] el usuario interno {email} ya existía; su contraseña NO se toca "
              f"(ADMIN_FORZAR_PASSWORD=1 para cambiarla).", flush=True)


def main() -> None:
    comprobar_config()
    comprobar_base()
    preparar_interno()
    puerto = os.environ.get("PORT", "8000")
    print(f"[arranque] uvicorn escuchando en 0.0.0.0:{puerto}", flush=True)
    # Se lanza con el propio intérprete (no con el `uvicorn` del PATH): así funciona aunque el
    # contenedor no tenga el PATH del entorno virtual.
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "app.main:app",
                              "--host", "0.0.0.0", "--port", str(puerto),
                              "--app-dir", str(RAIZ / "backend")])


if __name__ == "__main__":
    main()
