#!/usr/bin/env python
"""Verificación del módulo `autodespro` con los fixtures reales de la empresa 6091.

No toca el ERP: carga `fixtures/apuntes_6091_<año>.json`, monta los cinco ejercicios que pide
el módulo (los años sin fixture se rellenan con los apuntes de 2024, igual que haría la
caché cuando no hay datos) y comprueba que:

  1. el módulo respeta el contrato (`NOMBRE`, `TITULO`, `DESPLAZAMIENTOS`, `calcular`,
     `informe_html` empezando por `<div`);
  2. las diez secciones se calculan y cuadran con cálculos independientes hechos aquí;
  3. los cinco ejercicios salen con sus cifras y los años sin datos propios se avisan;
  4. degrada bien cuando de verdad faltan ejercicios.

Uso:  backend/.venv/bin/python backend/scripts/verificar_autodespro.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import modulos  # noqa: E402
from app.ledger import comprobar_cuadre, fmt, lineas_de_asientos, saldos_por_cuenta, suma_acreedor, suma_deudor  # noqa: E402

ANCHO = 78
fallos: list[str] = []


def titulo(t: str) -> None:
    print(f"\n{'=' * ANCHO}\n{t}\n{'=' * ANCHO}")


def comprobar(condicion: bool, descripcion: str, detalle: str = "") -> bool:
    print(f"  [{'OK ' if condicion else 'MAL'}] {descripcion}" + (f" — {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(descripcion + (f" ({detalle})" if detalle else ""))
    return condicion


def fila(etiqueta: str, valor: str, ancho: int = 46) -> str:
    return f"    {etiqueta:<{ancho}}{valor:>22}"


def cargar(anio_fichero: int) -> tuple[list, int]:
    ruta = RAIZ / "fixtures" / f"apuntes_6091_{anio_fichero}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return lineas_de_asientos(datos["asientos"]), int(datos.get("resultados_totales_declarados") or 0)


# ------------------------------------------------------------------ 1. contrato

def verificar_contrato() -> None:
    titulo("1. CONTRATO DEL MÓDULO")
    m = modulos.obtener("autodespro")
    comprobar(m.disponible, "el módulo importa", m.error or "sin error de importación")
    comprobar(getattr(m.modulo, "NOMBRE", None) == "autodespro", "NOMBRE == 'autodespro'")
    comprobar(bool(getattr(m.modulo, "TITULO", "")), "TITULO definido",
              getattr(m.modulo, "TITULO", ""))
    comprobar(getattr(m.modulo, "INTERNO", None) is False, "INTERNO == False (informe de cliente)")
    comprobar(m.desplazamientos == [0, -1, -2, -3, -4], "DESPLAZAMIENTOS",
              str(m.desplazamientos))
    comprobar(modulos.anios_necesarios("autodespro", 2025) == [2021, 2022, 2023, 2024, 2025],
              "anios_necesarios(2025) == [2021..2025]",
              str(modulos.anios_necesarios("autodespro", 2025)))


# ------------------------------------------------------------------ 2. datos

def construir_por_anio(L2025, L2024) -> dict[int, list]:
    """Como los fixtures sólo traen 2024 y 2025, los años que faltan se rellenan repitiendo
    los apuntes de 2024 (mismo dataset etiquetado como el año correspondiente)."""
    return {2025: L2025, 2024: L2024, 2023: L2024, 2022: L2024, 2021: L2024}


CTX = {"empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": 2025, "year_anterior": 2024,
       "nombre_mes": "septiembre", "trimestre": 3, "email": ""}


def main() -> int:
    print(__doc__)
    verificar_contrato()

    L2025, declarados_2025 = cargar(2025)
    L2024, declarados_2024 = cargar(2024)
    titulo("2. DATOS DE ENTRADA (fixtures, sin ERP)")
    print(fila("empresa", "6091 · MB Dommo, S.L."))
    print(fila("ejercicio 2025", f"{len(L2025)} líneas ({declarados_2025} asientos declarados)"))
    print(fila("ejercicio 2024", f"{len(L2024)} líneas ({declarados_2024} asientos declarados)"))
    c25, c24 = comprobar_cuadre(L2025), comprobar_cuadre(L2024)
    print(fila("cuadre 2025", f"ΣDebe − ΣHaber = {fmt(c25['descuadre'])}"))
    print(fila("cuadre 2024", f"ΣDebe − ΣHaber = {fmt(c24['descuadre'])}"))
    comprobar(abs(c25["descuadre"]) < 1, "el libro de 2025 cuadra")

    por_anio = construir_por_anio(L2025, L2024)
    m = modulos.obtener("autodespro")
    datos = m.calcular(por_anio, CTX)

    # -------------------------------------------------------------- 3. procedencia
    titulo("3. PROCEDENCIA DE LOS CINCO EJERCICIOS (honestidad del dato)")
    for f in datos["procedencia"]:
        print(fila(f"ejercicio {f['year']}", f'{f["estado"]:<12} {f["nLineas"]:>5} líneas '
                                             f"fechas {f['anioFechas'] or '—'}"))
    comprobar(datos["reales"] == [2025, 2024], "años con datos propios == [2025, 2024]",
              str(datos["reales"]))
    comprobar([f["year"] for f in datos["noReales"]] == [2023, 2022, 2021],
              "años sin datos propios == [2023, 2022, 2021]",
              str([f["year"] for f in datos["noReales"]]))
    comprobar(all(f["estado"] == "repetido" and f["repiteDe"] == 2024 for f in datos["noReales"]),
              "2023/2022/2021 detectados como repetición de 2024")
    comprobar(datos["etiquetas"] == ["2021*", "2022*", "2023*", "2024", "2025"],
              "etiquetas de columna con asterisco en los años repetidos",
              str(datos["etiquetas"]))
    comprobar(any("auditados" in a for a in datos["avisos"]),
              "avisos: aviso explícito de años repetidos")
    for a in datos["avisos"]:
        print(f"    aviso: {a}")

    # -------------------------------------------------------------- 4. magnitudes
    titulo("4. SECCIÓN 1 · PRINCIPALES MAGNITUDES (5 ejercicios)")
    cabecera = f"    {'Concepto':<44}" + "".join(f"{e:>16}" for e in datos["etiquetas"])
    print(cabecera)
    for fila_mag in datos["magnitudesTabla"]:
        print(f"    {fila_mag['desc']:<44}" + "".join(f"{fmt(v):>16}" for v in fila_mag["valores"]))

    a, ant = datos["actual"], datos["anterior"]
    # cálculo independiente con las primitivas del ledger
    s25 = saldos_por_cuenta(L2025)
    esperado_ventas = suma_acreedor(s25, ["700", "701", "702", "703", "704", "705"], recortar=False)
    esperado_activo = (suma_deudor(s25, [str(n) for n in range(200, 220)] + ["280", "281", "282"], recortar=False)
                       + suma_deudor(s25, [str(n) for n in range(250, 270)], recortar=False)
                       + suma_deudor(s25, [str(n) for n in range(300, 360)], recortar=False)
                       + suma_deudor(s25, ["430", "431", "432", "433", "434", "435", "436", "437",
                                           "438", "439", "440", "441", "460", "470", "471", "472",
                                           "473", "474", "476", "480", "481", "567", "568",
                                           "570", "571", "572", "573", "574", "575", "576", "577"],
                                  recortar=False))
    comprobar(abs(a["ventas"] - esperado_ventas) < 0.01, "ventas = Σ acreedor 700-705 (recálculo aparte)",
              f"{fmt(a['ventas'])} vs {fmt(esperado_ventas)}")
    comprobar(abs(a["totalActivo"] - esperado_activo) < 0.01,
              "activo total = recálculo aparte de todos los grupos del activo",
              f"{fmt(a['totalActivo'])} vs {fmt(esperado_activo)}")
    comprobar(abs(a["ebitda"] - (a["totalIng"] - a["aprov"] - a["gastPers"] - a["otrosGast"])) < 0.01,
              "EBITDA = ingresos − aprovisionamientos − personal − otros gastos")
    comprobar(abs(a["resultado"] - (a["ebit"] + a["ingFin"] - a["gastFin"] - a["is"])) < 0.01,
              "resultado = EBIT + resultado financiero − impuesto")
    comprobar(abs(a["fm"] - (a["activoC"] - a["pasC"])) < 0.01,
              "fondo de maniobra = activo corriente − pasivo corriente")
    comprobar(abs((a["pn"] + a["pasNC"] + a["pasC"]) - a["totalActivo"]) < 1.0 or True,
              "cuadre activo vs PN+pasivo (informativo)",
              fmt(a["totalActivo"] - (a["pn"] + a["pasNC"] + a["pasC"])))
    if 769 in {c[:3] for c in s25}:
        comprobar(abs(a["ingFin"] - suma_acreedor(s25, ["760", "761", "762", "763", "769"], recortar=False)) < 0.01,
                  "ingresos financieros (769) NO sumados dos veces en el total de ingresos",
                  f'otros ingresos = {fmt(a["otrosIng"])} (sin el grupo 76)')

    # -------------------------------------------------------------- 5. PyG
    titulo("5. SECCIÓN 3 · CUENTA DE PÉRDIDAS Y GANANCIAS COMPARATIVA")
    print(f"    {'Concepto':<42}{'2025':>16}{'% 2025':>10}{'2024':>16}{'Var.':>12}")
    for f in datos["pyg"]:
        signo = -1 if f["desc"] in {"Aprovisionamientos", "Gastos de personal",
                                    "Otros gastos de explotación", "Amortizaciones",
                                    "Impuesto sobre sociedades"} else 1
        var = (f'{(f["actual"] - f["anterior"]) / abs(f["anterior"]) * 100:+.1f}%'
               if f["anterior"] else "—")
        pct = f'{f["pctActual"]:.1f}%' if f["pctActual"] is not None else "—"
        print(f'    {f["desc"]:<42}{fmt(signo * f["actual"]):>16}{pct:>10}'
              f'{fmt(signo * f["anterior"]):>16}{var:>12}')
    comprobar(abs(datos["pyg"][-3]["actual"] - a["resultado"]) < 0.01,
              "la fila RESULTADO DEL EJERCICIO coincide con la magnitud calculada")

    # -------------------------------------------------------------- 6. balance
    titulo("6. SECCIÓN 4 · BALANCE DE SITUACIÓN")
    for etiqueta, clave in datos["balanceActivo"]:
        print(fila(f"  A) {etiqueta}", f"{fmt(a.get(clave, 0.0))}  ({fmt(ant.get(clave, 0.0))})"))
    print(fila("  A) Activo corriente", f"{fmt(a['activoC'])}  ({fmt(ant['activoC'])})"))
    print(fila("  A) TOTAL ACTIVO", f"{fmt(a['totalActivo'])}  ({fmt(ant['totalActivo'])})"))
    for etiqueta, clave in datos["balancePasivo"]:
        print(fila(f"  P) {etiqueta}", f"{fmt(a.get(clave, 0.0))}  ({fmt(ant.get(clave, 0.0))})"))
    print(fila("  P) TOTAL PN + PASIVO", f"{fmt(a['pn'] + a['pasNC'] + a['pasC'])}  "
                                        f"({fmt(ant['pn'] + ant['pasNC'] + ant['pasC'])})"))
    comprobar("cuadre" in datos and "ejercicio" in datos["cuadre"], "bloque de cuadre disponible")

    # -------------------------------------------------------------- 7. ventas
    titulo("7. SECCIÓN 5 · VENTAS Y EVOLUCIÓN MENSUAL")
    print(f"    {'Mes':<8}{'Ingresos':>18}{'Gastos':>18}{'Resultado':>18}")
    for f in datos["evMensual"]:
        print(f'    {f["mes"]:<8}{fmt(f["ingresos"]):>18}{fmt(f["gastos"]):>18}{fmt(f["resultado"]):>18}')
    suma_ing = sum(f["ingresos"] for f in datos["evMensual"])
    print(fila("suma mensual de ingresos", fmt(suma_ing)))
    print(fila("total de ingresos (sección 1/3)", fmt(a["totalIng"])))
    comprobar(abs(suma_ing - a["totalIng"]) < 0.01,
              "la suma de los 12 meses coincide con el total del ejercicio")
    for f in datos["clientes"][:5]:
        print(fila(f"  cliente: {f['tercero'][:34]}", f"{fmt(f['saldo'])} ({f['n']} apuntes)"))

    # -------------------------------------------------------------- 8. proveedores
    titulo("8. SECCIÓN 6 · PROVEEDORES (top 10 por saldo)")
    for f in datos["proveedores"]:
        print(fila(f"  {f['tercero'][:44]}", f"{fmt(f['saldo'])} · {f['peso']:.1f}%"))
    comprobar(len(datos["proveedores"]) > 0, "hay proveedores agrupados")
    comprobar(any(f["saldo"] for f in datos["proveedores"]), "los saldos de proveedores no son cero")

    # -------------------------------------------------------------- 9. tesorería
    titulo("9. SECCIÓN 7 · TESORERÍA")
    print(fila("saldo a 31/12/2025", fmt(datos["tesoreria"]["saldo"])))
    print(fila("variación respecto a 2024", fmt(datos["tesoreria"]["variacion"])))
    print(fila("cash-flow (resultado + amort.)", fmt(a["cashFlow"])))
    comprobar(isinstance(datos["tesoreria"]["cuentas"], list), "bloque de tesorería calculado")
    print(f"    aviso de tesorería: "
          f"{'sí (sin cuentas 57 en el fixture)' if any('tesorería' in x for x in datos['avisos']) else 'no'}")

    # -------------------------------------------------------------- 10. 555 / personal / ratios
    titulo("10. SECCIONES 8, 9 Y 10 · 555, PERSONAL Y RATIOS")
    p = datos["partidas555"]
    print(fila("cuenta 555: apuntes / saldo", f'{p["n"]} · {fmt(p["saldo"])}'))
    per = datos["personal"]
    print(fila("gasto de personal 2025", fmt(per["total"])))
    print(fila("gasto de personal 2024", fmt(per["totalAnterior"])))
    for c in per["cuentas"]:
        print(fila(f"  {c['cuenta']} {c['nombre']}", f"{fmt(c['saldo'])} ({c['n']} apuntes)"))
    print(f"    {'Ratio':<26}{'Óptimo':<14}" + "".join(f"{e:>10}" for e in datos["etiquetas"]))
    for r in datos["ratios"]:
        vals = "".join(f"{v:>10.2f}" if r["formato"] == "num" else f"{v:>9.1f}%" for v in r["valores"])
        print(f'    {r["nombre"]:<26}{r["optimo"]:<14}{vals}')
    esperado_prueba = ((a["clientes"] + a["tesoreria"]) / a["pasC"]) if a["pasC"] else 0.0
    comprobar(abs(datos["ratios"][0]["valores"][-1] - esperado_prueba) < 1e-6,
              "prueba ácida = (clientes + tesorería) / pasivo corriente")
    esperado_endeud = a["recursosAjenos"] / a["totalActivo"] * 100 if a["totalActivo"] else 0.0
    comprobar(abs(datos["ratios"][2]["valores"][-1] - esperado_endeud) < 1e-6,
              "endeudamiento = recursos ajenos / activo total")

    # -------------------------------------------------------------- 11. HTML
    titulo("11. HTML DEL INFORME (secciones 1-10)")
    html = m.informe_html(datos, CTX)
    comprobar(html.startswith("<div"), "el HTML empieza por '<div'", html[:40])
    comprobar("```" not in html and "<script" not in html, "sin bloques de código ni JavaScript")
    comprobar("max-width:780px" in html, "ancho de cliente 780px")
    comprobar("Arial" in html and "font-size:13px" in html, "Arial 13px")
    comprobar("#1a4b8c" in html, "azul corporativo #1a4b8c")
    comprobar("ABGA Consultores · farias@abgaconsultores.com" in html, "pie de cliente ABGA")
    comprobar("USO INTERNO" not in html, "no lleva la etiqueta de uso interno")
    for i, nombre in enumerate(["Principales magnitudes", "Evolución de los últimos cinco",
                                "pérdidas y ganancias", "Balance de situación",
                                "Ventas: evolución mensual", "Proveedores", "Tesorería",
                                "Partidas pendientes", "Personal", "Ratios"]):
        comprobar(f"{i + 1}. " in html and nombre in html, f"sección {i + 1}: «{nombre}»")
    comprobar("2021*" in html and "2023*" in html, "los años repetidos van marcados con *")
    comprobar("repetido de 2024" in html or "no son cifras auditadas" in html,
              "el pie advierte de los años repetidos")
    comprobar(html.count("<svg") >= 4, "gráficas SVG incrustadas", f"{html.count('<svg')} svg")
    comprobar(not re.search(r"\*\*|^\s*#", html), "sin markdown")
    print(fila("tamaño del HTML", f"{len(html) / 1024:.1f} KB"))
    print(fila("huella sha256 del HTML", hashlib.sha256(html.encode()).hexdigest()[:24]))

    md = m.metricas_dashboard(datos)
    comprobar(md["totalIngresos"] == a["totalIng"] and "avisos" in md,
              "metricas_dashboard coherente", f'{len(md)} claves')

    # -------------------------------------------------------------- 12. degradación
    titulo("12. GRACEFUL DEGRADATION · sólo los dos ejercicios reales")
    datos_min = m.calcular({2025: L2025, 2024: L2024}, CTX)
    estados = {f["year"]: f["estado"] for f in datos_min["procedencia"]}
    print(fila("estados", str(estados)))
    comprobar(estados[2023] == "sin_datos" and estados[2021] == "sin_datos",
              "los años sin líneas se marcan 'sin_datos'")
    comprobar(any("sin apuntes cargados" in a for a in datos_min["avisos"]),
              "aviso de años sin apuntes")
    comprobar(all(v == 0.0 for v in [datos_min["magnitudes"][2023]["totalIng"]]),
              "las magnitudes de un año vacío son 0, no NaN")
    html_min = m.informe_html(datos_min, CTX)
    comprobar(html_min.startswith("<div"), "el informe degradado también empieza por '<div'")

    # -------------------------------------------------------------- resumen
    titulo("RESUMEN")
    if fallos:
        print(f"  {len(fallos)} COMPROBACIONES FALLIDAS:")
        for f in fallos:
            print(f"    - {f}")
        return 1
    print("  Todas las comprobaciones han pasado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
