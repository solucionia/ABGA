"""Módulo `pyg` — REQ-05 Balance y PyG.

Portado del nodo Code «Calcular Estados Financieros» del workflow de n8n, con tres
correcciones sobre el original:

1. **El impuesto se restaba dos veces.** La lista de gastos de explotación incluía la
   cuenta 630 y después `resultadoNeto = rai − impuesto` volvía a restarlo. Aquí la 630
   queda fuera de explotación y se resta una sola vez tras el RAI.
2. **Saldos contrarios.** El original hacía `Math.max(0, total)` en cada agregado, así que
   un saldo de signo contrario (devoluciones, cuentas deudoras en pasivo) se volvía 0 y el
   balance no cuadraba. Aquí se usan los saldos reales y se conserva el signo.
3. **Doble uso de prefijos.** `76` y `778` ya contenían a `760`-`769`; al sumar por prefijos
   anidados se contaba dos veces. Los prefijos se aplican ahora sin solapes.

Además se calculan series mensuales y comparativas de ejercicios, que es lo que alimenta
el dashboard nuevo.
"""
from __future__ import annotations

from typing import Any, Iterable

from .. import informes as inf
from ..ledger import (Linea, MESES, a_float, anio_de, fmt, fmt_pct, mes_de, num, por_mes,
                      saldos_por_cuenta, serie_mensual, suma_acreedor, suma_deudor)

AZUL_FILA = "#eef4fd"

# --- prefijos PGC (sin solapes) ---
P_VENTAS = ["700", "701", "702", "703", "704", "705"]
P_OTROS_INGRESOS = ["706", "708", "709", "740", "741", "746", "747", "748", "749", "75", "778"]
P_APROVISIONAMIENTOS = ["600", "601", "602", "606", "607", "608", "609", "610", "611", "612"]
P_PERSONAL = ["640", "641", "642", "643", "644", "649"]
P_OTROS_GASTOS = ["620", "621", "622", "623", "624", "625", "626", "627", "628", "629",
                  "631", "632", "633", "634", "636", "639", "650", "651", "659",
                  "67"]  # 67 «otros gastos» (670-679), p. ej. 678 gastos excepcionales
P_AMORTIZACIONES = ["680", "681", "682", "690", "691", "692"]
P_ING_FINANCIEROS = ["760", "761", "762", "763", "768", "769"]
P_GASTOS_FINANCIEROS = ["660", "661", "662", "663", "664", "665", "668", "669"]
P_IMPUESTO = ["630"]

P_INMOV_INTANGIBLE = ["200", "201", "202", "203", "204", "205", "206", "207", "280"]
P_INMOV_MATERIAL = ["210", "211", "212", "213", "214", "215", "216", "217", "218", "219", "281", "282"]
P_INVERSIONES_LP = [str(n) for n in range(250, 270)]
P_EXISTENCIAS = [str(n) for n in range(300, 360)]
# 53x y 54x: inversiones financieras a corto plazo (participaciones y valores). Faltaban y una
# empresa del grupo (6221) tenía 800.855,88 € en la 531: el activo salía descuadrado por eso.
P_INVERSIONES_CP = [str(n) for n in range(530, 550)]
P_DEUDORES = ["430", "431", "432", "433", "434", "435", "436", "437", "438", "439",
              "440", "441", "460", "470", "471", "472", "473", "474", "480", "481", "567", "568",
              "490"]  # 490: deterioro de créditos comerciales, correctora del saldo de clientes
# ojo: el original incluía la 476 (Hacienda, acreedora) entre los deudores; está en deudas a corto
P_TESORERIA = ["570", "571", "572", "573", "574", "575", "576", "577"]
P_CAPITAL = ["100", "101", "102", "103", "104", "108", "109"]
P_RESERVAS = [str(n) for n in range(110, 122)]
P_SUBVENCIONES = ["130", "131", "132"]
P_DEUDAS_LP = [str(n) for n in range(150, 180)]
P_PROVEEDORES = [str(n) for n in range(400, 420)]
P_DEUDAS_CP = ([str(n) for n in range(500, 530)] + [str(n) for n in range(550, 560)]
               + ["465", "475", "476", "477"])  # 465 personal, 475/476/477 Hacienda y SS acreedoras

