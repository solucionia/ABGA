"""Genera la carpeta `mock/` con respuestas reales de la API, para que Claude Design
previsualice el portal con datos de verdad en lugar de números falsos.

Uso (con el servidor levantado):
    ./.venv/bin/python backend/scripts/generar_mock.py http://127.0.0.1:8011

Los datos son de la empresa 6091 (MB Dommo, S.L.) del ejercicio 2025 — son datos reales de
cliente, así que `mock/` está en .gitignore.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import os
def clave_admin() -> str:
    """Contraseña del usuario interno de ABGA: del entorno o de `.env`, nunca escrita aquí."""
    v = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "")
    if v:
        return v
    for linea in (Path(__file__).resolve().parents[2] / ".env").read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith("ADMIN_BOOTSTRAP_PASSWORD="):
            return linea.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("Falta ADMIN_BOOTSTRAP_PASSWORD: no está ni en el entorno ni en .env")

RAIZ = Path(__file__).resolve().parents[2]
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011").rstrip("/")
SALIDA = RAIZ / "mock"

CLIENTE = ("cliente@mbdommo.com", "demo2025")
INTERNO = ("admin@abgaconsultores.com", clave_admin())


def cli() -> httpx.Client:
    return httpx.Client(timeout=600.0)


def login(c: httpx.Client, email: str, password: str) -> dict:
    r = c.post(f"{BASE}/api/login", json={"email": email, "password": password})
    return r.json()


def guardar(nombre: str, objeto: dict) -> None:
    (SALIDA / nombre).write_text(json.dumps(objeto, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {nombre}  ({len(json.dumps(objeto))} bytes)")


def main() -> None:
    SALIDA.mkdir(exist_ok=True)
    with cli() as c:
        print("== autenticación ==")
        tok_cliente = login(c, *CLIENTE)["token"]
        hc = {"Authorization": f"Bearer {tok_cliente}"}
        tok_int = login(c, *INTERNO)["token"]
        hi = {"Authorization": f"Bearer {tok_int}"}

        print("== endpoints del cliente ==")
        guardar("yo.json", c.get(f"{BASE}/api/yo", headers=hc).json())
        guardar("empresas.json", c.get(f"{BASE}/api/empresas", headers=hc).json())
        guardar("modulos.json", c.get(f"{BASE}/api/modulos", headers=hc).json())
        guardar("cache.json", c.get(f"{BASE}/api/cache", params={"cod_empresa": "6091"}, headers=hc).json())
        guardar("dashboard.json",
                c.get(f"{BASE}/api/dashboard", params={"cod_empresa": "6091", "year": 2025}, headers=hc).json())

        # un informe: guardamos status/meta/avisos y un HTML recortado (el diseño no maqueta el informe)
        r = c.post(f"{BASE}/api/informe", headers=hc,
                   json={"modulo": "pyg", "cod_empresa": "6091", "year": 2025}).json()
        if r.get("status") == "ok":
            r["html"] = r["html"][:1200] + "\n… (informe completo) …"
        guardar("informe.json", r)

        print("== trabajos (muestra de estado) ==")
        ref = c.post(f"{BASE}/api/refrescar", headers=hc, json={"cod_empresa": "6091", "year": 2025}).json()
        guardar("refrescar.json", ref)
        tid = ref.get("trabajo", {}).get("id")
        if tid:
            import time
            time.sleep(2)
            guardar("trabajo.json", c.get(f"{BASE}/api/trabajos/{tid}", headers=hc).json())

        print("== panel interno (rol ABGA) ==")
        resumen = c.get(f"{BASE}/api/interno/resumen", headers=hi).json()
        # recortamos las listas largas para que el mock sea manejable
        resumen["ejecuciones"] = resumen.get("ejecuciones", [])[:10]
        guardar("interno-resumen.json", resumen)

    print(f"\nlisto: {len(list(SALIDA.glob('*.json')))} ficheros en {SALIDA}/")
    print("AVISO: contienen datos reales del cliente 6091; no compartir y están en .gitignore.")


if __name__ == "__main__":
    main()
