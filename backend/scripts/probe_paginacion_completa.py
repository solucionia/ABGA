"""Sonda 3: Swagger, filtros compuestos y paginación completa con verificación de cobertura.

Objetivo: saber si podemos traernos los 1.531 asientos íntegros (y si hay endpoints
agregados que eviten traerse el detalle).
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
EMPRESA = sys.argv[1] if len(sys.argv) > 1 else "6091"
YEAR = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
PAUSA = 3.0

cli = httpx.Client(timeout=180.0, follow_redirects=True)


def pausa() -> None:
    time.sleep(PAUSA)


def get(ruta: str, params=None, cab=None, nota="") -> httpx.Response:
    pausa()
    t0 = time.perf_counter()
    r = cli.get(f"{BASE}{ruta}", params=params, headers=cab or {})
    dt = time.perf_counter() - t0
    extra = ""
    if "json" in r.headers.get("content-type", ""):
        try:
            j = r.json()
            if isinstance(j, dict) and "Datos" in j:
                extra = (f" | Totales={j.get('ResultadosTotales')} Pag={j.get('PaginaActual')} "
                         f"EnPag={j.get('ElementosEnPagina')} PorPag={j.get('ElementosPorPagina')}")
        except Exception:
            pass
    print(f"[{r.status_code}] {nota or ruta} {params or ''} -> {dt:.2f}s {len(r.content)/1e6:.2f}MB{extra}")
    return r


def main() -> None:
    tok = cli.post(
        f"{BASE}/token",
        data={
            "grant_type": "password", "username": cfg.apicon_username, "password": cfg.apicon_password,
            "client_id": cfg.apicon_client_id, "client_secret": cfg.apicon_client_secret,
            "cod_empresa": EMPRESA,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    cab = {"Authorization": f"Bearer {tok.json()['access_token']}", "Accept": "application/json"}
    print("token ok\n")

    # 1) ¿Hay documentación de la API?
    print("=== 1. Swagger / OpenAPI ===")
    for ruta in ("/swagger/v1/swagger.json", "/swagger/index.html", "/openapi.json",
                 "/api/swagger/v1/swagger.json", "/api-docs", "/help"):
        r = get(ruta, cab=cab, nota=f"swagger {ruta}")
        if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
            try:
                spec = r.json()
                rutas = list((spec.get("paths") or {}).keys())
                print(f"   !! SPEC ENCONTRADA con {len(rutas)} rutas")
                (RAW / "swagger.json").write_bytes(r.content)
                for x in rutas[:60]:
                    print("      ", x)
                break
            except Exception:
                pass

    # 2) filtros compuestos y por mes
    print("\n=== 2. filtros ===")
    pruebas_filtro = [
        ("and + rango mes", f"Ejercicio eq '{YEAR}' and Fecha ge {YEAR}0101 and Fecha le {YEAR}0131"),
        ("solo rango mes", f"Fecha ge {YEAR}0101 and Fecha le {YEAR}0131"),
        ("gte/le", f"Fecha gte {YEAR}0101"),
        ("ge entero sin comillas mes 2", f"Ejercicio eq '{YEAR}' and Fecha ge {YEAR}0201 and Fecha le {YEAR}0228"),
    ]
    for etiqueta, filtro in pruebas_filtro:
        r = get("/api/apuntes/", {"$filter": filtro, "$top": "200"}, cab, etiqueta)
        if r.status_code == 400:
            print("    400 ->", r.text[:160])

    # 3) paginación completa con $skip y verificación de cobertura
    print("\n=== 3. paginación completa ===")
    vistos: dict[str, dict] = {}
    primera = get("/api/apuntes/", {"$filter": f"Ejercicio eq '{YEAR}'", "$top": "200"}, cab, "pagina 0")
    j = primera.json()
    total = j.get("ResultadosTotales")
    print(f"   ResultadosTotales={total}")
    (RAW / f"pag_skip0_{EMPRESA}_{YEAR}.json").write_bytes(primera.content)

    def clave(a: dict) -> str:
        return f"{a.get('Ejercicio')}-{a.get('Serie')}-{a.get('Documento')}-{a.get('Fecha')}"

    for a in j.get("Datos") or []:
        vistos[clave(a)] = a

    n_pag = 0
    for skip in range(200, min(total or 0, 2000), 200):
        r = get("/api/apuntes/", {"$filter": f"Ejercicio eq '{YEAR}'", "$top": "200", "$skip": str(skip)}, cab, f"skip={skip}")
        if r.status_code != 200:
            break
        jj = r.json()
        datos = jj.get("Datos") or []
        nuevos = sum(1 for a in datos if clave(a) not in vistos)
        for a in datos:
            vistos[clave(a)] = a
        print(f"    skip={skip}: devueltos={len(datos)} nuevos={nuevos} acumulado={len(vistos)}")
        (RAW / f"pag_skip{skip}_{EMPRESA}_{YEAR}.json").write_bytes(r.content)
        n_pag += 1
        if not datos or nuevos == 0:
            print("    -> la paginación se ha agotado o no avanza")
            break

    print(f"\n   COBERTURA: {len(vistos)} asientos únicos de {total} declarados")

    # 4) ¿los apuntes traen ya el saldo de la cuenta? ¿existen endpoints agregados?
    print("\n=== 4. endpoints agregados ===")
    for ruta in ("/api/apuntes", "/api/cuentas", "/api/mayores", "/api/balance",
                 "/api/saldos", "/api/balanceSituacion", "/api/empresas", "/api/ejercicios"):
        r = get(ruta, {"$top": "1"}, cab, f"probe {ruta}")

    # 5) fixture completo consolidado
    print("\n=== 5. fixture ===")
    fixture = {
        "empresa": EMPRESA, "year": YEAR,
        "resultados_totales_declarados": total,
        "asientos": list(vistos.values()),
    }
    ruta_fx = Path(__file__).resolve().parents[2] / "fixtures" / f"apuntes_{EMPRESA}_{YEAR}.json"
    ruta_fx.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    lineas = sum(len(a.get("Detalles") or []) for a in fixture["asientos"])
    print(f"   {ruta_fx.name}: {len(fixture['asientos'])} asientos, {lineas} líneas, "
          f"{ruta_fx.stat().st_size/1e6:.2f} MB")


if __name__ == "__main__":
    main()
