"""Enseña, entero, lo que devuelven los módulos `memoria` y `duplicados`.

Los demás módulos caben en el resumen de `contrato_modulos.py`, pero estos dos tienen listas largas
dentro (notas, inmovilizado, clientes por cuenta, parejas duplicadas) y hace falta ver la forma de
un elemento para poder traducirlos en el frontal. Se ejecuta con los fixtures: no toca el ERP.

    ./.venv/bin/python backend/scripts/probe_dos_modulos.py
"""

import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import modulos  # noqa: E402
from app.ledger import lineas_de_asientos  # noqa: E402

CTX = {
    "empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": 2025, "year_anterior": 2024,
    "nombre_mes": "septiembre", "trimestre": 3, "email": "prueba@abga.es",
}


def main() -> None:
    asientos = json.loads((RAIZ / "fixtures" / "apuntes_6091_2025.json").read_text(encoding="utf-8"))
    lineas = lineas_de_asientos(asientos["asientos"])
    for nombre in ("memoria", "duplicados"):
        modulo = modulos.obtener(nombre)
        datos = modulo.calcular({2025 - d: lineas for d in (modulo.desplazamientos or [0])}, dict(CTX))
        print("=" * 30, nombre)
        for clave, valor in datos.items():
            if isinstance(valor, list):
                primero = json.dumps(valor[0], ensure_ascii=False)[:300] if valor else ""
                print(f"  {clave}: lista de {len(valor)} -> {primero}")
            elif isinstance(valor, dict):
                print(f"  {clave}: diccionario -> {list(valor)[:20]}")
            else:
                print(f"  {clave}: {type(valor).__name__} = {str(valor)[:80]}")


if __name__ == "__main__":
    main()