P_INGRESOS_ACTIVIDAD = P_VENTAS + P_OTROS_INGRESOS
P_GASTOS_ACTIVIDAD = P_APROVISIONAMIENTOS + P_PERSONAL + P_OTROS_GASTOS


def calcular_lineas(lineas: list[Linea], lineas_anterior: Iterable[Linea] = ()) -> dict[str, Any]:
    """Cálculo a partir de las líneas ya cargadas (lo usan el dashboard y los informes)."""
    s = saldos_por_cuenta(lineas)
    sa = saldos_por_cuenta(list(lineas_anterior))

    # ---------- PyG ----------
    ventas = suma_acreedor(s, P_VENTAS, recortar=False)
    otros_ingresos = suma_acreedor(s, P_OTROS_INGRESOS, recortar=False)
    total_ingresos = ventas + otros_ingresos
    aprovisionamientos = suma_deudor(s, P_APROVISIONAMIENTOS, recortar=False)
    gastos_personal = suma_deudor(s, P_PERSONAL, recortar=False)
    otros_gastos = suma_deudor(s, P_OTROS_GASTOS, recortar=False)
    amortizaciones = suma_deudor(s, P_AMORTIZACIONES, recortar=False)
    ebitda = total_ingresos - aprovisionamientos - gastos_personal - otros_gastos
    ebit = ebitda - amortizaciones
    ing_financieros = suma_acreedor(s, P_ING_FINANCIEROS, recortar=False)
    gastos_financieros = suma_deudor(s, P_GASTOS_FINANCIEROS, recortar=False)
    rai = ebit + ing_financieros - gastos_financieros
    impuesto = suma_deudor(s, P_IMPUESTO, recortar=False)
    resultado_neto = rai - impuesto
    cash_flow = resultado_neto + amortizaciones

    # ---------- PyG año anterior ----------
    ingresos_ant = (suma_acreedor(sa, P_VENTAS, recortar=False)
                    + suma_acreedor(sa, P_OTROS_INGRESOS, recortar=False))
    rai_ant = (ingresos_ant
               - suma_deudor(sa, P_APROVISIONAMIENTOS, recortar=False)
               - suma_deudor(sa, P_PERSONAL, recortar=False)
               - suma_deudor(sa, P_OTROS_GASTOS, recortar=False)
               - suma_deudor(sa, P_AMORTIZACIONES, recortar=False)
               + suma_acreedor(sa, P_ING_FINANCIEROS, recortar=False)
               - suma_deudor(sa, P_GASTOS_FINANCIEROS, recortar=False))
    resultado_ant = rai_ant - suma_deudor(sa, P_IMPUESTO, recortar=False)

    # ---------- Balance ----------
    inmov_intangible = suma_deudor(s, P_INMOV_INTANGIBLE, recortar=False)
    inmov_material = suma_deudor(s, P_INMOV_MATERIAL, recortar=False)
    inversiones_lp = suma_deudor(s, P_INVERSIONES_LP, recortar=False)
    activo_no_corriente = inmov_intangible + inmov_material + inversiones_lp
    existencias = suma_deudor(s, P_EXISTENCIAS, recortar=False)
    deudores = suma_deudor(s, P_DEUDORES, recortar=False)
    tesoreria = suma_deudor(s, P_TESORERIA, recortar=False)
    inversiones_cp = suma_deudor(s, P_INVERSIONES_CP, recortar=False)
    activo_corriente = existencias + deudores + tesoreria + inversiones_cp
    total_activo = activo_no_corriente + activo_corriente

    capital = suma_acreedor(s, P_CAPITAL, recortar=False)
    reservas = suma_acreedor(s, P_RESERVAS, recortar=False)
    subvenciones = suma_acreedor(s, P_SUBVENCIONES, recortar=False)
    patrimonio_neto = capital + reservas + resultado_neto + subvenciones
    deudas_lp = suma_acreedor(s, P_DEUDAS_LP, recortar=False)
    proveedores = suma_acreedor(s, P_PROVEEDORES, recortar=False)
    deudas_cp = suma_acreedor(s, P_DEUDAS_CP, recortar=False)
    pasivo_corriente = proveedores + deudas_cp
    total_pasivo = deudas_lp + pasivo_corriente + patrimonio_neto
    fondo_maniobra = activo_corriente - pasivo_corriente

    def pct(n: float, d: float) -> float:
        return (n / d * 100) if d else 0.0

    recursos_ajenos = deudas_lp + pasivo_corriente

    # cuentas con saldo que no caen en ningún grupo: si las hay, se declaran en el informe
    huerfanas = cuentas_huerfanas(lineas, limite=10)
    huerfanas_total = round(sum(f["saldo"] for f in cuentas_huerfanas(lineas, limite=10_000)), 2)

    return {
        "year": anio_de(lineas[0].fecha) if lineas else 0,
        # series para las gráficas (contrato: el informe se pinta sólo con `datos` y `ctx`)
        "series": series(lineas),
        # explotación
        "ventas": ventas, "otrosIngresos": otros_ingresos, "totalIngresos": total_ingresos,
        "aprovisionamientos": aprovisionamientos, "gastosPersonal": gastos_personal,
        "otrosGastosExplot": otros_gastos, "amortizaciones": amortizaciones,
        "ebitda": ebitda, "ebit": ebit,
        "ingresosFinancieros": ing_financieros, "gastosFinancieros": gastos_financieros,
        "rai": rai, "impuesto": impuesto, "resultadoNeto": resultado_neto, "cashFlow": cash_flow,
        "margenBruto": pct(total_ingresos - aprovisionamientos, total_ingresos),
        "margenEBITDA": pct(ebitda, total_ingresos),
        "margenNeto": pct(resultado_neto, total_ingresos),
        # comparativa
        "totalIngresosAnt": ingresos_ant, "resultadoNetoAnt": resultado_ant,
        "varIngresos": pct(total_ingresos - ingresos_ant, ingresos_ant),
        "varResultado": pct(resultado_neto - resultado_ant, abs(resultado_ant)) if resultado_ant else 0.0,
        # balance
        "inmovIntangible": inmov_intangible, "inmovMaterial": inmov_material,
        "inversionesLP": inversiones_lp, "activoNoCorriente": activo_no_corriente,
        "existencias": existencias, "clientesSaldo": deudores, "tesoreria": tesoreria,
        "inversionesCP": inversiones_cp,
        "activoCorriente": activo_corriente, "totalActivo": total_activo,
        "capitalSocial": capital, "reservas": reservas, "subvenciones": subvenciones,
        "patrimonioNeto": patrimonio_neto, "deudasLP": deudas_lp,
        "proveedoresSaldo": proveedores, "deudasCP": deudas_cp,
        "pasivoCorriente": pasivo_corriente, "totalPasivo": total_pasivo,
        "recursosAjenos": recursos_ajenos, "fondoManiobra": fondo_maniobra,
        # ratios
        "liquidez": (activo_corriente / pasivo_corriente) if pasivo_corriente else 0.0,
        "acidTest": ((activo_corriente - existencias) / pasivo_corriente) if pasivo_corriente else 0.0,
        "endeudamiento": pct(recursos_ajenos, total_activo),
        "garantia": (total_activo / recursos_ajenos) if recursos_ajenos else 0.0,
        "roe": pct(resultado_neto, patrimonio_neto),
        "roa": pct(ebit, total_activo),
        # control de integridad
        "cuadre": {
            "activo": round(total_activo, 2),
            "pasivo_mas_pn": round(total_pasivo, 2),
            "diferencia": round(total_activo - total_pasivo, 2),
            "huerfanas": huerfanas,
            "huerfanas_total": huerfanas_total,
        },
    }


