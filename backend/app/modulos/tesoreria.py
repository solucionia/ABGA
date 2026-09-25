"""Módulo `tesoreria` — Tesorería y cobros (módulo nuevo, no venía del sistema anterior).

Todo sale de los apuntes del ERP: saldos por cuenta de tesorería, cobros y pagos pendientes
por tercero con su antigüedad, periodos medios de cobro y pago, y una previsión de tesorería
a tres meses construida con el flujo medio de los últimos meses del ejercicio.

Lo que NO hace: inventar fechas de vencimiento. El ERP no las trae en `/api/apuntes/`, así que
la antigüedad se cuenta desde la fecha del apunte y el informe lo dice expresamente.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .. import informes as inf
from ..ledger import (Linea, MESES, fecha_a_int, fmt, fmt_pct, mes_de, nombre_tercero, num,
                      por_mes, saldos_por_cuenta, suma_acreedor, suma_deudor)

NOMBRE = "tesoreria"
TITULO = "Tesorería y cobros"
INTERNO = False
DESPLAZAMIENTOS = [0]
PARAMETROS: dict[str, Any] = {
    "dias_alerta": 90,   # a partir de aquí un saldo pendiente se considera viejo
    "top_n": 12,         # terceros listados
}

P_TESORERIA = ["570", "571", "572", "573", "574", "575", "576", "577", "578", "579"]
P_COBRO = ["430", "431", "432", "433", "435", "436", "437", "440", "441", "443", "446", "449",
           "460", "461", "470", "471", "472", "473", "474"]
# 475, 476 y 477 son Hacienda y Seguridad Social ACREEDORAS: van en deudas, no en cobros
P_PAGO = ["400", "401", "402", "403", "405", "406", "407", "410", "411", "413", "415", "416",
          "419", "465", "466", "4750", "4751", "4752", "4758", "4759", "476", "477", "523", "525"]

TRAMOS = [("0-30 días", 0, 30), ("31-60 días", 31, 60), ("61-90 días", 61, 90), ("más de 90 días", 91, 99999)]


def _referencia(lineas: list[Linea]) -> date:
    """Fecha de referencia del informe: el último apunte del ejercicio (no «hoy»)."""
    fechas = [l.fecha for l in lineas if l.fecha]
    if not fechas:
        return date.today()
    f = max(fechas)
    try:
        return date(f // 10000, (f // 100) % 100, f % 100)
    except ValueError:
        return date.today()


def _pendientes(lineas: list[Linea], prefijos: list[str], ref: date) -> tuple[list[dict], dict]:
    """Saldos pendientes por tercero con su antigüedad, y reparto por tramos."""
    acumulado: dict[str, dict[str, Any]] = {}
    tramos = {t[0]: 0.0 for t in TRAMOS}
    for l in lineas:
        if not any(l.cuenta.startswith(p) for p in prefijos):
            continue
        saldo = l.debe - l.haber
        if not saldo:
            continue
        nombre = nombre_tercero(l.tercero, l.descripcion)
        reg = acumulado.setdefault(nombre, {"tercero": nombre, "saldo": 0.0, "lineas": 0,
                                            "fecha_mas_antigua": None, "importe_antiguo": 0.0})
        reg["saldo"] += saldo
        reg["lineas"] += 1
        f = fecha_a_int(l.fecha)
        if f:
            if reg["fecha_mas_antigua"] is None or f < reg["fecha_mas_antigua"]:
                reg["fecha_mas_antigua"] = f
            dias = (ref - date(f // 10000, (f // 100) % 100, f % 100)).days
            for etq, lo, hi in TRAMOS:
                if lo <= dias <= hi:
                    tramos[etq] += saldo
                    if dias >= 90:
                        reg["importe_antiguo"] += saldo
                    break
    filas = []
    for r in acumulado.values():
        f = r["fecha_mas_antigua"]
        r["dias"] = (ref - date(f // 10000, (f // 100) % 100, f % 100)).days if f else 0
        r["fecha_texto"] = f"{f % 100:02d}/{(f // 100) % 100:02d}/{f // 10000}" if f else "—"
        filas.append(r)
    return sorted(filas, key=lambda r: -abs(r["saldo"])), tramos


def calcular(por_anio: dict[int, list[Linea]], ctx: dict[str, Any]) -> dict[str, Any]:
    year = int(ctx.get("year") or 0)
    dias_alerta = int(ctx.get("dias_alerta") or 90)
    top_n = int(ctx.get("top_n") or 12)
    lineas = por_anio.get(year) or []
    ref = _referencia(lineas)

    # ---------- tesorería ----------
    saldos = saldos_por_cuenta(lineas)
    cuentas = []
    for cuenta, s in saldos.items():
        if any(cuenta.startswith(p) for p in P_TESORERIA) and (s.debe or s.haber):
            cuentas.append({"cuenta": cuenta, "saldo": round(s.deudor, 2), "n": s.n})
    cuentas.sort(key=lambda c: -abs(c["saldo"]))
    tesoreria_total = round(sum(c["saldo"] for c in cuentas), 2)

    movimiento_mes = {m: 0.0 for m in range(1, 13)}
    for l in lineas:
        if any(l.cuenta.startswith(p) for p in P_TESORERIA):
            m = mes_de(l.fecha)
            if 1 <= m <= 12:
                movimiento_mes[m] += l.debe - l.haber
    mensual, acumulado = [], 0.0
    for m in range(1, 13):
        acumulado += movimiento_mes[m]
        mensual.append({"mes": MESES[m - 1], "flujo": round(movimiento_mes[m], 2),
                        "saldo": round(acumulado, 2)})

    # ---------- cobros y pagos pendientes ----------
    cobros, tramos_cobro = _pendientes(lineas, P_COBRO, ref)
    pagos, tramos_pago = _pendientes(lineas, P_PAGO, ref)
    cobros = [c for c in cobros if c["saldo"] > 0.5]
    pagos = [p for p in pagos if p["saldo"] > 0.5]

    # ---------- periodos medios ----------
    ingresos = suma_acreedor(saldos, [p for p in ("700", "701", "702", "703", "704", "705",
                                                  "706", "708", "709", "74", "75", "778")])
    compras = suma_deudor(saldos, [p for p in ("600", "601", "602", "607", "608", "609", "610",
                                               "611", "612", "62", "63")])
    saldo_clientes = round(sum(c["saldo"] for c in cobros), 2)
    saldo_proveedores = round(sum(p["saldo"] for p in pagos), 2)
    pmc = round(saldo_clientes / ingresos * 365) if ingresos else None
    pmp = round(saldo_proveedores / compras * 365) if compras else None

    # ---------- previsión a 3 meses con el flujo medio observado ----------
    meses_con_datos = [m["flujo"] for m in mensual if m["flujo"]]
    ultimos = [m["flujo"] for m in mensual[-3:] if m["flujo"]]
    flujo_medio = round(sum(ultimos) / len(ultimos), 2) if ultimos else 0.0
    prevision = []
    saldo_prev = tesoreria_total
    for i in range(1, 4):
        saldo_prev += flujo_medio
        prevision.append({"mes": f"mes +{i}", "flujo": flujo_medio, "saldo": round(saldo_prev, 2)})

    # ---------- avisos ----------
    avisos: list[str] = []
    if not cuentas:
        avisos.append("Los apuntes del ejercicio no traen movimientos en las cuentas de tesorería (57x).")
    if tesoreria_total < 0:
        avisos.append(f"La tesorería cierra en negativo ({fmt(tesoreria_total)}): hay descubierto en alguna cuenta.")
    viejos = [c for c in cobros if c["dias"] >= dias_alerta]
    if viejos:
        importe_viejo = sum(c["saldo"] for c in viejos)
        avisos.append(f"{len(viejos)} clientes tienen saldos pendientes con más de {dias_alerta} días "
                      f"de antigüedad, por {fmt(importe_viejo)} en total.")
    if saldo_clientes and cobros and cobros[0]["saldo"] / saldo_clientes > 0.35:
        avisos.append(f"Concentración de riesgo: {cobros[0]['tercero']} representa "
                      f"{fmt_pct(cobros[0]['saldo'] / saldo_clientes * 100)} del saldo pendiente de cobro.")
    if pmc and pmc > 90:
        avisos.append(f"El periodo medio de cobro estimado es de {pmc} días.")
    avisos.append("Las fechas de vencimiento no vienen en los apuntes del ERP: la antigüedad se cuenta "
                  "desde la fecha de cada apunte, no desde su vencimiento real.")

    return {
        "year": year, "fecha_referencia": ref.isoformat(),
        "tesoreria_total": tesoreria_total, "cuentas": cuentas,
        "mensual": mensual, "prevision": prevision, "flujo_medio": flujo_medio,
        "cobros": cobros, "pagos": pagos,
        "tramos_cobro": {k: round(v, 2) for k, v in tramos_cobro.items()},
        "tramos_pago": {k: round(v, 2) for k, v in tramos_pago.items()},
        "saldo_clientes": saldo_clientes, "saldo_proveedores": saldo_proveedores,
        "pmc": pmc, "pmp": pmp, "ingresos": round(ingresos, 2), "compras": round(compras, 2),
        "top_n": top_n, "dias_alerta": dias_alerta, "avisos": avisos,
    }


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    return {
        "tesoreria_total": datos.get("tesoreria_total"),
        "saldo_clientes": datos.get("saldo_clientes"),
        "saldo_proveedores": datos.get("saldo_proveedores"),
        "pmc": datos.get("pmc"),
        "pmp": datos.get("pmp"),
    }


def informe_html(datos: dict[str, Any], ctx: dict[str, Any]) -> str:
    year = datos["year"]
    categorias = [m["mes"] for m in datos["mensual"]]

    kpis_items = [
        ("Tesorería", inf.importe(datos["tesoreria_total"])),
        ("Pendiente de cobro", inf.importe(datos["saldo_clientes"])),
        ("Pendiente de pago", inf.importe(datos["saldo_proveedores"])),
        ("Periodo medio de cobro", f'{num(datos["pmc"])} días' if datos["pmc"] else "—"),
    ]

    tabla_cuentas = inf.tabla(
        ["Cuenta de tesorería", "Saldo", "Apuntes"],
        [[c["cuenta"], inf.importe(c["saldo"]), str(c["n"])] for c in datos["cuentas"]] or
        [["Sin movimientos en cuentas 57x", "—", "0"]],
        totales=["Total", inf.importe(datos["tesoreria_total"]), ""],
        anchos=["52%", "28%", "20%"],
    )

    grafico_saldo = inf.lineas_svg(categorias, [
        {"nombre": "Saldo de tesorería", "color": inf.AZUL, "valores": [m["saldo"] for m in datos["mensual"]]},
    ], titulo="Evolución del saldo de tesorería")
    grafico_flujo = inf.barras_svg(categorias, [
        {"nombre": "Flujo del mes", "color": inf.AZUL, "valores": [m["flujo"] for m in datos["mensual"]]},
    ], titulo="Entradas menos salidas de tesorería, por mes")

    etiquetas_tramos = [t[0] for t in TRAMOS]
    grafico_tramos = inf.barras_svg(etiquetas_tramos, [
        {"nombre": "Cobros pendientes", "color": inf.AZUL,
         "valores": [datos["tramos_cobro"].get(e, 0) for e in etiquetas_tramos]},
        {"nombre": "Pagos pendientes", "color": "#c98a2b",
         "valores": [datos["tramos_pago"].get(e, 0) for e in etiquetas_tramos]},
    ], alto=180, titulo="Antigüedad de los saldos pendientes")

    filas_cobros = []
    for c in datos["cobros"][: datos["top_n"]]:
        viejo = c["dias"] >= int(datos.get("dias_alerta") or 90)
        filas_cobros.append([
            c["tercero"][:40], inf.importe(c["saldo"]), str(c["dias"]), c["fecha_texto"],
            (f'<span style="color:{inf.NEGATIVO};font-weight:bold">revisar</span>' if viejo else "—"),
        ])
    tabla_cobros = inf.tabla(
        ["Cliente", "Pendiente", "Días", "Apunte más antiguo", "Estado"],
        filas_cobros or [["Sin saldos pendientes de cobro", "—", "—", "—", "—"]],
        anchos=["36%", "20%", "10%", "20%", "14%"],
    )

    tabla_pagos = inf.tabla(
        ["Proveedor", "Pendiente", "Días", "Apunte más antiguo"],
        [[p["tercero"][:40], inf.importe(p["saldo"]), str(p["dias"]), p["fecha_texto"]]
         for p in datos["pagos"][: datos["top_n"]]] or [["Sin saldos pendientes de pago", "—", "—", "—"]],
        anchos=["44%", "22%", "12%", "22%"],
    )

    tabla_periodos = inf.tabla(
        ["Indicador", "Valor", "Cómo se calcula"],
        [
            ["Periodo medio de cobro", f'{num(datos["pmc"])} días' if datos["pmc"] else "—",
             f'saldo de clientes / ingresos del ejercicio × 365 (clientes {fmt(datos["saldo_clientes"])}, '
             f'ingresos {fmt(datos["ingresos"])})'],
            ["Periodo medio de pago", f'{num(datos["pmp"])} días' if datos["pmp"] else "—",
             f'saldo de proveedores / compras y gastos × 365 (proveedores {fmt(datos["saldo_proveedores"])}, '
             f'compras {fmt(datos["compras"])})'],
        ], alinear="right", primera_izquierda=True, anchos=["24%", "14%", "62%"],
    )

    tabla_prevision = inf.tabla(
        ["Escenario", "Flujo mensual estimado", "Saldo previsto"],
        [["Situación actual", "—", inf.importe(datos["tesoreria_total"])]] +
        [[p["mes"], inf.importe(p["flujo"]), inf.importe(p["saldo"])] for p in datos["prevision"]],
        anchos=["34%", "33%", "33%"],
    )

    cuerpo = (
        inf.kpis(kpis_items)
        + "".join(inf.aviso(a, tipo="info" if "vencimiento" in a else "alerta") for a in datos["avisos"])
        + inf.seccion("Situación de tesorería", tabla_cuentas)
        + inf.seccion("Evolución durante el ejercicio", grafico_saldo + f'<div style="margin-top:10px">{grafico_flujo}</div>')
        + inf.seccion("Antigüedad de los saldos pendientes",
                      grafico_tramos, nota="Importes pendientes agrupados por antigüedad del apunte.")
        + inf.seccion("Principales clientes con saldo pendiente", tabla_cobros)
        + inf.seccion("Principales proveedores con saldo pendiente", tabla_pagos)
        + inf.seccion("Periodos medios", tabla_periodos)
        + inf.seccion("Previsión de tesorería a tres meses", tabla_prevision,
                      nota=f"Proyección con el flujo medio de los últimos meses del ejercicio "
                           f"({fmt(datos['flujo_medio'])} al mes). Es una extrapolación, no una previsión "
                           f"de cobros comprometidos.")
    )
    return inf.envoltura(
        titulo="Tesorería y cobros",
        subtitulo=f"Ejercicio {year} · situación a {datos['fecha_referencia']}",
        empresa=ctx.get("empresa") or "", ejercicio=year, cuerpo=cuerpo,
        meta={"Referencia": datos["fecha_referencia"]},
    )
