"""Comprobación de integridad: ¿el recorrido por páginas cubre todo el ejercicio?

Compara dos caminos independientes:
  A) recorrer páginas 1..N hasta que la enumeración deja de avanzar
  B) preguntar `ResultadosTotales` por trimestre y sumarlos
Si A == B, sabemos exactamente cuántos asientos tiene el ejercicio y que no perdemos
ninguno. Además se prueba si `$orderby` estabiliza el tramo final.
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
YEAR = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
PAUSA = 3.0

cli = httpx.Client(timeout=180.0)


def get(params, cab, nota):
    time.sleep(PAUSA)
    t0 = time.perf_counter()
    r = cli.get(f"{BASE}/api/apuntes/", params=params, headers=cab)
    print(f"[{r.status_code}] {nota} -> {time.perf_counter()-t0:.2f}s")
    return r


def clave(a):
    return (a.get("Ejercicio"), a.get("Serie"), a.get("Documento"), a.get("Fecha"), a.get("Debe"), a.get("Haber"))


def main() -> None:
    tok = cli.post(f"{BASE}/token", data={
        "grant_type": "password", "username": cfg.apicon_username, "password": cfg.apicon_password,
        "client_id": cfg.apicon_client_id, "client_secret": cfg.apicon_client_secret, "cod_empresa": EMPRESA},
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    cab = {"Authorization": f"Bearer {tok.json()['access_token']}", "Accept": "application/json"}
    print(f"empresa {EMPRESA} · ejercicio {YEAR}\n")

    # ---- B) totales por trimestre ----
    print("=== B) ResultadosTotales por trimestre ===")
    suma = 0
    for t, (ini, fin) in enumerate(
            [(f"{YEAR}0101", f"{YEAR}0331"), (f"{YEAR}0401", f"{YEAR}0630"),
             (f"{YEAR}0701", f"{YEAR}0930"), (f"{YEAR}1001", f"{YEAR}1231")], start=1):
        filtro = f"Ejercicio eq '{YEAR}' and Fecha ge {ini} and Fecha le {fin}"
        r = get({"$filter": filtro, "$top": "1", "$skip": "1"}, cab, f"T{t} {ini}-{fin}")
        if r.status_code != 200:
            print("   400/error ->", r.text[:200])
            continue
        j = r.json()
        n = int(j.get("ResultadosTotales") or 0)
        suma += n
        print(f"   T{t}: ResultadosTotales={n}")
    r = get({"$filter": f"Ejercicio eq '{YEAR}'", "$top": "1", "$skip": "1"}, cab, "año completo")
    total_anio = int(r.json().get("ResultadosTotales") or 0) if r.status_code == 200 else -1
    print(f"   año completo: ResultadosTotales={total_anio} | suma de trimestres={suma}\n")

    # ---- A) recorrido por páginas con detección de reinicio ----
    print("=== A) recorrido por páginas ===")
    vistos: dict[tuple, int] = {}
    pagina = 1
    fecha_max = 0
    while pagina <= 30:
        r = get({"$filter": f"Ejercicio eq '{YEAR}'", "$top": "200", "$skip": str(pagina)}, cab, f"pág {pagina}")
        if r.status_code != 200:
            break
        j = r.json()
        datos = j.get("Datos") or []
        if not datos:
            print("   página vacía: fin")
            break
        fechas = [a.get("Fecha") or 0 for a in datos]
        nuevos = sum(1 for a in datos if clave(a) not in vistos)
        reinicio = max(fechas) < fecha_max
        print(f"   pág {pagina}: n={len(datos)} nuevos={nuevos} fechas {min(fechas)}..{max(fechas)} "
              f"reinicio={reinicio} acumulado={len(vistos) + nuevos}")
        for a in datos:
            vistos[clave(a)] = pagina
        fecha_max = max(fecha_max, max(fechas))
        if reinicio:
            print("   -> la enumeración ha vuelto al principio: hemos terminado")
            break
        pagina += 1

    print(f"\nRESUMEN: recorrido={len(vistos)} asientos únicos | ResultadosTotales(año)={total_anio} "
          f"| suma trimestres={suma}")

    # ---- C) ¿$orderby estabiliza? ----
    print("\n=== C) ¿$orderby estabiliza la enumeración? ===")
    for orden in ("$orderby=Documento", "$orderby=Serie,Documento", "$orderby=Fecha asc"):
        r = get({"$filter": f"Ejercicio eq '{YEAR}'", "$top": "5", "$skip": "1", "$orderby": orden.split("=", 1)[1]},
                cab, f"probe {orden}")
        if r.status_code != 200:
            print("   no soportado:", r.text[:120])
    # con $orderby, ¿la última página sigue reiniciando?
    for p in (6, 7, 8):
        r = get({"$filter": f"Ejercicio eq '{YEAR}'", "$top": "200", "$skip": str(p),
                 "$orderby": "Documento"}, cab, f"ordenada pág {p}")
        if r.status_code == 200:
            j = r.json()
            d = j.get("Datos") or []
            fs = [a.get("Fecha") for a in d]
            print(f"   ordenada pág {p}: n={len(d)} fechas {min(fs) if fs else '-'}..{max(fs) if fs else '-'}")

    destino = RAIZ / "fixtures" / f"integ_{EMPRESA}_{YEAR}.json"
    destino.write_text(json.dumps({"empresa": EMPRESA, "year": YEAR, "recorrido": len(vistos),
                                   "total_declarado": total_anio, "suma_trimestres": suma},
                                  ensure_ascii=False), encoding="utf-8")
    print("\nguardado:", destino.name)


if __name__ == "__main__":
    main()
