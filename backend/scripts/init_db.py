"""Crea las empresas y los usuarios iniciales.

Uso:  ./.venv/bin/python backend/scripts/init_db.py

- Empresas: 6091 (MB Dommo, S.L.) y 1092 (ABGA Consultores).
- Usuario interno de ABGA: `admin@abgaconsultores.com`, con la contraseña aleatoria que está
  en `.env` (ADMIN_BOOTSTRAP_PASSWORD).
- Usuario de cliente de demostración: `cliente@mbdommo.com`, con la contraseña del portal
  antiguo (`demo2025`) para no romper las pruebas que ya se hacían; **hay que cambiarla antes
  de abrir el portal a clientes reales**.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import auth, cache, db  # noqa: E402
from app.config import cargar_config  # noqa: E402

EMPRESAS = [
    ("6091", "MB Dommo, S.L.", 2022),
    ("1092", "ABGA Consultores", 2022),
]

USUARIOS = [
    ("admin@abgaconsultores.com", "ABGA · administración", "interno", ["6091", "1092"], None),
    ("cliente@mbdommo.com", "MB Dommo, S.L.", "cliente", ["6091"], "demo2025"),
]


def main() -> None:
    cfg = cargar_config()
    cache.conectar()  # crea el esquema

    for cod, nombre, inicio in EMPRESAS:
        db.crear_empresa(cod, nombre, inicio, notas="Creada por init_db")
        print(f"empresa  {cod} · {nombre}")

    env = {}
    for linea in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in linea and not linea.startswith("#"):
            k, v = linea.split("=", 1)
            env[k.strip()] = v.strip()
    password_admin = env.get("ADMIN_BOOTSTRAP_PASSWORD") or auth.password_generada()

    for email, nombre, rol, empresas, fija in USUARIOS:
        password = fija or password_admin
        db.crear_usuario(email, nombre, auth.hash_password(password), rol, empresas=empresas)
        print(f"usuario  {email:<30} rol={rol:<8} empresas={','.join(empresas)} "
              f"contraseña={'la del portal antiguo' if fija else 'ADMIN_BOOTSTRAP_PASSWORD del .env'}")

    print("\nlisto. Usuarios en la base:")
    for u in db.listar_usuarios():
        print(f"  {u['email']:<30} {u['rol']:<8} {u['empresas']}")
    print(f"\ncontraseña del usuario interno (está en .env): {password_admin}")
    print("cámbiala después del primer acceso si el portal va a ver clientes reales.")


if __name__ == "__main__":
    main()