def calcular(por_anio: dict[int, list[Linea]], ctx: dict[str, Any]) -> dict[str, Any]:
    """Firma del contrato: recibe {ejercicio: líneas} y el contexto del informe."""
    year = int(ctx.get("year") or 0)
    return calcular_lineas(por_anio.get(year) or [], por_anio.get(year - 1) or [])


def series(lineas: list[Linea]) -> dict[str, Any]:
    """Series para las gráficas del dashboard: mensual y acumulada."""
    mensual = serie_mensual(lineas, P_INGRESOS_ACTIVIDAD, P_GASTOS_ACTIVIDAD)
    acumulado, acum_ing, acum_gas = 0.0, 0.0, 0.0
    for fila in mensual:
        acum_ing += fila["ingresos"]
        acum_gas += fila["gastos"]
        acumulado = acum_ing - acum_gas
        fila["resultado_acumulado"] = round(acumulado, 2)
        fila["ingresos_acumulados"] = round(acum_ing, 2)
        fila["gastos_acumulados"] = round(acum_gas, 2)
    return {"mensual": mensual}


GRUPOS_ASIGNADOS = (P_VENTAS + P_OTROS_INGRESOS + P_APROVISIONAMIENTOS + P_PERSONAL + P_OTROS_GASTOS
                    + P_AMORTIZACIONES + P_ING_FINANCIEROS + P_GASTOS_FINANCIEROS + P_IMPUESTO
                    + P_INMOV_INTANGIBLE + P_INMOV_MATERIAL + P_INVERSIONES_LP + P_EXISTENCIAS
                    + P_INVERSIONES_CP
                    + P_DEUDORES + P_TESORERIA + P_CAPITAL + P_RESERVAS + P_SUBVENCIONES
                    + P_DEUDAS_LP + P_PROVEEDORES + P_DEUDAS_CP)


