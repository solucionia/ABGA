"""Enseña un elemento entero de cada lista con miga: hallazgos, cuentas, terceros y parejas.

Es el complemento de `contrato_modulos.py` (que resume las claves) y de `probe_dos_modulos.py`: aquí
se ve un elemento completo de las listas de `analisis`, `conciliacion` y `duplicados`, que es lo que
necesita el frontal para pintarlas. Con los fixtures: no toca el ERP.

    ./.venv/bin/python backend/scripts/probe_entradas.py
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


def calcular(lineas: dict, nombre: str) -> dict:
    modulo = modulos.obtener(nombre)
    return modulo.calcular({2025 - d: lineas for d in (modulo.desplazamientos or [0])}, dict(CTX))


def trozo(etiqueta: str, valor: object, largo: int = 900) -> None:
    print(f"### {etiqueta}")
    print(json.dumps(valor, ensure_ascii=False, indent=2)[:largo])


def main() -> None:
    asientos = json.loads((RAIZ / "fixtures" / "apuntes_6091_2025.json").read_text(encoding="utf-8"))
    lineas = lineas_de_asientos(asientos["asientos"])

    analisis = calcular(lineas, "analisis")
    trozo("ANÁLISIS · una comprobación", analisis["hallazgos"][0], 1200)
    trozo("ANÁLISIS · resumen", analisis["resumen"])

    conciliacion = calcular(lineas, "conciliacion")
    trozo("CONCILIACIÓN · un hallazgo", conciliacion["hallazgos"][0], 900)
    trozo("CONCILIACIÓN · una cuenta", conciliacion["cuentas"][0])
    trozo("CONCILIACIÓN · un tercero", conciliacion["terceros"][0])

    duplicados = calcular(lineas, "duplicados")
    trozo("DUPLICADOS · una pareja", duplicados["duplicados"][0], 1600)

    fiscal = calcular(lineas, "fiscal")
    trozo("FISCAL · IVA por trimestre", fiscal["ivaTrimestreDetalle"], 700)
    trozo("FISCAL · vencimientos", fiscal.get("vencimientos"), 700)


if __name__ == "__main__":
    main()
