"""Sonda 2: paginación real, volumen por ejercicio y política de 429.

Va despacio a propósito (el ERP limita el ritmo) y guarda cada respuesta en disco
para no volver a pedirla. No imprime credenciales.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import cargar_config  # noqa: E402

RAW = Path(__file__).resolve().parents[2] / "fixtures" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
cfg = cargar_config()
BASE = cfg.apicon_base.rstrip("/")
EMPRESA = sys.argv[1] if len(sys.argv) > 1 else cfg.apicon_empresa_defecto
YEAR = sys.argv[2] if len(sys.argv) > 2 else "2025"
PAUSA = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0

cliente = httpx.Client(timeout=180.0)
llamadas: list[dict] = []


def pedir(endpoint: str, params: dict | None = None, cab: dict | None = None, etiqueta: str = "") -> httpx.Response:
    if llamadas:
        time.sleep(PAUSA)
    t0 = time.perf_counter()
    r = cliente.get(f"{BASE}{endpoint}", params=params, headers=cab or {})
    dt = time.perf_counter() - t0
    reg = {
        "etiqueta": etiqueta,
        "params": params,
        "status": r.status_code,
        "segundos": round(dt, 2),
        "mb": round(len(r.content) / 1e6, 3),
        "retry_after": r.headers.get("Retry-After"),
        "x_ratelimit": {k: v for k, v in r.headers.items() if "rate" in k.lower() or "limit" in k.lower()},
    }
    llamadas.append(reg)
    print(f"[{r.status_code}] {etiqueta} {params} -> {dt:.2f}s {reg['mb']}MB"
          + (f" Retry-After={reg['retry_after']}" if reg["retry_after"] else "")
          + (f" {reg['x_ratelimit']}" if reg["x_ratelimit"] else ""))
    if r.status_code == 429:
        print("   cuerpo 429:", r.text[:200])
    return r


def sobresalientes(r: httpx.Response) -> str:
    try:
        j = r.json()
    except Exception:
        return "(no json)"
    return (f"ResultadosTotales={j.get('ResultadosTotales')} PaginaActual={j.get('PaginaActual')} "
            f"ElementosEnPagina={j.get('ElementosEnPagina')} ElementosPorPagina={j.get('ElementosPorPagina')} "
            f"n_Datos={len(j.get('Datos') or [])}")


def main() -> None:
    tok = cliente.post(
        f"{BASE}/token",
        data={
            "grant_type": "password",
            "username": cfg.apicon_username,
            "password": cfg.apicon_password,
            "client_id": cfg.apicon_client_id,
            "client_secret": cfg.apicon_client_secret,
            "cod_empresa": EMPRESA,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    access = tok.json().get("access_token")
    cab = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
    print(f"token ok ({tok.status_code})\n")

    # A) consulta de los workflows, pero leyendo la envoltura de paginación
    r = pedir("/api/apuntes/", {"$filter": f"Ejercicio eq '{YEAR}'", "$top": "5000"}, cab, "A $top=5000")
    print("   ", sobresalientes(r))
    if r.status_code == 200:
        (RAW / f"A_top5000_{EMPRESA}_{YEAR}.json").write_bytes(r.content)

    # B) ¿el filtro de Fecha admite entero YYYYMMDD?
    for filtro in (f"Fecha ge 20250101", f"Fecha ge '20250101'", f"Fecha eq 20250115"):
        r = pedir("/api/apuntes/", {"$filter": filtro, "$top": "5"}, cab, f"B filtro {filtro}")
        if r.status_code == 200:
            print("   ", sobresalientes(r))

    # C) ¿cómo se pide la página siguiente?
    pruebas = [
        ("C1 $skip=200", {"$filter": f"Ejercicio eq '{YEAR}'", "$top": "200", "$skip": "200"}),
        ("C2 Pagina=2", {"$filter": f"Ejercicio eq '{YEAR}'", "Pagina": "2"}),
        ("C3 paginaActual=2", {"$filter": f"Ejercicio eq '{YEAR}'", "paginaActual": "2"}),
        ("C4 ElementosPorPagina=1000", {"$filter": f"Ejercicio eq '{YEAR}'", "ElementosPorPagina": "1000"}),
        ("C5 $top=0", {"$filter": f"Ejercicio eq '{YEAR}'", "$top": "0"}),
    ]
    for etiqueta, params in pruebas:
        r = pedir("/api/apuntes/", params, cab, etiqueta)
        if r.status_code == 200:
            print("   ", sobresalientes(r))

    print("\n--- resumen de llamadas ---")
    for c in llamadas:
        print(f"  {c['status']} {c['etiqueta']:<28} {c['segundos']:>6.2f}s {c['mb']:>6.3f}MB")
    print("\nfixtures guardados en:", RAW)


if __name__ == "__main__":
    main()