def cuentas_huerfanas(lineas: list[Linea], *, nivel: int = 3, limite: int = 40) -> list[dict[str, Any]]:
    """Cuentas con saldo que no entran en ningún grupo del balance ni de la cuenta de resultados.

    Es la comprobación que explica por qué el balance no cuadra: sirve para completar los
    prefijos en vez de dejarse 240.000 € fuera.
    """
    s = saldos_por_cuenta(lineas)
    grupos: dict[str, dict[str, Any]] = {}
    for cuenta, saldo in s.items():
        if any(cuenta.startswith(p) for p in GRUPOS_ASIGNADOS):
            continue
        clave = cuenta[:nivel]
        g = grupos.setdefault(clave, {"cuenta": clave, "debe": 0.0, "haber": 0.0, "n": 0})
        g["debe"] += saldo.debe
        g["haber"] += saldo.haber
        g["n"] += saldo.n
    filas = [{"cuenta": g["cuenta"], "debe": round(g["debe"], 2), "haber": round(g["haber"], 2),
              "saldo": round(g["debe"] - g["haber"], 2), "n": g["n"]} for g in grupos.values()]
    return sorted(filas, key=lambda f: -abs(f["saldo"]))[:limite]


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    """Las cuatro tarjetas del inicio, más las que añadimos para el panel nuevo."""
    return {
        "totalIngresos": datos["totalIngresos"],
        "resultadoNeto": datos["resultadoNeto"],
        "fondoManiobra": datos["fondoManiobra"],
        "ebitda": datos["ebitda"],
        "ebit": datos["ebit"],
        "tesoreria": datos["tesoreria"],
        "patrimonioNeto": datos["patrimonioNeto"],
        "totalActivo": datos["totalActivo"],
        "margenEBITDA": datos["margenEBITDA"],
        "margenNeto": datos["margenNeto"],
        "liquidez": datos["liquidez"],
        "endeudamiento": datos["endeudamiento"],
        "roe": datos["roe"],
        "roa": datos["roa"],
        "varIngresos": datos["varIngresos"],
        "varResultado": datos["varResultado"],
    }


