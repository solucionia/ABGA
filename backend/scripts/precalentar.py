"""Precalienta la caché: deja los ejercicios listos antes de que nadie los pida.

El ERP tarda ~200 s en entregar un ejercicio completo (22 peticiones con pausa, porque
limita el ritmo) y 0,04 s cuando está en caché. Este script es el que hace que el portal
sea inmediato para el cliente: se lanza por la noche, por ejemplo con un cronjob de Hermes.

Uso:
    ./.venv/bin/python backend/scripts/precalentar.py [cod_empresa ...] [--years 2024 2025] [--forzar]
Sin argumentos recorre todas las empresas dadas de alta y los años indicados en la
configuración.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import apicon, db, modulos  # noqa: E402
from app.config import cargar_config  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    forzar = "--forzar" in sys.argv
    years: list[int] = []
    if "--years" in sys.argv:
        i = sys.argv.index("--years") + 1
        while i < len(sys.argv) and not sys.argv[i].startswith("--"):
            years.append(int(sys.argv[i]))
            i += 1
    if not years:
        years = list(cargar_config().ejercicios_disponibles)

    empresas = args or [e["cod_empresa"] for e in db.listar_empresas()]
    if not empresas:
        print("no hay empresas dadas de alta: ejecuta antes backend/scripts/init_db.py")
        return

    cli = apicon.cliente()
    t_total = time.perf_counter()
    print(f"precalentando {len(empresas)} empresa(s) y {len(years)} ejercicio(s)")
    for cod in empresas:
        for year in years:
            t0 = time.perf_counter()
            try:
                info = cli.apuntes(cod, year, forzar=forzar)
                print(f"  {cod}/{year}: {info['n_asientos']} asientos · {info['cobertura']} · "
                      f"{time.perf_counter() - t0:.1f}s · desde_cache={info.get('desde_cache')}")
            except apicon.ErrorErp as e:
                print(f"  {cod}/{year}: ERROR del ERP — {e}")
    print(f"\ntotal {time.perf_counter() - t_total:.1f}s")


if __name__ == "__main__":
    main()
