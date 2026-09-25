"""Módulo `dashboard` — panel de control (no existía en el sistema anterior).

Es lo que hacía falta para dejar de ser «un botón que genera un HTML»: un único cálculo
que devuelve KPIs, series mensuales, comparativa interanual y rankings, y que el portal
pinta como gráficas sin volver a pedir nada al ERP.

Reutiliza el cálculo de PyG del módulo `pyg` para que las cifras del panel y las del
informe no puedan divergir.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .. import informes as inf
from ..ledger import (Linea, MESES, MESES_LARGOS, a_float, agrupar_por_cuenta, fmt, fmt_pct,
                      mes_de, num, por_mes, por_tercero, saldos_por_cuenta, serie_mensual,
                      suma_acreedor, suma_deudor)
from . import pyg

NOMBRE = "dashboard"
TITULO = "Panel de control"
INTERNO = False
DESPLAZAMIENTOS = [0, -1, -2]

P_TESORERIA = pyg.P_TESORERIA
P_CLIENTES = pyg.P_DEUDORES
P_PROVEEDORES = pyg.P_PROVEEDORES


def _tesoreria_mensual(lineas: list[Linea]) -> list[float]:
    """Saldo de tesorería al cierre de cada mes (acumulado, no flujo del mes)."""
    saldos = [0.0] * 13
    movimiento = {m: 0.0 for m in range(1, 13)}
    for l in lineas:
        if any(l.cuenta.startswith(p) for p in P_TESORERIA):
            m = mes_de(l.fecha)
            if 1 <= m <= 12:
                movimiento[m] += l.debe - l.haber
    acumulado = 0.0
    for m in range(1, 13):
        acumulado += movimiento[m]
        saldos[m] = round(acumulado, 2)
    return saldos[1:]


def _ranking_cuentas(lineas: list[Linea], prefijos: list[str], *, signo_deudor: bool,
                     limite: int = 8) -> list[dict[str, Any]]:
    filtradas = [l for l in lineas if any(l.cuenta.startswith(p) for p in prefijos)]
    filas = agrupar_por_cuenta(filtradas, nivel=3)
    for f in filas:
        f["importe"] = round(-f["saldo"], 2) if signo_deudor else f["saldo"]
    filas = [f for f in filas if f["importe"]]
    return sorted(filas, key=lambda f: -abs(f["importe"]))[:limite]


def calcular(por_anio: dict[int, list[Linea]], ctx: dict) -> dict[str, Any]:
    year = int(ctx["year"])
    lineas = por_anio.get(year, [])
    lineas_ant = por_anio.get(year - 1, [])

    actual = pyg.calcular_lineas(lineas, lineas_ant)
    mensual = serie_mensual(lineas, pyg.P_INGRESOS_ACTIVIDAD, pyg.P_GASTOS_ACTIVIDAD)
    acum_ing = acum_gas = 0.0
    for fila in mensual:
        acum_ing += fila["ingresos"]
        acum_gas += fila["gastos"]
        fila["ingresos_acumulados"] = round(acum_ing, 2)
        fila["gastos_acumulados"] = round(acum_gas, 2)
        fila["resultado_acumulado"] = round(acum_ing - acum_gas, 2)
        fila["margen"] = round((fila["resultado"] / fila["ingresos"] * 100), 1) if fila["ingresos"] else 0.0

    tesoreria = _tesoreria_mensual(lineas)
    for i, fila in enumerate(mensual):
        fila["tesoreria"] = tesoreria[i]

    # ---------- comparativa interanual ----------
    anios = sorted({year + d for d in DESPLAZAMIENTOS}, reverse=True)
    comparativa = []
    for y in anios:
        base = pyg.calcular_lineas(por_anio.get(y, []), por_anio.get(y - 1, []))
        comparativa.append({
            "year": y,
            "ingresos": round(base["totalIngresos"], 2),
            "gastos": round(base["aprovisionamientos"] + base["gastosPersonal"] + base["otrosGastosExplot"], 2),
            "ebitda": round(base["ebitda"], 2),
            "resultadoNeto": round(base["resultadoNeto"], 2),
            "activo": round(base["totalActivo"], 2),
            "patrimonioNeto": round(base["patrimonioNeto"], 2),
            "tesoreria": round(base["tesoreria"], 2),
            "margenNeto": round(base["margenNeto"], 1),
            "tiene_datos": bool(por_anio.get(y)),
            "n_asientos": len({(l.documento, l.serie, l.fecha) for l in por_anio.get(y, [])}),
        })

    # ---------- rankings ----------
    top_gastos = _ranking_cuentas(lineas, pyg.P_GASTOS_ACTIVIDAD, signo_deudor=True)
    top_ingresos = _ranking_cuentas(lineas, pyg.P_INGRESOS_ACTIVIDAD, signo_deudor=False)
    clientes = por_tercero(lineas, P_CLIENTES)[:8]
    proveedores = por_tercero(lineas, P_PROVEEDORES)[:8]

    # ---------- avisos ----------
    hoy = date.today()
    en_curso = (year == hoy.year)
    avisos: list[str] = []
    if en_curso:
        avisos.append(f"Ejercicio en curso: datos hasta {MESES_LARGOS[hoy.month - 1]} de {year}.")
    dif = actual["cuadre"]["diferencia"]
    if abs(dif) > 1:
        avisos.append(f"El balance no cuadra: activo menos patrimonio neto y pasivo = {fmt(dif)}.")
    meses_vacios = [f["mes"] for f in mensual if not f["ingresos"] and not f["gastos"]
                    and (f["mes_num"] <= hoy.month if en_curso else True)]
    if meses_vacios:
        avisos.append("Sin movimientos registrados en: " + ", ".join(meses_vacios) + ".")
    if not por_anio.get(year - 1):
        avisos.append(f"No hay datos de {year - 1}: la comparativa interanual no está disponible.")
    if actual["resultadoNeto"] < 0:
        avisos.append(("El resultado acumulado a la fecha es negativo." if en_curso
                       else "El ejercicio cierra con resultado negativo."))
    if actual["fondoManiobra"] < 0:
        avisos.append("El fondo de maniobra es negativo: el circulante no cubre las deudas a corto.")
    if actual["endeudamiento"] > 75:
        avisos.append(f"Endeudamiento elevado ({fmt_pct(actual['endeudamiento'])} del activo).")

    return {
        "year": year,
        "kpis": pyg.metricas_dashboard(actual),
        "pyg": {k: round(v, 2) for k, v in actual.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)},
        "balance": {
            "activoNoCorriente": round(actual["activoNoCorriente"], 2),
            "activoCorriente": round(actual["activoCorriente"], 2),
            "existencias": round(actual["existencias"], 2),
            "clientes": round(actual["clientesSaldo"], 2),
            "tesoreria": round(actual["tesoreria"], 2),
            "totalActivo": round(actual["totalActivo"], 2),
            "patrimonioNeto": round(actual["patrimonioNeto"], 2),
            "deudasLP": round(actual["deudasLP"], 2),
            "pasivoCorriente": round(actual["pasivoCorriente"], 2),
        },
        "mensual": mensual,
        "comparativa": comparativa,
        "top_gastos": top_gastos,
        "top_ingresos": top_ingresos,
        "clientes": clientes,
        "proveedores": proveedores,
        "avisos": avisos,
    }


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    return dict(datos.get("kpis") or {})


def informe_html(datos: dict[str, Any], ctx: dict) -> str:
    year = datos["year"]
    k = datos["kpis"]
    mensual = datos["mensual"]
    categorias = [f["mes"] for f in mensual]

    tarjetas = [
        ("Ingresos", inf.importe(k["totalIngresos"])),
        ("Resultado neto", inf.importe(k["resultadoNeto"])),
        ("EBITDA", inf.importe(k["ebitda"])),
        ("Fondo de maniobra", inf.importe(k["fondoManiobra"])),
        ("Tesorería", inf.importe(k["tesoreria"])),
        ("Patrimonio neto", inf.importe(k["patrimonioNeto"])),
        ("Margen EBITDA", fmt_pct(k["margenEBITDA"])),
        ("Endeudamiento", fmt_pct(k["endeudamiento"])),
    ]

    grafico_mensual = inf.barras_svg(categorias, [
        {"nombre": "Ingresos", "color": inf.AZUL, "valores": [f["ingresos"] for f in mensual]},
        {"nombre": "Gastos", "color": "#c98a2b", "valores": [f["gastos"] for f in mensual]},
    ], titulo="Ingresos y gastos por mes")
    grafico_acum = inf.lineas_svg(categorias, [
        {"nombre": "Resultado acumulado", "color": inf.AZUL, "valores": [f["resultado_acumulado"] for f in mensual]},
        {"nombre": "Tesorería", "color": inf.POSITIVO, "valores": [f["tesoreria"] for f in mensual]},
    ], titulo="Resultado acumulado y tesorería")

    comparativa = datos["comparativa"]
    cats_comp = [str(c["year"]) for c in comparativa]
    grafico_comparativa = inf.barras_svg(cats_comp, [
        {"nombre": "Ingresos", "color": inf.AZUL, "valores": [c["ingresos"] for c in comparativa]},
        {"nombre": "Resultado neto", "color": inf.POSITIVO, "valores": [c["resultadoNeto"] for c in comparativa]},
    ], titulo="Comparativa interanual")

    tabla_comparativa = inf.tabla(
        ["Ejercicio", "Ingresos", "EBITDA", "Resultado neto", "Tesorería", "Margen neto"],
        [[str(c["year"]), inf.importe(c["ingresos"]), inf.importe(c["ebitda"]),
          inf.importe(c["resultadoNeto"]), inf.importe(c["tesoreria"]), fmt_pct(c["margenNeto"])]
         for c in comparativa],
        anchos=["14%", "19%", "19%", "19%", "19%", "10%"],
    )

    cuerpo = (
        inf.kpis(tarjetas, columnas=4)
        + "".join(inf.aviso(a, tipo="alerta") for a in datos["avisos"])
        + inf.seccion("Evolución del ejercicio", grafico_mensual + f'<div style="margin-top:10px">{grafico_acum}</div>',
                      nota="Importes por mes de los grupos 6 y 7, y saldo de tesorería al cierre de cada mes.")
        + inf.seccion("Comparativa interanual", grafico_comparativa + tabla_comparativa)
        + inf.seccion("Dónde se va el dinero", inf.tabla(
            ["Cuenta", "Importe"], [[f["cuenta"], inf.importe(f["importe"])] for f in datos["top_gastos"]], anchos=["70%", "30%"]),
            nota="Cuentas de gasto agrupadas a tres dígitos.")
        + inf.seccion("Principales clientes y proveedores", inf.tabla(
            ["Tercero", "Pendiente de cobro", "Pendiente de pago"],
            [[(c["tercero"][:38] or "(sin nombre)"), inf.importe(c["saldo"]),
              inf.importe(next((p["saldo"] for p in datos["proveedores"] if p["tercero"] == c["tercero"]), 0))]
             for c in datos["clientes"][:6]], anchos=["52%", "24%", "24%"]))
    )
    return inf.envoltura(titulo="Panel de control financiero", subtitulo=f"Ejercicio {datos['year']}",
                         empresa=ctx["empresa"], ejercicio=datos["year"], cuerpo=cuerpo)