def informe_html(datos: dict[str, Any], ctx: dict[str, Any]) -> str:
    series_datos = datos.get("series") or series([])
    empresa = ctx.get("empresa") or datos.get("empresa") or ""
    year = int(ctx.get("year") or datos.get("year") or 0)
    mensual = series_datos["mensual"]
    categorias = [f["mes"] for f in mensual]
    kpi_items = [
        ("Ingresos", inf.importe(datos["totalIngresos"])),
        ("EBITDA", inf.importe(datos["ebitda"])),
        ("Resultado neto", inf.importe(datos["resultadoNeto"])),
        ("Fondo de maniobra", inf.importe(datos["fondoManiobra"])),
    ]

    filas_pyg = [
        ("Importe neto de la cifra de negocios", datos["ventas"], None),
        ("Otros ingresos de explotación", datos["otrosIngresos"], None),
        ("Aprovisionamientos", -datos["aprovisionamientos"], None),
        ("Gastos de personal", -datos["gastosPersonal"], None),
        ("Otros gastos de explotación", -datos["otrosGastosExplot"], None),
        ("Amortización del inmovilizado", -datos["amortizaciones"], None),
        ("Resultado de explotación (EBIT)", datos["ebit"], "total"),
        ("Ingresos financieros", datos["ingresosFinancieros"], None),
        ("Gastos financieros", -datos["gastosFinancieros"], None),
        ("Resultado antes de impuestos (RAI)", datos["rai"], "total"),
        ("Impuesto sobre sociedades", -datos["impuesto"], None),
        ("Resultado del ejercicio", datos["resultadoNeto"], "total"),
    ]
    filas_pyg_html = []
    for etiqueta, valor, tipo in filas_pyg:
        peso = "bold" if tipo == "total" else "normal"
        fondo = AZUL_FILA if tipo == "total" else ("#fff" if len(filas_pyg_html) % 2 == 0 else "#f9fbff")
        filas_pyg_html.append(
            f'<tr style="background:{fondo}">'
            f'<td style="padding:5px 8px;border-bottom:1px solid #eef2f8;font-weight:{peso}">{inf.esc(etiqueta)}</td>'
            f'<td style="padding:5px 8px;border-bottom:1px solid #eef2f8;text-align:right;font-weight:{peso}">'
            f'{inf.importe(valor, con_signo=(tipo == "total"))}</td></tr>'
        )
    tabla_pyg = (f'<table style="width:100%;border-collapse:collapse;font-size:12px">'
                 f'<thead><tr><th style="text-align:left;padding:6px 8px;border-bottom:2px solid {inf.AZUL};'
                 f'color:{inf.AZUL}">Cuenta de pérdidas y ganancias</th>'
                 f'<th style="text-align:right;padding:6px 8px;border-bottom:2px solid {inf.AZUL};'
                 f'color:{inf.AZUL}">Importe</th></tr></thead><tbody>{"".join(filas_pyg_html)}</tbody></table>')

    filas_balance = [
        ("Activo no corriente", datos["activoNoCorriente"]),
        ("Existencias", datos["existencias"]),
        ("Deudores comerciales", datos["clientesSaldo"]),
        ("Tesorería", datos["tesoreria"]),
        ("Activo corriente", datos["activoCorriente"]),
        ("TOTAL ACTIVO", datos["totalActivo"]),
        ("Patrimonio neto", datos["patrimonioNeto"]),
        ("Deudas a largo plazo", datos["deudasLP"]),
        ("Acreedores y otras deudas a corto", datos["pasivoCorriente"]),
        ("TOTAL PATRIMONIO NETO Y PASIVO", datos["totalPasivo"]),
    ]
    tabla_balance = inf.tabla(
        ["Balance de situación", f"Ejercicio {year}"],
        [[e, inf.importe(v)] for e, v in filas_balance],
        anchos=["62%", "38%"],
    )

    tabla_ratios = inf.tabla(
        ["Ratio", "Valor", "Lectura"],
        [
            ["Liquidez corriente", f'{num(datos["liquidez"])}',
             "Holgada" if datos["liquidez"] >= 1.5 else ("Justa" if datos["liquidez"] >= 1 else "Ajustada")],
            ["Prueba ácida", f'{num(datos["acidTest"])}',
             "Correcta" if datos["acidTest"] >= 1 else "Depende de existencias"],
            ["Endeudamiento", fmt_pct(datos["endeudamiento"]),
             "Alto" if datos["endeudamiento"] > 70 else "Contenido"],
            ["Garantía", num(datos["garantia"]), "Suficiente" if datos["garantia"] >= 1.5 else "Justa"],
            ["ROE", fmt_pct(datos["roe"]), "Rentabilidad sobre recursos propios"],
            ["ROA", fmt_pct(datos["roa"]), "Rentabilidad sobre activos"],
        ],
        alinear="right", primera_izquierda=True,
    )

    grafico = inf.barras_svg(
        categorias,
        [
            {"nombre": "Ingresos", "color": inf.AZUL, "valores": [f["ingresos"] for f in mensual]},
            {"nombre": "Gastos", "color": "#c98a2b", "valores": [f["gastos"] for f in mensual]},
        ],
        titulo="Ingresos y gastos por mes",
    )
    grafico_acum = inf.lineas_svg(
        categorias,
        [
            {"nombre": "Resultado acumulado", "color": inf.AZUL,
             "valores": [f["resultado_acumulado"] for f in mensual]},
        ],
        titulo="Resultado acumulado del ejercicio",
    )

    comparativa = inf.barras_svg(
        [f"Ejercicio {year - 1}", f"Ejercicio {year}"],
        [
            {"nombre": "Ingresos", "color": inf.AZUL,
             "valores": [datos["totalIngresosAnt"], datos["totalIngresos"]]},
            {"nombre": "Resultado neto", "color": inf.POSITIVO,
             "valores": [datos["resultadoNetoAnt"], datos["resultadoNeto"]]},
        ],
        alto=170, titulo="Comparativa con el ejercicio anterior",
    )

    aviso_cuadre = ""
    dif = datos["cuadre"]["diferencia"]
    if abs(dif) > 1:
        detalle_huerfanas = datos["cuadre"].get("huerfanas") or []
        lista = ", ".join(f'{h["cuenta"]} ({h["saldo"]:,.2f} €)'.replace(",", ".").replace(".", ",", 1)
                          for h in detalle_huerfanas[:6])
        aviso_cuadre = inf.aviso(
            f"El balance presenta una diferencia de {fmt(dif)} entre activo y patrimonio neto más pasivo."
            + (f" Cuentas fuera de los grupos previstos: {lista}." if lista else ""),
            tipo="alerta", titulo="Revisar cuadre del balance")
    elif datos["cuadre"].get("huerfanas"):
        nombres = ", ".join(h["cuenta"] for h in datos["cuadre"]["huerfanas"][:8])
        aviso_cuadre = inf.aviso(
            f"Hay cuentas fuera de los grupos previstos ({nombres}), aunque el balance cuadra al cierre.",
            tipo="info", titulo="Cuentas no clasificadas")

    cuerpo = (
        inf.kpis(kpi_items)
        + f'<div style="font-size:12px;color:#5b6b80;padding:2px 4px 6px">'
        f'Variación de ingresos respecto a {year - 1}: <b>{fmt_pct(datos["varIngresos"])}</b> · '
        f'Variación del resultado: <b>{fmt_pct(datos["varResultado"])}</b></div>'
        + inf.seccion("Cuenta de pérdidas y ganancias", tabla_pyg)
        + inf.seccion("Evolución mensual", grafico
                      + f'<div style="margin-top:10px">{grafico_acum}</div>')
        + inf.seccion(f"Comparativa con {year - 1}", comparativa)
        + inf.seccion("Balance de situación", tabla_balance + aviso_cuadre)
        + inf.seccion("Ratios", tabla_ratios)
    )
    return inf.envoltura(
        titulo="Balance y cuenta de pérdidas y ganancias",
        subtitulo=f"Ejercicio {year} · comparativa con {year - 1}",
        empresa=empresa, ejercicio=year, cuerpo=cuerpo,
        meta={"Datos": "ERP apiCON (ejercicio completo)"},
    )


__all__ = ["calcular", "calcular_lineas", "series", "metricas_dashboard", "informe_html",
           "cuentas_huerfanas"]
