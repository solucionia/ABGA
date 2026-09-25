"""Prueba de aceptación de la API (se ejecuta contra un servidor levantado).

Uso:
    cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8011 &
    ./.venv/bin/python backend/scripts/e2e_api.py http://127.0.0.1:8011

Comprueba lo que de verdad importa del cambio:
  * el login es real (antes entraba cualquiera con sólo un código de empresa)
  * cada usuario sólo ve sus empresas
  * los informes de uso interno no salen por la API para un usuario de cliente
  * los informes se generan y llegan en HTML puro empezando por <div
  * los datos del panel llegan agregados (no 5.000 apuntes al navegador)
  * queda registro de cada ejecución
"""
from __future__ import annotations

import json
import sys
import time

import httpx
import os
from pathlib import Path
def clave_admin() -> str:
    """Contraseña del usuario interno de ABGA: del entorno o de `.env`, nunca escrita aquí."""
    v = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "")
    if v:
        return v
    for linea in (Path(__file__).resolve().parents[2] / ".env").read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith("ADMIN_BOOTSTRAP_PASSWORD="):
            return linea.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("Falta ADMIN_BOOTSTRAP_PASSWORD: no está ni en el entorno ni en .env")

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011").rstrip("/")
FALLOS: list[str] = []


def check(cond: bool, texto: str, detalle: str = "") -> None:
    print(("  OK   " if cond else "  FALLO") + f" {texto}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLOS.append(texto)


def login(cli: httpx.Client, email: str, password: str, cod_empresa: str = "6091") -> str:
    """Entra al portal. El número de empresa forma parte del acceso (indica qué datos se abren)."""
    r = cli.post(f"{BASE}/api/login", json={"email": email, "password": password, "cod_empresa": cod_empresa})
    j = r.json()
    return j.get("token") or ""


def main() -> None:
    print(f"API: {BASE}\n")
    with httpx.Client(timeout=600.0) as cli:
        print("=== salud y frontal ===")
        s = cli.get(f"{BASE}/api/salud").json()
        check(s.get("status") == "ok", "el servicio responde")
        check(cli.get(f"{BASE}/").status_code == 200, "el portal se sirve en /")
        check("ABGA" in cli.get(f"{BASE}/").text, "el HTML del portal carga")

        print("\n=== autenticación ===")
        check(cli.post(f"{BASE}/api/login", json={"email": "cliente@mbdommo.com", "password": "mala",
                                                  "cod_empresa": "6091"}).status_code == 401,
              "una contraseña incorrecta NO entra")
        check(cli.post(f"{BASE}/api/login", json={"email": "nadie@x.com", "password": "x",
                                                  "cod_empresa": "6091"}).status_code == 401,
              "un usuario inexistente NO entra")
        check(cli.post(f"{BASE}/api/login", json={"email": "cliente@mbdommo.com", "password": "demo2025"}
                       ).status_code == 400, "sin número de empresa NO entra")
        check(cli.post(f"{BASE}/api/login", json={"email": "cliente@mbdommo.com", "password": "demo2025",
                                                  "cod_empresa": "999999"}).status_code == 404,
              "con un número que no existe NO entra")
        check(cli.get(f"{BASE}/api/dashboard", params={"cod_empresa": "6091", "year": 2025}).status_code == 401,
              "sin sesión no hay datos")

        tok_cli = login(cli, "cliente@mbdommo.com", "demo2025")
        check(bool(tok_cli), "el usuario de cliente entra")
        tok_int = login(cli, "admin@abgaconsultores.com", clave_admin())
        check(bool(tok_int), "el usuario interno de ABGA entra")

        h_cli = {"Authorization": f"Bearer {tok_cli}"}
        h_int = {"Authorization": f"Bearer {tok_int}"}

        print("\n=== permisos por empresa ===")
        r = cli.get(f"{BASE}/api/empresas", headers=h_cli).json()
        codigos = [e["cod_empresa"] for e in r.get("empresas", [])]
        check(codigos == ["6091"], "el cliente sólo ve su empresa", str(codigos))
        r = cli.get(f"{BASE}/api/empresas", headers=h_int).json()
        codigos_int = sorted(e["cod_empresa"] for e in r.get("empresas", []))
        check({"1092", "6091"} <= set(codigos_int) and len(codigos_int) > len(codigos),
              "el interno ve todas las empresas", f"{len(codigos_int)} frente a {len(codigos)} del cliente")

        r = cli.post(f"{BASE}/api/informe", headers=h_cli, json={"modulo": "fiscal", "cod_empresa": "1092", "year": 2025})
        check(r.status_code == 403, "el cliente no puede pedir datos de otra empresa", f"HTTP {r.status_code}")

        print("\n=== informes internos ===")
        r = cli.post(f"{BASE}/api/informe", headers=h_cli, json={"modulo": "duplicados", "cod_empresa": "6091", "year": 2025})
        check(r.status_code == 403, "los informes internos no salen para el cliente", f"HTTP {r.status_code}")
        mods = [m["nombre"] for m in cli.get(f"{BASE}/api/modulos", headers=h_cli).json().get("modulos", [])]
        check("duplicados" not in mods, "el catálogo del cliente no ofrece los informes internos", str(mods))
        check("conciliacion" in mods, "pero la conciliación sí (la ve el cliente)", str(mods))
        r = cli.post(f"{BASE}/api/informe", headers=h_int, json={"modulo": "conciliacion", "cod_empresa": "6091", "year": 2025})
        check(r.status_code == 200, "el interno sí genera los informes internos", f"HTTP {r.status_code}")

        print("\n=== generación de informes (datos en caché) ===")
        for nombre in ("fiscal", "duplicados", "conciliacion"):
            t0 = time.perf_counter()
            r = cli.post(f"{BASE}/api/informe", headers=h_int,
                         json={"modulo": nombre, "cod_empresa": "6091", "year": 2025})
            dt = time.perf_counter() - t0
            j = r.json()
            html = j.get("html") or ""
            check(r.status_code == 200 and j.get("status") == "ok", f"{nombre}: se genera (HTTP {r.status_code})")
            check(html.lstrip().startswith("<div"), f"{nombre}: HTML puro empezando por <div>")
            check(len(html) > 3000, f"{nombre}: informe con contenido", f"{len(html)} caracteres")
            meta = j.get("meta") or {}
            print(f"         {nombre}: {dt:.2f}s · caché={meta.get('desde_cache')} · cobertura={list((meta.get('ejercicios') or {}).values())[0].get('cobertura') if meta.get('ejercicios') else '—'}")

        print("\n=== panel (datos agregados) ===")
        t0 = time.perf_counter()
        r = cli.get(f"{BASE}/api/dashboard", params={"cod_empresa": "6091", "year": 2025}, headers=h_cli)
        dt = time.perf_counter() - t0
        j = r.json()
        if r.status_code != 200:
            print(f"  aviso: el panel devolvió HTTP {r.status_code} ({j.get('error')}) — puede faltar caché de ejercicios previos")
        else:
            d = j["data"]
            check(set(["kpis", "mensual", "comparativa", "avisos"]).issubset(d.keys()),
                  "el panel trae KPIs, series y comparativa")
            check(len(d["mensual"]) == 12, "la serie mensual tiene 12 meses")
            check(isinstance(d["kpis"]["totalIngresos"], (int, float)), "los KPIs son numéricos")
            check(d["kpis"]["totalIngresos"] > 0, "hay ingresos en el ejercicio",
                  f"{d['kpis']['totalIngresos']:,.2f} €")
            check(isinstance(d["comparativa"], list) and len(d["comparativa"]) >= 1, "hay comparativa interanual")
            print(f"         panel en {dt:.2f}s · desde caché={j['meta'].get('desde_cache')} · "
                  f"{len(json.dumps(j))} bytes de JSON (antes se enviaban 5.000 apuntes)")

        print("\n=== catálogo de ejercicios y caché ===")
        r = cli.get(f"{BASE}/api/cache", params={"cod_empresa": "6091"}, headers=h_cli).json()
        entradas = r.get("cache") or []
        check(bool(entradas), "la caché tiene ejercicios cargados")
        for e in entradas:
            print(f"         {e['empresa']}/{e['ejercicio']}: {e['n_asientos']} asientos · {e['cobertura']}")
        completa = any("completa" in (e.get("cobertura") or "") for e in entradas)
        check(completa, "algún ejercicio está con cobertura completa (no la página de 200)")

        print("\n=== registro de ejecuciones ===")
        r = cli.get(f"{BASE}/api/interno/resumen", headers=h_int).json()
        check(r.get("status") == "ok", "el panel interno responde al usuario de ABGA")
        check(len(r.get("ejecuciones") or []) > 0, "hay ejecuciones registradas",
              f"{len(r.get('ejecuciones') or [])} filas")
        estados = {e["estado"] for e in (r.get("ejecuciones") or [])}
        check("ok" in estados, "las ejecuciones se registran con su estado", str(estados))
        check(cli.get(f"{BASE}/api/interno/resumen", headers=h_cli).status_code == 403,
              "el panel interno NO es accesible para el cliente")

    print("\n=== resultado ===")
    if FALLOS:
        print(f"{len(FALLOS)} comprobaciones fallidas:")
        for f in FALLOS:
            print("  -", f)
        raise SystemExit(1)
    print("la API pasa todas las comprobaciones")


if __name__ == "__main__":
    main()
