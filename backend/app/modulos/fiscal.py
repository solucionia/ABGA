"""Módulo `fiscal` — REQ-06 Alertas fiscales (IVA, retenciones y pagos fraccionados).

Portado del nodo Code «Calcular Situación Fiscal» del workflow REQ-06 de n8n. El original
recibía del nodo `Guardar Token` (empresa, ejercicio, trimestre, fechaLimite, modelos) y el
volcado de `/api/apuntes/`, y devolvía todo **ya formateado como texto**. Aquí se devuelven
**números** y el HTML lo maqueta `app/informes.py`, según el contrato de módulos.

Qué se conserva del original:

- IVA repercutido = Σ(Haber−Debe) de las cuentas 477 · IVA soportado = Σ(Debe−Haber) de 472.
- Retenciones de IRPF = Σ(Haber−Debe) de 4751.
- Pago fraccionado del IS: base estimada = max(0, ingresos 70x−709 gastos 60x-68x) y 18 % sobre
  ella; exigible en el 1T (plazo de abril) y en el 3T (plazo de octubre), como en el original.
- Obligaciones del trimestre = IVA a ingresar + retenciones + 202 (si aplica), con los saldos
  contrarios recortados a cero **sólo** en ese total, igual que el `Math.max(0, …)` original.
- Alertas ALTA (>10.000 € de IVA), MEDIA (>3.000 €) e INFO, y su nivel global.

Diferencias deliberadas (documentadas para que nadie las «arregle» sin querer):

1. **El desglose trimestral usa `por_trimestre()` del motor contable**, no cuatro filtros de
   fecha repetidos: mismo resultado, un solo recorrido y fecha ya normalizada a entero.
2. **`trimestre` es un parámetro de verdad.** El webhook del original lo recibía y el nodo
   reventaba si faltaba (`indexOf(...) = -1` → `undefined`); aquí, sin valor, se usa el
   trimestre natural de la fecha de ejecución y se admite `3`, `"3"`, `"Q3"` o `"3T"`.
3. **Los vencimientos viven en el módulo**, no en `tokens.fechaLimite` (que llegaba ya calculado
   desde el portal). Mod. 303 e IRPF (111) trimestrales al día 20 de abril/julio/octubre y de
   enero (el del 4T cae en el año siguiente); mod. 202 al 20 de abril/octubre y, como
   recordatorio, al 20 de diciembre (ese último sólo obliga a ejercicios no naturales, así que
   se muestra pero no suma obligación).
4. **La base del 202 es la del ejercicio completo**, no la del trimestre: es lo que hacía el
   original al estimar el resultado, y el informe lo dice en vez de disimularlo.
5. **Los signos contrarios se enseñan.** Si el IVA soportado supera al repercutido, el 303 sale
   a compensar/devolver y el informe lo destaca en lugar de mostrar un cero mudo.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .. import informes as inf
from ..ledger import (MESES_LARGOS, Linea, comprobar_cuadre, fmt, fmt_pct, por_trimestre,
                      saldos_por_cuenta, suma_acreedor, suma_deudor)

NOMBRE = "fiscal"
TITULO = "Alertas fiscales"
INTERNO = False
DESPLAZAMIENTOS = [0]
# `trimestre`: None = trimestre natural del día de la ejecución; admite 1-4, "1"-"4", "Q1"-"Q4", "1T"-"4T".
PARAMETROS: dict[str, Any] = {"trimestre": None, "email": ""}

PORCENTAJE_202 = 0.18
DIA_LIMITE = 20
TRIMESTRE_PERIODO = ["enero–marzo", "abril–junio", "julio–septiembre", "octubre–diciembre"]

# --- prefijos PGC del original REQ-06 (sin solapes entre ellos) ---
P_IVA_REPERCUTIDO = ["477"]
P_IVA_SOPORTADO = ["472"]
P_RETENCIONES_IRPF = ["4751"]
P_BASE_INGRESOS = ["700", "701", "702", "703", "704", "705", "706", "708", "709"]
P_BASE_GASTOS = ["600", "601", "602", "620", "621", "622", "623", "624", "625", "626", "627",
                 "628", "629", "640", "641", "642", "660", "661", "662", "680", "681", "682"]

# Plazos (mes, día) según el trimestre que se declara. El mes de enero pertenece al año siguiente.
PLAZO_303 = {1: (4, DIA_LIMITE), 2: (7, DIA_LIMITE), 3: (10, DIA_LIMITE), 4: (1, DIA_LIMITE)}
PLAZO_111 = {1: (4, DIA_LIMITE), 2: (7, DIA_LIMITE), 3: (10, DIA_LIMITE), 4: (1, DIA_LIMITE)}
PLAZO_202 = {1: (4, DIA_LIMITE), 3: (10, DIA_LIMITE)}   # 1T → abril · 3T → octubre, como REQ-06
PLAZO_202_DICIEMBRE = (12, DIA_LIMITE)                  # recordatorio: sólo ejercicio no natural

NIVELES = {"ALTA": ("error", "ALTA"), "MEDIA": ("alerta", "MEDIA"), "INFO": ("info", "INFO")}


# ---------- utilidades ----------

def _r(x: Any) -> float:
    """Los números se devuelven siempre a dos decimales (contrato: números, no texto)."""
    try:
        return round(float(x or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def trimestre_natural(hoy: date | None = None) -> int:
    hoy = hoy or date.today()
    return (hoy.month - 1) // 3 + 1


def normalizar_trimestre(valor: Any) -> tuple[int, str]:
    """Devuelve (1..4, aviso). Sin valor válido se cae al trimestre natural, nunca se lanza."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return trimestre_natural(), ""
    if isinstance(valor, bool):  # bool es subclase de int: fuera antes de mirar ints
        return trimestre_natural(), f"El trimestre «{valor}» no es válido; se usa el natural."
    if isinstance(valor, int) and 1 <= valor <= 4:
        return valor, ""
    t = str(valor).strip().upper()
    if len(t) > 1 and t[0] == "Q" and t[1:].isdigit():
        t = t[1:]
    elif len(t) > 1 and t[-1] == "T" and t[:-1].isdigit():
        t = t[:-1]
    if t.isdigit() and 1 <= int(t) <= 4:
        return int(t), ""
    natural = trimestre_natural()
    return natural, (f"El trimestre «{valor}» no se reconoce (se espera 1-4, «Q1» o «1T»); "
                     f"se usa el trimestre natural, el {natural}T.")


