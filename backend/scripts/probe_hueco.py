"""¿De dónde salen los asientos que no alcanza el filtro por rango de fechas?

Para cada ejercicio: compara el total del año con la suma de los totales mes a mes y con el
total del rango 01/01–31/12, y busca asientos con fecha fuera del ejercicio o sin fecha.
También recorre el listado sin filtro de fecha (por número de página) para ver qué asientos
aparecen ahí y no en el recorrido por rangos.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import cargar_config  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
cfg = cargar_config()
BASE = cfg.apicon_base.rstrip("/")
EMPRESA = sys.argv[1] if len(sys.argv) > 1 else "6091"
YEAR = int(sys.argv[2]) if len(sys.argv) > 2 else 2024
PAUSA = 3.0
cli = httpx.Client(timeout=180.0)
cab: dict[str, str] = {}


def pedir(filtro: str, top: int = 1, skip: int = 1) -> dict:
    time.sleep(PAUSA)
    r = cli.get(f"{BASE}/api/apuntes/", params={"$filter": filtro, "$top": str(top), "$skip": str(skip)},
                headers=cab)
    if r.status_code != 200:
        print(f"   [{r.status_code}] {filtro[:80]} -> {r.text[:120]}")
        return {"Datos": [], "ResultadosTotales": 0}
    return r.json()


def clave(a: dict) -> str:
    return (f"{a.get('Ejercicio')}|{a.get('Serie')}|{a.get('Documento')}|"
            f"{a.get('Fecha')}|{a.get('Debe')}|{a.get('Haber')}")


def main() -> None:
    tok = cli.post(f"{BASE}/token", data={
        "grant_type": "password", "username": cfg.apicon_username, "password": cfg.apicon_password,
        "client_id": cfg.apicon_client_id, "client_secret": cfg.apicon_client_secret,
        "cod_empresa": EMPRESA},
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    cab.update({"Authorization": f"Bearer {tok.json()['access_token']}", "Accept": "application/json"})
    print(f"empresa {EMPRESA} · ejercicio {YEAR}\n")

    print("=== 1. totales ===")
    año = pedir(f"Ejercicio eq '{YEAR}'")["ResultadosTotales"]
    rango = pedir(f"Ejercicio eq '{YEAR}' and Fecha ge {YEAR}0101 and Fecha le {YEAR}1231")["ResultadosTotales"]
    print(f"   total del año (sin filtro de fecha) = {año}")
    print(f"   total del rango 01/01-31/12         = {rango}")

    print("\n=== 2. totales mes a mes ===")
    suma_meses = 0
    meses = [(f"{YEAR}{m:02d}01", f"{YEAR}{m:02d}{d}") for m, d in
             [(1, 31), (2, 29), (3, 31), (4, 30), (5, 31), (6, 30), (7, 31), (8, 31), (9, 30),
              (10, 31), (11, 30), (12, 31)]]
    for ini, fin in meses:
        n = pedir(f"Ejercicio eq '{YEAR}' and Fecha ge {ini} and Fecha le {fin}")["ResultadosTotales"]
        suma_meses += n
        print(f"   {ini[:6]}: {n}")
    print(f"   suma de los meses = {suma_meses}")

    print("\n=== 3. ¿hay asientos con fecha fuera del ejercicio? ===")
    for etiqueta, filtro in (
            ("fecha anterior al año", f"Ejercicio eq '{YEAR}' and Fecha lt {YEAR}0101"),
            ("fecha posterior al año", f"Ejercicio eq '{YEAR}' and Fecha gt {YEAR}1231"),
            ("fecha cero", f"Ejercicio eq '{YEAR}' and Fecha eq 0"),
            ("fecha nula", f"Ejercicio eq '{YEAR}' and Fecha eq null"),
    ):
        n = pedir(filtro)["ResultadosTotales"]
        print(f"   {etiqueta}: {n}")

    print("\n=== 4. recorrido sin filtro de fecha (por páginas) ===")
    claves_pagina: set[str] = set()
    for pag in range(1, 14):
        j = pedir(f"Ejercicio eq '{YEAR}'", top=200, skip=pag)
        datos = j.get("Datos") or []
        if not datos:
            break
        nuevos = sum(1 for a in datos if clave(a) not in claves_pagina)
        fechas = [int(a.get("Fecha") or 0) for a in datos]
        print(f"   pág {pag}: {len(datos)} asientos, nuevos {nuevos}, "
              f"fechas {min(fechas)}-{max(fechas)}, acumulado {len(claves_pagina) + nuevos}")
        for a in datos:
            claves_pagina.add(clave(a))

    destino = RAIZ / "fixtures" / f"diagnostico_{EMPRESA}_{YEAR}.json"
    destino.write_text(json.dumps({"empresa": EMPRESA, "year": YEAR, "total_anio": año,
                                   "total_rango": rango, "suma_meses": suma_meses,
                                   "asientos_en_recorrido_sin_filtro": len(claves_pagina),
                                   "claves": sorted(claves_pagina)}, ensure_ascii=False),
                       encoding="utf-8")
    print(f"\nguardado: {destino.name} ({len(claves_pagina)} asientos del recorrido por páginas)")

    # comparación con lo que hay en caché
    from app import cache  # noqa: E402
    guardado = cache.leer_apuntes(EMPRESA, YEAR, ttl=-1)
    if guardado:
        tengo = {clave(a) for a in guardado["asientos"]}
        solo_paginas = claves_pagina - tengo
        print(f"\n=== 5. comparación con la caché ===")
        print(f"   en caché: {len(tengo)} asientos")
        print(f"   en el recorrido por páginas y no en caché: {len(solo_paginas)}")
        for k in list(solo_paginas)[:8]:
            print("     ", k)


if __name__ == "__main__":
    main()
