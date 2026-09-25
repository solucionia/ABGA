"""Verificación del núcleo: PyG, dashboard y caché, contra datos reales del fixture.

Comprueba lo que tiene que cuadrar por contabilidad, no sólo que el código no falle:
  * el libro cuadra (ΣDebe == ΣHaber)
  * activo == patrimonio neto + pasivo
  * la cadena de la cuenta de resultados es coherente con sus componentes
  * el HTML empieza por `<div` y respeta las convenciones (fuentes, ancho, colores)
  * los totales mensuales suman el total del ejercicio
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import informes as inf  # noqa: E402
from app.ledger import comprobar_cuadre, lineas_de_asientos  # noqa: E402
from app.modulos import dashboard, pyg  # noqa: E402

FALLOS: list[str] = []


def check(condicion: bool, mensaje: str) -> None:
    print(("  OK   " if condicion else "  FALLO") + f" {mensaje}")
    if not condicion:
        FALLOS.append(mensaje)


def casi(a: float, b: float, tol: float = 1.0) -> bool:
    return abs(a - b) <= tol


def cargar(year: int):
    ruta = RAIZ / "fixtures" / f"apuntes_6091_{year}.json"
    if not ruta.exists():
        return None
    return json.load(open(ruta, encoding="utf-8"))["asientos"]


def main() -> None:
    ctx = {"empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": 2025, "year_anterior": 2024,
           "nombre_mes": "septiembre", "trimestre": 3, "email": ""}

    print("=== datos de entrada ===")
    asientos_2025, asientos_2024 = cargar(2025), cargar(2024)
    if not asientos_2025:
        print("faltan fixtures; ejecuta antes backend/scripts/traer_ejercicio.py")
        raise SystemExit(1)
    lineas_2025 = lineas_de_asientos(asientos_2025)
    lineas_2024 = lineas_de_asientos(asientos_2024 or [])
    print(f"  2025: {len(asientos_2025)} asientos -> {len(lineas_2025)} líneas")
    print(f"  2024: {len(asientos_2024 or [])} asientos -> {len(lineas_2024)} líneas")

    print("\n=== integridad del libro ===")
    cuadre = comprobar_cuadre(lineas_2025)
    print(f"  ΣDebe={cuadre['debe']:,.2f}  ΣHaber={cuadre['haber']:,.2f}  descuadre={cuadre['descuadre']:,.2f}")
    check(casi(cuadre["descuadre"], 0, 5), "el libro cuadra (ΣDebe ≈ ΣHaber)")

    print("\n=== PyG ===")
    d = pyg.calcular_lineas(lineas_2025, lineas_2024)
    check(casi(d["totalIngresos"], d["ventas"] + d["otrosIngresos"], 0.5), "ingresos = ventas + otros ingresos")
    check(casi(d["ebitda"], d["totalIngresos"] - d["aprovisionamientos"] - d["gastosPersonal"] - d["otrosGastosExplot"], 0.5),
          "EBITDA = ingresos − aprovisionamientos − personal − otros gastos")
    check(casi(d["ebit"], d["ebitda"] - d["amortizaciones"], 0.5), "EBIT = EBITDA − amortizaciones")
    check(casi(d["rai"], d["ebit"] + d["ingresosFinancieros"] - d["gastosFinancieros"], 0.5),
          "RAI = EBIT + ingresos financieros − gastos financieros")
    check(casi(d["resultadoNeto"], d["rai"] - d["impuesto"], 0.5), "resultado = RAI − impuesto")
    check(casi(d["cashFlow"], d["resultadoNeto"] + d["amortizaciones"], 0.5), "cash-flow = resultado + amortizaciones")

    print("\n=== balance ===")
    print(f"  Activo={d['totalActivo']:,.2f}  PN+Pasivo={d['totalPasivo']:,.2f}  diferencia={d['cuadre']['diferencia']:,.2f}")
    check(casi(d["totalActivo"], d["totalPasivo"], 1.0),
          "activo == patrimonio neto + pasivo (antes no cuadraba por el recorte a cero: Math.max(0, …))")
    check(casi(d["activoNoCorriente"], d["inmovIntangible"] + d["inmovMaterial"] + d["inversionesLP"], 0.5),
          "activo no corriente = intangible + material + inversiones LP")
    check(casi(d["totalActivo"], d["activoNoCorriente"] + d["activoCorriente"], 0.5), "activo = no corriente + corriente")

    print("\n=== impuesto de sociedades (defecto del original) ===")
    print(f"  impuesto contabilizado (cta 630) = {d['impuesto']:,.2f}")
    print(f"  otros gastos de explotación      = {d['otrosGastosExplot']:,.2f} (ya NO incluye la 630)")
    check("630" not in pyg.P_OTROS_GASTOS, "la cuenta 630 no está en gastos de explotación (no se resta dos veces)")

    print("\n=== dashboard ===")
    datos = dashboard.calcular({2025: lineas_2025, 2024: lineas_2024, 2023: []}, ctx)
    total_mensual = sum(f["ingresos"] for f in datos["mensual"])
    check(casi(total_mensual, d["totalIngresos"], 1.0),
          f"los ingresos mensuales suman el total del ejercicio ({total_mensual:,.2f} vs {d['totalIngresos']:,.2f})")
    total_gastos_mensual = sum(f["gastos"] for f in datos["mensual"])
    gasto_anual = d["aprovisionamientos"] + d["gastosPersonal"] + d["otrosGastosExplot"]
    print(f"  gastos: serie mensual {total_gastos_mensual:,.2f} vs informe {gasto_anual:,.2f}")
    check(len(datos["mensual"]) == 12, "la serie mensual tiene 12 meses")
    check(len(datos["comparativa"]) == 3, "la comparativa trae los 3 ejercicios del módulo")
    check(all(isinstance(f["tesoreria"], float) for f in datos["mensual"]), "la tesorería mensual es numérica")
    check(bool(datos["avisos"]), "el panel emite avisos cuando falta algún ejercicio")

    print("\n=== maquetación ===")
    for nombre, mod, dd in (("pyg", pyg, d), ("dashboard", dashboard, datos)):
        html = mod.informe_html(dd, ctx)
        print(f"  {nombre}: {len(html)} caracteres")
        check(html.lstrip().startswith("<div"), f"{nombre}: el HTML empieza por <div")
        check("<table" in html and "style=" in html, f"{nombre}: lleva tabla y CSS inline")
        check("Arial" in html, f"{nombre}: fuente Arial")
        check(inf.AZUL in html and inf.NEGATIVO in html, f"{nombre}: usa los colores de la casa")
        check("ABGA Consultores · farias@abgaconsultores.com · 913 788 740" in html,
              f"{nombre}: el pie lleva el contacto de ABGA")
        check("<h1" not in html.lower() and "```" not in html, f"{nombre}: sin markdown ni etiquetas raras")
        check("max-width:780px" in html, f"{nombre}: ancho 780px")
        # importes en formato español
        ejemplo = re.findall(r">([\d.]+,\d{2} €)<", html)
        if ejemplo:
            check(True, f"{nombre}: importes en formato es-ES (p. ej. {ejemplo[0]})")
        else:
            check(False, f"{nombre}: no se han encontrado importes es-ES")

    print("\n=== resultado ===")
    if FALLOS:
        print(f"  {len(FALLOS)} comprobaciones han fallado:")
        for f in FALLOS:
            print("   -", f)
        raise SystemExit(1)
    print("  todas las comprobaciones han pasado")


if __name__ == "__main__":
    main()
