"""Siembra la caché local con los ejercicios ya exportados a `fixtures/`.

Para qué: la caché de la copia local caduca (12 h) y, cuando caduca, cualquier dashboard o informe
se va al ERP de ABGA a leer miles de apuntes: lento y consume cuota del cliente. Con los ejercicios
ya exportados, esta siembra deja la plataforma respondiendo desde la caché local, **sin tocar el
ERP**, que es lo que hace falta para desarrollar y verificar el frontal con cifras reales.

No modifica los fixtures ni el ERP: sólo escribe en `data/abga.sqlite3` la misma fila que escribiría
una lectura normal del ERP.

    ./.venv/bin/python backend/scripts/sembrar_cache_fixtures.py [6091 ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import cache  # noqa: E402

CARPETA = RAIZ / "fixtures"


def main() -> None:
    filtro = [a for a in sys.argv[1:] if not a.startswith("--")]
    ficheros = sorted(CARPETA.glob("apuntes_*.json"))
    if not ficheros:
        print(f"no hay fixtures en {CARPETA}")
        return
    for fichero in ficheros:
        datos = json.loads(fichero.read_text(encoding="utf-8"))
        empresa = str(datos.get("empresa") or fichero.stem.split("_")[1])
        ejercicio = int(datos.get("year") or fichero.stem.split("_")[2])
        if filtro and empresa not in filtro:
            continue
        asientos = datos.get("asientos") or []
        cache.guardar_apuntes(
            empresa, ejercicio, asientos,
            resultados_totales=datos.get("resultados_totales_declarados"),
            cobertura=datos.get("cobertura") or f"sembrado de {fichero.name}",
            segundos=0.0,
        )
        lineas = sum(len(a.get("Detalles") or []) for a in asientos)
        print(f"sembrado {empresa}/{ejercicio}: {len(asientos)} asientos, {lineas} líneas")

    print("\ncaché local:")
    for fila in cache.info_cache():
        print(f"  {fila['empresa']}/{fila['ejercicio']}: {fila['n_asientos']} asientos, "
              f"{fila['n_lineas']} líneas · {fila['actualizado']}")


if __name__ == "__main__":
    main()
