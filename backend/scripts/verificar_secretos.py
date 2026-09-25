"""Comprueba que NO haya credenciales del ERP ni secretos en los ficheros que git tiene dentro.

Lee los valores reales de `.env` y busca cada uno en el contenido **seguido por git** (no en el
directorio: un fichero ignorado no viaja a GitHub). Sólo imprime rutas y cuentas, nunca el valor,
para que el propio informe no sea la fuga que intenta evitar.

Uso:  ./.venv/bin/python backend/scripts/verificar_secretos.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
ENV = RAIZ / ".env"

# Valores que nunca deben estar en un fichero versionado.
CLAVES = ("APICON_PASSWORD", "APICON_CLIENT_SECRET", "SECRET_KEY", "ADMIN_BOOTSTRAP_PASSWORD",
          "APICON_USER", "APICON_CLIENT_ID")


def valores_env() -> dict[str, str]:
    salida: dict[str, str] = {}
    if not ENV.exists():
        return salida
    for linea in ENV.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        clave, valor = clave.strip(), valor.strip().strip("'\"")
        if clave in CLAVES and len(valor) >= 6:
            salida[clave] = valor
    return salida


def ficheros_versionados() -> list[str]:
    r = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True)
    return [l for l in r.stdout.splitlines() if l.strip()]


def main() -> int:
    valores = valores_env()
    print(f"valores leídos de .env: {len(valores)} ({', '.join(sorted(valores)) or 'ninguno'})")
    ficheros = ficheros_versionados()
    print(f"ficheros seguidos por git: {len(ficheros)}")

    fugas: list[tuple[str, str, int]] = []
    for rel in ficheros:
        ruta = RAIZ / rel
        try:
            texto = ruta.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for clave, valor in valores.items():
            n = texto.count(valor)
            if n:
                fugas.append((rel, clave, n))

    print()
    if fugas:
        print("  \033[31mFUGA: hay valores de .env dentro del repositorio\033[0m")
        for rel, clave, n in fugas:
            print(f"    - {rel}: {clave} aparece {n} vez/veces")
        return 1

    print("  \033[32m✓\033[0m ningún valor de .env aparece en los ficheros versionados")

    # Y lo que sí debe estar ignorado, que se comprueba en vez de suponerse.
    print()
    for patron in (".env", "data/", "fixtures/", "salidas/", "mock/", ".venv/"):
        r = subprocess.run(["git", "check-ignore", "-q", patron], cwd=RAIZ)
        print(f"    {'✓' if r.returncode == 0 else '✗ NO'} ignorado: {patron}")
        if r.returncode != 0:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
