"""Saca el contrato REAL de cada módulo: qué claves devuelve `calcular()`.

Se ejecuta con los fixtures, sin tocar el ERP ni la base. Es sólo para saber qué hay dentro de
`datos` y poder traducirlo a lo que espera cada pantalla del hub.
"""

import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]   # raíz del proyecto (…/nuevo)
sys.path.insert(0, str(RAIZ / "backend"))

from app import modulos  # noqa: E402
from app.ledger import lineas_de_asientos  # noqa: E402


def esq(valor, prof=0, maximo=2):
    if isinstance(valor, dict):
        if prof >= maximo:
            return "dict(" + ", ".join(list(valor)[:8]) + ")"
        return "{" + ", ".join(f"{k}: {esq(v, prof + 1, maximo)}" for k, v in list(valor.items())[:14]) + "}"
    if isinstance(valor, list):
        return f"[{len(valor)}]" + (" de " + esq(valor[0], prof + 1, maximo) if valor else "")
    if isinstance(valor, float):
        return "float"
    if isinstance(valor, int):
        return "int"
    if isinstance(valor, bool):
        return "bool"
    return f"str({str(valor)[:28]})"


asientos = json.loads((RAIZ / "fixtures" / "apuntes_6091_2025.json").read_text())["asientos"]
lineas = lineas_de_asientos(asientos)

print("### CATÁLOGO")
for m in modulos.listar_todos():
    print(f"- {m.nombre:16} interno={m.interno!s:5} disponible={m.disponible!s:5} "
          f"desplazamientos={m.desplazamientos} parametros={m.parametros} :: {m.titulo}"
          + (f"  ERROR={m.error}" if m.error else ""))

ctx = {
    "empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": 2025, "year_anterior": 2024,
    "nombre_mes": "septiembre", "trimestre": 3, "email": "prueba@abga.es",
}

print("\n### SALIDA DE calcular()")
for m in modulos.listar_todos():
    if not m.disponible:
        print(f"\n== {m.nombre} :: NO DISPONIBLE ({m.error})")
        continue
    desplazamientos = m.desplazamientos or [0]
    por_anio = {2025 - d: lineas for d in desplazamientos}
    try:
        datos = m.calcular(por_anio, dict(ctx))
        print(f"\n== {m.nombre} :: {esq(datos, 0, 2)}")
    except Exception as fallo:  # noqa: BLE001
        print(f"\n== {m.nombre} :: ERROR {type(fallo).__name__}: {fallo}")