def fecha_limite(year: int, mes: int, dia: int = DIA_LIMITE) -> dict[str, Any]:
    """Plazo de presentación: el del mes de enero pertenece al ejercicio siguiente."""
    anio = year + 1 if mes == 1 else year
    return {
        "anio": anio, "mes": mes, "dia": dia,
        "iso": f"{anio:04d}-{mes:02d}-{dia:02d}",
        "humano": f"{dia} de {MESES_LARGOS[mes - 1]} de {anio}",
    }


def vencimientos(trimestre: int, year: int) -> list[dict[str, Any]]:
    """Calendario de las obligaciones que caen en ese trimestre, con su plazo real."""
    filas: list[dict[str, Any]] = []
    mes, dia = PLAZO_303[trimestre]
    filas.append({"modelo": "303", "concepto": f"IVA — {trimestre}T {year}",
                  "aplica": True, "nota": "", **fecha_limite(year, mes, dia)})
    mes, dia = PLAZO_111[trimestre]
    filas.append({"modelo": "111", "concepto": f"Retenciones IRPF — {trimestre}T {year}",
                  "aplica": True, "nota": "", **fecha_limite(year, mes, dia)})
    if trimestre in PLAZO_202:
        mes, dia = PLAZO_202[trimestre]
        filas.append({"modelo": "202", "concepto": f"Pago fraccionado IS — {trimestre}T {year}",
                      "aplica": True, "nota": "", **fecha_limite(year, mes, dia)})
    else:
        mes, dia = PLAZO_202_DICIEMBRE
        filas.append({"modelo": "202", "concepto": "Pago fraccionado IS — diciembre",
                      "aplica": False, "nota": "Sólo obliga a ejercicios no naturales",
                      **fecha_limite(year, mes, dia)})
    return filas


