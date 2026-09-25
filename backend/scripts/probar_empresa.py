"""Pasa todos los módulos por una empresa ya cacheada (prueba de aceptación).

    APICON_SOLO_CACHE=1 ./.venv/bin/python backend/scripts/probar_empresa.py 6221 2025

No llama al ERP: exige `APICON_SOLO_CACHE=1` y que el ejercicio esté en la caché. Sirve para
comprobar que los módulos aguantan una empresa grande y que la cobertura parcial se declara.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

os.environ.setdefault("APICON_SOLO_CACHE", "1")

from app import modulos, servicio  # noqa: E402


def main() -> int:
    cod = sys.argv[1] if len(sys.argv) > 1 else "6221"
    year = int(sys.argv[2] if len(sys.argv) > 2 else 2025)

    dash = servicio.datos_dashboard(cod, year)
    if dash.get("status") != "ok":
        print("el panel no se pudo calcular:", dash.get("error"))
        return 1

    k = dash["data"]["kpis"]
    meta = dash["meta"]
    print(f"=== panel {cod}/{year} ===")
    print(f"  ingresos={k['totalIngresos']:,.2f}  resultado={k['resultadoNeto']:,.2f}  "
          f"ebitda={k['ebitda']:,.2f}  activo={k['totalActivo']:,.2f}  "
          f"patrimonio={k['patrimonioNeto']:,.2f}")
    for y, ej in sorted((meta.get("ejercicios") or {}).items()):
        print(f"  ejercicio {y}: {ej.get('n_asientos')} asientos · cobertura={ej.get('cobertura')}"
              f" · cerrado={ej.get('cerrado')}")
    print("  avisos del panel:")
    for a in dash["data"].get("avisos", []):
        print(f"    · {a}")

    print(f"\n=== los 10 módulos con {cod}/{year} ===")
    fallos = []
    for d in modulos.listar_todos():
        if not d.disponible:
            print(f"  --   {d.nombre:<13} no disponible: {d.error}")
            fallos.append(d.nombre)
            continue
        t = time.perf_counter()
        r = servicio.ejecutar(d.nombre, cod_empresa=cod, year=year, origen="prueba")
        seg = time.perf_counter() - t
        if r.status != "ok":
            print(f"  KO   {d.nombre:<13} {seg:6.1f} s  {r.error}")
            fallos.append(d.nombre)
            continue
        avisos = r.avisos or []
        parciales = [a for a in avisos if "parcial" in a.lower()]
        print(f"  OK   {d.nombre:<13} {seg:6.1f} s  {len(r.html or ''):>7} car. HTML  "
              f"{len(avisos)} avisos" + (f"  (¡{len(parciales)} de cobertura parcial!)" if parciales else ""))
        for a in parciales[:2]:
            print(f"        cobertura: {a}")
    print()
    print("todos los módulos han pasado" if not fallos else f"FALLOS: {', '.join(fallos)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
