"""Carga ejercicios en la caché usando el cliente definitivo y comprueba la cobertura.

Uso: ./.venv/bin/python backend/scripts/traer_cache.py 6091 2025 2024 [--forzar]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import apicon, cache  # noqa: E402

forzar = "--forzar" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
empresa = args[0] if args else "6091"
years = [int(y) for y in (args[1:] or ["2025"])]

cli = apicon.cliente()
t_total = time.perf_counter()
for y in years:
    t0 = time.perf_counter()
    info = cli.apuntes(empresa, y, forzar=forzar)
    print(f"{empresa}/{y}: {info['n_asientos']} asientos, {info['n_lineas']} líneas, "
          f"cobertura={info['cobertura']}, peticiones={info.get('peticiones')}, "
          f"{time.perf_counter() - t0:.1f}s, desde_cache={info.get('desde_cache')}")
    if info.get("dias_paginados"):
        print("   días con más de una página:", info["dias_paginados"])

print(f"\ntotal {time.perf_counter() - t_total:.1f}s")
print("\nestado de la caché:")
for f in cache.info_cache(empresa):
    print(f"  {f['empresa']}/{f['ejercicio']}: {f['n_asientos']} asientos, {f['n_lineas']} líneas, "
          f"{f['segundos']}s, {f['actualizado']}")
    print(f"     cobertura: {f['cobertura']} (el ERP declara {f['resultados_totales']})")

# segunda lectura: debe ser instantánea (viene de caché)
t0 = time.perf_counter()
info = cli.apuntes(empresa, years[0])
print(f"\nsegunda lectura de {empresa}/{years[0]}: {time.perf_counter() - t0:.3f}s "
      f"(desde_cache={info.get('desde_cache')})")