def estado_plazo(fila: dict[str, Any], hoy: date | None = None) -> str:
    """Texto del estado del plazo: cuánto queda o cuánto hace que pasó."""
    hoy = hoy or date.today()
    try:
        limite = date(int(fila["anio"]), int(fila["mes"]), int(fila["dia"]))
    except (KeyError, TypeError, ValueError):
        return ""
    dias = (limite - hoy).days
    if dias > 0:
        return f"Faltan {dias} días"
    if dias == 0:
        return "Vence hoy"
    return f"Vencido hace {abs(dias)} días"


# ---------- cálculo ----------

def calcular(por_anio: dict[int, list[Linea]], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Situación fiscal del ejercicio y del trimestre pedido, todo en números.

    Devuelve los agregados aplanados (contrato de módulos) y el mismo bloque bajo
    `datos["data"]`, para que el JSON del portal exponga `data.totalObligaciones` numérico.
    """
    ctx = dict(ctx or {})
    avisos: list[str] = []

    if isinstance(por_anio, (list, tuple)):  # tolera que le pasen las líneas directamente
        lineas = list(por_anio)
        year = int(ctx.get("year") or 0)
    else:
        year = int(ctx.get("year") or 0) or (max(por_anio) if por_anio else 0)
        lineas = list(por_anio.get(year) or [])

    if not lineas and isinstance(por_anio, dict) and por_anio:
        year = max(por_anio)
        lineas = list(por_anio[year] or [])
        avisos.append(f"No llegaron apuntes del ejercicio pedido; se calcula con el {year} disponible.")
    if not lineas:
        avisos.append(f"No hay apuntes cargados del ejercicio {year}: todas las cifras salen a cero.")

    trimestre, aviso_trimestre = normalizar_trimestre(ctx.get("trimestre"))
    if aviso_trimestre:
        avisos.append(aviso_trimestre)

    # ---------- ejercicio completo ----------
    s = saldos_por_cuenta(lineas)
    iva_rep = suma_acreedor(s, P_IVA_REPERCUTIDO, recortar=False)
    iva_sop = suma_deudor(s, P_IVA_SOPORTADO, recortar=False)
    saldo_iva = iva_rep - iva_sop
    iva_a_ingresar = max(0.0, saldo_iva)
    iva_a_devolver = abs(min(0.0, saldo_iva))
    retenciones = suma_acreedor(s, P_RETENCIONES_IRPF, recortar=False)
    # el original sólo miraba la 4751: se comprueba el resto de 475x para no perder concepto
    otras_retenciones = sum(x.acreedor for c, x in s.items()
                            if c.startswith("475") and not c.startswith(P_RETENCIONES_IRPF[0]))

    base_ingresos = suma_acreedor(s, P_BASE_INGRESOS, recortar=False)
    base_gastos = suma_deudor(s, P_BASE_GASTOS, recortar=False)
    base_is = max(0.0, base_ingresos - base_gastos)
    pago_202 = base_is * PORCENTAJE_202

    # ---------- desglose por trimestre (por_trimestre del motor contable) ----------
    por_t = por_trimestre(lineas)
    detalle: list[dict[str, Any]] = []
    for q in (1, 2, 3, 4):
        del_trimestre = por_t.get(q, [])
        sq = saldos_por_cuenta(del_trimestre)
        rep = suma_acreedor(sq, P_IVA_REPERCUTIDO, recortar=False)
        sop = suma_deudor(sq, P_IVA_SOPORTADO, recortar=False)
        saldo = rep - sop
        ret = suma_acreedor(sq, P_RETENCIONES_IRPF, recortar=False)
        detalle.append({
            "trimestre": q, "periodo": TRIMESTRE_PERIODO[q - 1], "nLineas": len(del_trimestre),
            "repercutido": _r(rep), "soportado": _r(sop), "saldo": _r(saldo),
            "ivaAIngresar": _r(max(0.0, saldo)), "ivaADevolver": _r(abs(min(0.0, saldo))),
            "retenciones": _r(ret),
        })
    actual = next(d for d in detalle if d["trimestre"] == trimestre)

    # ---------- obligaciones del trimestre (mismo total que el original) ----------
    aplica_202 = trimestre in PLAZO_202
    obligacion_iva = actual["ivaAIngresar"]
    obligacion_retenciones = max(0.0, actual["retenciones"])
    obligacion_202 = pago_202 if aplica_202 else 0.0
    total_obligaciones = obligacion_iva + obligacion_retenciones + obligacion_202

    venc = vencimientos(trimestre, year)
    plazo_303 = next(v for v in venc if v["modelo"] == "303")

    # ---------- alertas (portadas de REQ-06) ----------
    alertas: list[dict[str, Any]] = []
    if obligacion_iva > 10000:
        alertas.append({"nivel": "ALTA", "modelo": "303",
                        "mensaje": f"IVA a ingresar este trimestre: {fmt(obligacion_iva)} — "
                                   f"vence el {plazo_303['humano']}"})
    elif obligacion_iva > 3000:
        alertas.append({"nivel": "MEDIA", "modelo": "303",
                        "mensaje": f"IVA a ingresar: {fmt(obligacion_iva)} — presentar antes del "
                                   f"{plazo_303['humano']}"})
    elif obligacion_iva > 0:
        alertas.append({"nivel": "INFO", "modelo": "303",
                        "mensaje": f"IVA a ingresar: {fmt(obligacion_iva)}"})
    elif iva_a_devolver > 0:
        alertas.append({"nivel": "INFO", "modelo": "303",
                        "mensaje": f"IVA acumulado a devolver en el ejercicio: {fmt(iva_a_devolver)} "
                                   "— valorar solicitud"})
    if obligacion_retenciones > 0:
        alertas.append({"nivel": "INFO", "modelo": "111",
                        "mensaje": f"Retenciones IRPF {trimestre}T: {fmt(obligacion_retenciones)} "
                                   "— Modelo 111"})
    if aplica_202 and pago_202 > 1000:
        alertas.append({"nivel": "INFO", "modelo": "202",
                        "mensaje": f"Pago fraccionado IS estimado: {fmt(pago_202)} — Modelo 202"})
    nivel_global = ("ALTA" if any(a["nivel"] == "ALTA" for a in alertas)
                    else "MEDIA" if any(a["nivel"] == "MEDIA" for a in alertas) else "INFO")

    # ---------- avisos de cálculo (los pinta el informe y los devuelve el servicio) ----------
    cuadre = comprobar_cuadre(lineas)
    if lineas and abs(cuadre["descuadre"]) > 1:
        avisos.append(f"El libro no cuadra: ΣDebe − ΣHaber = {fmt(cuadre['descuadre'])} "
                      f"({cuadre['n_lineas']} líneas). Revisar asientos de regularización.")
    sin_fecha = len(por_t.get(0, []))
    if sin_fecha:
        avisos.append(f"{sin_fecha} líneas del ejercicio no traen fecha: quedan fuera del desglose "
                      "por trimestre.")
    if not actual["nLineas"]:
        avisos.append(f"El {trimestre}T no tiene apuntes: sus cifras salen a cero.")
    if saldo_iva < 0 and not obligacion_iva:
        avisos.append("El IVA soportado (472) supera al repercutido (477) en el ejercicio, así que el "
                      "303 sale a compensar o a devolver y no a ingresar. Comprobar si la sociedad está "
                      "en devolución mensual o si hay operaciones intracomunitarias.")
    if otras_retenciones:
        avisos.append(f"Hay {fmt(otras_retenciones)} en cuentas 475x distintas de la 4751: el workflow "
                      "original no las miraba, conviene identificar el concepto.")
    if aplica_202:
        avisos.append("La cuota del mod. 202 se estima sobre la base del ejercicio completo (18 %), no "
                      "sobre el trimestre: es la fórmula del workflow original.")

    numeros: dict[str, Any] = {
        "year": year, "trimestre": trimestre, "periodo": TRIMESTRE_PERIODO[trimestre - 1],
        # IVA del ejercicio
        "ivaRepercutido": _r(iva_rep), "ivaSoportado": _r(iva_sop), "saldoIVA": _r(saldo_iva),
        "ivaAIngresar": _r(iva_a_ingresar), "ivaADevolver": _r(iva_a_devolver),
        # IVA por trimestre
        "ivaTrimestreDetalle": detalle, "ivaTrimestreActual": dict(actual),
        # retenciones
        "retencionesIRPF": _r(retenciones), "retencionesOtras": _r(otras_retenciones),
        "retencionesTrimestre": _r(actual["retenciones"]),
        # pago fraccionado
        "baseIngresos": _r(base_ingresos), "baseGastos": _r(base_gastos), "baseIS": _r(base_is),
        "porcentajeIS": PORCENTAJE_202, "pagoFraccionadoIS": _r(pago_202),
        "aplicaModelo202": aplica_202,
        # obligaciones del trimestre
        "obligacionIVA": _r(obligacion_iva), "obligacionRetenciones": _r(obligacion_retenciones),
        "obligacion202": _r(obligacion_202), "totalObligaciones": _r(total_obligaciones),
        # plazos, alertas y control
        "vencimientos": venc, "fechaLimite": plazo_303["iso"],
        "fechaLimiteTexto": plazo_303["humano"],
        "alertas": alertas, "nivelGlobal": nivel_global,
        "nLineas": len(lineas), "cuadre": cuadre,
    }
    datos = dict(numeros)
    datos["data"] = dict(numeros)  # mismo bloque: el portal lee data.totalObligaciones
    datos["avisos"] = avisos
    return datos


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    """KPIs del panel: lo que hay que pagar este trimestre y con qué nivel de alerta."""
    return {
        "totalObligaciones": datos.get("totalObligaciones", 0.0),
        "obligacionIVA": datos.get("obligacionIVA", 0.0),
        "obligacionRetenciones": datos.get("obligacionRetenciones", 0.0),
        "obligacion202": datos.get("obligacion202", 0.0),
        "saldoIVA": datos.get("saldoIVA", 0.0),
        "ivaADevolver": datos.get("ivaADevolver", 0.0),
        "retencionesIRPF": datos.get("retencionesIRPF", 0.0),
        "pagoFraccionadoIS": datos.get("pagoFraccionadoIS", 0.0),
        "trimestre": datos.get("trimestre"),
        "fechaLimite": datos.get("fechaLimiteTexto", ""),
        "nivelGlobal": datos.get("nivelGlobal", ""),
        "nAlertas": len(datos.get("alertas") or []),
    }


# ---------- informe ----------

def informe_html(datos: dict[str, Any], ctx: dict[str, Any] | None = None, *,
                 empresa: str | None = None, year: int | None = None) -> str:
    """Informe HTML (empieza por `<div`), Arial 13 px y CSS inline: lo pinta el portal tal cual."""
    ctx = dict(ctx or {})
    if empresa:
        ctx.setdefault("empresa", empresa)
    if year:
        ctx.setdefault("year", year)
    year = int(datos.get("year") or ctx.get("year") or 0)
    trimestre = int(datos.get("trimestre") or 1)
    nombre_empresa = ctx.get("empresa") or ""
    detalle = datos.get("ivaTrimestreDetalle") or []
    actual = datos.get("ivaTrimestreActual") or {}
    venc = datos.get("vencimientos") or []

    # 1 · resumen
    periodo = datos.get("periodo") or TRIMESTRE_PERIODO[trimestre - 1]
    plazo_303 = next((v for v in venc if v["modelo"] == "303"), {})
    kpis = inf.kpis([
        ("IVA repercutido (477)", inf.importe(datos.get("ivaRepercutido", 0.0))),
        ("IVA soportado (472)", inf.importe(datos.get("ivaSoportado", 0.0))),
        (f"Saldo IVA {trimestre}T", inf.importe(actual.get("saldo", 0.0), con_signo=True)),
        ("Total obligaciones del trimestre", inf.importe(datos.get("totalObligaciones", 0.0))),
    ])
    cabecera_trimestre = (
        f'<div style="font-size:12px;color:#5b6b80;padding:2px 4px 6px">'
        f'Trimestre analizado: <b>{trimestre}T de {year}</b> ({inf.esc(periodo)}) · '
        f'plazo del mod. 303: <b>{inf.esc(plazo_303.get("humano", "—"))}</b>'
        + (f' ({inf.esc(estado_plazo(plazo_303))})' if plazo_303 else "")
        + f' · nivel de alerta: <b>{inf.esc(datos.get("nivelGlobal", "INFO"))}</b></div>'
    )

    # 2 · obligaciones del trimestre, con su fecha límite
    importe_modelo = {"303": datos.get("obligacionIVA", 0.0),
                      "111": datos.get("obligacionRetenciones", 0.0),
                      "202": datos.get("obligacion202", 0.0)}
    filas_venc = []
    for v in venc:
        if v["aplica"]:
            importe_html = inf.importe(importe_modelo.get(v["modelo"], 0.0))
            estado = estado_plazo(v)
        else:
            importe_html = '<span style="color:#8a95a6">No aplica</span>'
            estado = v.get("nota", "")
        filas_venc.append([f"{v['modelo']}", v["concepto"], importe_html,
                           f'{v["humano"]}<div style="font-size:10.5px;color:#8a95a6">'
                           f'{inf.esc(v["iso"])}</div>', estado])
    tabla_venc = inf.tabla(["Modelo", "Concepto", "Importe", "Fecha límite", "Estado"],
                           filas_venc,
                           totales=["", "Total obligaciones del trimestre",
                                    inf.importe(datos.get("totalObligaciones", 0.0)), "", ""],
                           anchos=["9%", "38%", "18%", "22%", "13%"])
    nota_venc = (f'El mod. 303 y el mod. 111 (retenciones) se presentan los días {DIA_LIMITE} de '
                 f'abril, julio, octubre y enero. El mod. 202 en abril y octubre; el plazo de '
                 f'diciembre sólo obliga a ejercicios no naturales. Las cuotas vencidas no '
                 f'desaparecen: se quedan pendientes de presentar.')

    # 3 · IVA por trimestre
    filas_iva = []
    for d in detalle:
        saldo = d["saldo"]
        lectura = ("A ingresar" if saldo > 0 else "A devolver" if saldo < 0 else "Cero")
        color = inf.NEGATIVO if saldo > 0 else (inf.POSITIVO if saldo < 0 else "#666")
        filas_iva.append([f'{d["trimestre"]}T <span style="color:#8a95a6">({inf.esc(d["periodo"])})</span>',
                          str(d["nLineas"]), inf.importe(d["repercutido"]),
                          inf.importe(d["soportado"]), inf.importe(saldo, con_signo=True),
                          f'<span style="color:{color};font-weight:bold;white-space:nowrap">{lectura}</span>'])
    filas_iva.append(["TOTAL EJERCICIO", str(datos.get("nLineas", 0)),
                      inf.importe(datos.get("ivaRepercutido", 0.0)),
                      inf.importe(datos.get("ivaSoportado", 0.0)),
                      inf.importe(datos.get("saldoIVA", 0.0), con_signo=True),
                      '<span style="font-weight:bold;white-space:nowrap">'
                      + ("A ingresar" if datos.get("saldoIVA", 0) > 0 else
                         "A devolver" if datos.get("saldoIVA", 0) < 0 else "Cero")
                      + "</span>"])
    tabla_iva = inf.tabla(["Trimestre", "Líneas", "IVA repercutido (477)", "IVA soportado (472)",
                           "Saldo", "Resultado"], filas_iva,
                          anchos=["20%", "8%", "18%", "18%", "18%", "18%"])
    grafico_iva = inf.barras_svg(
        [f'{d["trimestre"]}T' for d in detalle],
        [{"nombre": "Repercutido (477)", "color": inf.AZUL, "valores": [d["repercutido"] for d in detalle]},
         {"nombre": "Soportado (472)", "color": "#c98a2b", "valores": [d["soportado"] for d in detalle]}],
        titulo="IVA repercutido y soportado por trimestre")

    # 4 · retenciones
    tabla_ret = inf.tabla(
        ["Trimestre", "Retenciones IRPF (4751)", "Nivel"],
        [[f'{d["trimestre"]}T', inf.importe(d["retenciones"]),
          f'<span style="font-weight:bold">{"Trimestre en curso" if d["trimestre"] == trimestre else ""}</span>']
         for d in detalle]
        + [["TOTAL EJERCICIO", inf.importe(datos.get("retencionesIRPF", 0.0)), ""]],
        anchos=["30%", "40%", "30%"])

    # 5 · pago fraccionado del IS
    tabla_202 = inf.tabla(
        ["Concepto", "Importe"],
        [["Base de ingresos (70x, 709…)", inf.importe(datos.get("baseIngresos", 0.0))],
         ["Base de gastos (60x-68x)", inf.importe(-datos.get("baseGastos", 0.0))],
         ["Base estimada del ejercicio", inf.importe(datos.get("baseIS", 0.0))],
         [f'Tipo del mod. 202', fmt_pct(PORCENTAJE_202 * 100)],
         ["Cuota estimada del pago fraccionado", inf.importe(datos.get("pagoFraccionadoIS", 0.0))],
         [f'Exigible en el {trimestre}T',
          ('<span style="color:#b26a00;font-weight:bold">Sí — plazo de '
           + inf.esc(plazo_303.get("humano", "")) + "</span>") if datos.get("aplicaModelo202")
          else '<span style="color:#666">No aplica a este trimestre</span>']],
        anchos=["62%", "38%"])

    # 6 · alertas y avisos
    bloques_alertas = "".join(
        inf.aviso(a["mensaje"], tipo=NIVELES.get(a["nivel"], ("info", "INFO"))[0],
                  titulo=f'{a["nivel"]} · modelo {a["modelo"]}')
        for a in datos.get("alertas") or []
    ) or inf.aviso("Sin alertas fiscales que destacar: las obligaciones del trimestre salen a cero.",
                   tipo="ok", titulo="Sin incidencias")

    avisos = datos.get("avisos") or []
    bloque_avisos = "".join(inf.aviso(a, tipo="alerta") for a in avisos) if avisos else ""

    cuerpo = (
        inf.aviso(
            f'Total a tener en cuenta en el {trimestre}T de {year}: '
            f'{fmt(datos.get("totalObligaciones", 0.0))} '
            f'(IVA {fmt(datos.get("obligacionIVA", 0.0))} + retenciones '
            f'{fmt(datos.get("obligacionRetenciones", 0.0))} + 202 '
            f'{fmt(datos.get("obligacion202", 0.0))}).',
            tipo="info", titulo=f"Obligaciones del {trimestre}T")
        + kpis + cabecera_trimestre
        + inf.seccion(f"Obligaciones del {trimestre}T y vencimientos", tabla_venc, nota=nota_venc)
        + inf.seccion("IVA por trimestre", tabla_iva + f'<div style="margin-top:10px">{grafico_iva}</div>')
        + inf.seccion("Retenciones de IRPF (4751)", tabla_ret,
                      nota="Retenciones soportadas del ejercicio y su reparto trimestral: alimenta el mod. 111.")
        + inf.seccion("Pago fraccionado del Impuesto sobre Sociedades (mod. 202)", tabla_202,
                      nota="La base es la del ejercicio completo (no la del trimestre), como en el cálculo original.")
        + inf.seccion("Alertas fiscales", bloques_alertas)
        + (inf.seccion("Avisos del cálculo", bloque_avisos,
                       nota="Comprobaciones de integridad hechas por el módulo sobre los apuntes cargados.")
           if bloque_avisos else "")
    )
    return inf.envoltura(
        titulo=TITULO,
        subtitulo=f"Ejercicio {year} · {trimestre}T ({periodo})",
        empresa=nombre_empresa, ejercicio=year, cuerpo=cuerpo,
        meta={"Trimestre": f"{trimestre}T {year}",
              "Plazo mod. 303": plazo_303.get("humano", ""),
              "Datos": "ERP apiCON (ejercicio completo)"},
    )


__all__ = ["NOMBRE", "TITULO", "INTERNO", "DESPLAZAMIENTOS", "PARAMETROS", "calcular",
           "informe_html", "metricas_dashboard", "vencimientos", "normalizar_trimestre"]
