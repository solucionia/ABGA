"""Módulo `autodespro` — REQ-03 Informe Autodespro (10 secciones).

Portado del nodo Code «Calcular Datos Autodespro» del workflow REQ-03 de n8n. El informe
original tenía diez secciones:

    1. Principales magnitudes (5 años)      6. Proveedores
    2. Evolución                             7. Tesorería
    3. Cuenta de pérdidas y ganancias        8. Partidas pendientes (555)
    4. Balance de situación                  9. Personal
    5. Ventas (evolución mensual)           10. Ratios (5 años)

El workflow pedía cinco ejercicios (`year`, `yearAnterior`, `year2`, `year3`, `year4`), de ahí
`DESPLAZAMIENTOS = [0, -1, -2, -3, -4]`. **Los años que se repiten se declaran**: si dos
ejercicios traen los mismos apuntes (o apuntes fechados en otro año) el módulo lo detecta, lo
escribe en `datos["avisos"]` y lo advierte en el pie del informe. El informe nunca presenta
cifras repetidas como si fueran datos auditados del ejercicio.

Correcciones sobre el JavaScript original (mismo criterio que `modulos/pyg.py`, para que los dos
informes del portal no den cifras distintas del mismo ejercicio):

1. **Ingresos financieros contados dos veces.** En el original «otros ingresos» incluía el
   prefijo `76`, y después el RAI volvía a sumar `760`-`769`: el resultado financiero se sumaba
   dos veces. Aquí `76` sale de otros ingresos y queda sólo en su línea.
2. **Gastos omitidos en la cuenta de resultados.** El original dejaba fuera del gasto el `607`
   (trabajos de otras empresas), el `609`, el `63x` y el `659`. Aquí se incluyen: son gastos de
   explotación reales del ejercicio.
3. **Inversiones a largo plazo invisibles en el balance.** El activo no corriente del original
   sólo miraba `20x` y `21x`; el grupo `25x` (inversiones financieras a largo plazo) no aparecía
   ni en el activo ni, por tanto, en el total. Aquí se añade.
4. **Saldos contrarios.** El original usaba `Math.max(0, …)` en algún agregado (y `pb>0`,
   `pn>0` en los ratios), lo que convertía en cero un saldo de signo contrario. Aquí se conserva
   el signo real: si un agregado sale al revés, eso es información para el asesor.
5. **Amortizaciones.** El original sólo sumaba `680`-`682`; se añaden `690`-`692` (amortización
   del inmovilizado intangible y financiero), coherente con el módulo `pyg`.

Lo que **no** se toca: los prefijos PGC de cada epígrafe, las fórmulas de los ratios y el orden
de las secciones del original.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from .. import informes as inf
from ..ledger import (Linea, MESES, anio_de, comprobar_cuadre, fmt, fmt_pct, mes_de, num,
                      por_tercero, saldos_por_cuenta, serie_mensual, suma_acreedor,
                      suma_deudor)

NOMBRE = "autodespro"
TITULO = "Informe Autodespro"
INTERNO = False
DESPLAZAMIENTOS = [0, -1, -2, -3, -4]
PARAMETROS: dict[str, Any] = {}

AZUL_FILA = "#eef4fd"

# ---------------------------------------------------------------- prefijos PGC (sin solapes)
P_VENTAS = ["700", "701", "702", "703", "704", "705"]
P_OTROS_INGRESOS = ["706", "708", "709", "740", "741", "746", "747", "748", "749", "75", "778"]
P_APROVISIONAMIENTOS = ["600", "601", "602", "606", "607", "608", "609", "610", "611", "612"]
P_PERSONAL = ["640", "641", "642", "643", "644", "649"]
P_OTROS_GASTOS = ["620", "621", "622", "623", "624", "625", "626", "627", "628", "629",
                  "631", "632", "633", "634", "636", "639", "650", "651", "659"]
P_AMORTIZACIONES = ["680", "681", "682", "690", "691", "692"]
P_ING_FINANCIEROS = ["760", "761", "762", "763", "769"]
P_GASTOS_FINANCIEROS = ["660", "661", "662", "663", "664", "665", "669"]
P_IMPUESTO = ["630", "633"]  # 633 = ajustes por impuesto de sociedades

P_INMOV_INTANGIBLE = ["200", "201", "202", "203", "204", "205", "206", "207", "208", "209", "280"]
P_INMOV_MATERIAL = ["210", "211", "212", "213", "214", "215", "216", "217", "218", "219", "281", "282"]
P_INVERSIONES_LP = [str(n) for n in range(250, 270)]
P_EXISTENCIAS = [str(n) for n in range(300, 360)]
P_CLIENTES = ["430", "431", "432", "433", "434", "435", "436", "437", "438", "439",
              "440", "441"]
P_OTROS_DEUDORES = ["460", "470", "471", "472", "473", "474", "476", "480", "481", "567", "568"]
P_TESORERIA = ["570", "571", "572", "573", "574", "575", "576", "577"]
P_PATRIMONIO = (["100", "101", "102", "103", "104", "108", "109"] + [str(n) for n in range(110, 122)]
                + ["130", "131", "132"])
P_PASIVO_NC = [str(n) for n in range(150, 180)]
P_PROVEEDORES = [str(n) for n in range(400, 420)]
P_DEUDAS_CP = ([str(n) for n in range(500, 530)] + [str(n) for n in range(550, 560)]
               + ["475", "477"])

P_INGRESOS_ACTIVIDAD = P_VENTAS + P_OTROS_INGRESOS
P_GASTOS_ACTIVIDAD = P_APROVISIONAMIENTOS + P_PERSONAL + P_OTROS_GASTOS

# epígrafes de la sección 1 y 2
MAGNITUDES = [
    ("Importe neto de la cifra de negocios", "totalIng", True),
    ("Resultado del ejercicio", "resultado", True),
    ("EBITDA", "ebitda", False),
    ("Resultado de explotación (EBIT)", "ebit", False),
    ("Cash-flow", "cashFlow", False),
    ("Activo total", "totalActivo", False),
    ("Patrimonio neto", "pn", False),
    ("Pasivo corriente", "pasC", False),
    ("Fondo de maniobra", "fm", True),
    ("Tesorería", "tesoreria", False),
]

# (etiqueta, clave, es_total) — cuenta de resultados comparativa, sección 3
PYG_FILAS = [
    ("Ventas", "ventas", False),
    ("Otros ingresos de explotación", "otrosIng", False),
    ("TOTAL INGRESOS DE EXPLOTACIÓN", "totalIng", True),
    ("Aprovisionamientos", "aprov", False),
    ("MARGEN BRUTO", "margenBruto", True),
    ("Gastos de personal", "gastPers", False),
    ("Otros gastos de explotación", "otrosGast", False),
    ("EBITDA", "ebitda", True),
    ("Amortizaciones", "amort", False),
    ("RESULTADO DE EXPLOTACIÓN", "ebit", True),
    ("Resultado financiero", "resFin", False),
    ("RESULTADO ANTES DE IMPUESTOS", "rai", True),
    ("Impuesto sobre sociedades", "is", False),
    ("RESULTADO DEL EJERCICIO", "resultado", True),
    ("Cash-flow", "cashFlow", False),
]

# ratios de la sección 10: (nombre, clave, óptimo, formato)
RATIOS = [
    ("Prueba ácida", "pruebaAcida", "0,8 – 1,0", "num"),
    ("Ratio de solvencia", "solvencia", "1,50", "num"),
    ("Endeudamiento s/activo", "endeudamiento", "≈ 50%", "pct"),
    ("Ratio de garantía", "garantia", "> 1,20", "num"),
    ("ROE", "roe", "> 10%", "pct"),
    ("ROA", "roa", "> 5%", "pct"),
]

NOMBRE_CUENTA = {
    "640": "Sueldos y salarios", "641": "Indemnizaciones", "642": "Seguridad Social a cargo de la empresa",
    "643": "Aportaciones a sistemas de pensiones", "644": "Retribuciones a largo plazo",
    "649": "Otros gastos sociales",
    "475": "Hacienda Pública acreedora", "476": "Organismos de la Seguridad Social acreedores",
    "477": "Hacienda Pública, IVA repercutido", "472": "Hacienda Pública, IVA soportado",
    "470": "Hacienda Pública deudora", "400": "Proveedores", "410": "Acreedores por prestaciones",
    "430": "Clientes", "440": "Deudores", "465": "Remuneraciones pendientes de pago",
    "555": "Partidas pendientes de aplicación", "524": "Acreedores por arrendamiento financiero c/p",
    "600": "Compras de mercaderías", "607": "Trabajos realizados por otras empresas",
}


# ------------------------------------------------------------------ utilidades internas

def _mag(L: Sequence[Linea]) -> dict[str, float]:
    """Las magnitudes del original (`mag()`), conservando el signo real de cada agregado."""
    s = saldos_por_cuenta(L)
    D = lambda pref: suma_deudor(s, pref, recortar=False)      # noqa: E731  (activo / gasto)
    A = lambda pref: suma_acreedor(s, pref, recortar=False)    # noqa: E731  (pasivo / ingreso)

    ventas = A(P_VENTAS)
    otros_ing = A(P_OTROS_INGRESOS)
    total_ing = ventas + otros_ing
    aprov = D(P_APROVISIONAMIENTOS)
    gast_pers = D(P_PERSONAL)
    otros_gast = D(P_OTROS_GASTOS)
    amort = D(P_AMORTIZACIONES)
    gast_fin = D(P_GASTOS_FINANCIEROS)
    ing_fin = A(P_ING_FINANCIEROS)
    ebitda = total_ing - aprov - gast_pers - otros_gast
    ebit = ebitda - amort
    rai = ebit + ing_fin - gast_fin
    is_ = D(P_IMPUESTO)
    resultado = rai - is_
    cash_flow = resultado + amort

    activo_nc = D(P_INMOV_INTANGIBLE) + D(P_INMOV_MATERIAL) + D(P_INVERSIONES_LP)
    existencias = D(P_EXISTENCIAS)
    clientes = D(P_CLIENTES)
    otros_deudores = D(P_OTROS_DEUDORES)
    tesoreria = D(P_TESORERIA)
    activo_c = existencias + clientes + otros_deudores + tesoreria
    total_activo = activo_nc + activo_c

    pn = A(P_PATRIMONIO) + resultado
    pas_nc = A(P_PASIVO_NC)
    proveedores = A(P_PROVEEDORES)
    deudas_cp = A(P_DEUDAS_CP)
    pas_c = proveedores + deudas_cp
    fm = activo_c - pas_c
    recursos_ajenos = pas_nc + pas_c

    return {
        "ventas": round(ventas, 2), "otrosIng": round(otros_ing, 2), "totalIng": round(total_ing, 2),
        "aprov": round(aprov, 2), "gastPers": round(gast_pers, 2), "otrosGast": round(otros_gast, 2),
        "amort": round(amort, 2), "ingFin": round(ing_fin, 2), "gastFin": round(gast_fin, 2),
        "ebitda": round(ebitda, 2), "ebit": round(ebit, 2), "rai": round(rai, 2),
        "is": round(is_, 2), "resultado": round(resultado, 2), "cashFlow": round(cash_flow, 2),
        "margenBruto": round(total_ing - aprov, 2), "resFin": round(ing_fin - gast_fin, 2),
        "activoNC": round(activo_nc, 2), "existencias": round(existencias, 2),
        "clientes": round(clientes, 2), "otrosDeudores": round(otros_deudores, 2),
        "tesoreria": round(tesoreria, 2), "activoC": round(activo_c, 2),
        "totalActivo": round(total_activo, 2), "pn": round(pn, 2), "pasNC": round(pas_nc, 2),
        "proveedores": round(proveedores, 2), "deudasCP": round(deudas_cp, 2),
        "pasC": round(pas_c, 2), "fm": round(fm, 2), "recursosAjenos": round(recursos_ajenos, 2),
        "nLineas": len(L),
    }


def _ratio(m: dict[str, float]) -> dict[str, float]:
    """Los seis ratios del original, sin los `if > 0` que convertían un mal dato en un cero."""
    def div(n: float, d: float) -> float:
        return (n / d) if d else 0.0

    return {
        "pruebaAcida": round(div(m["clientes"] + m["tesoreria"], m["pasC"]), 4),
        "solvencia": round(div(m["activoC"], m["pasC"]), 4),
        "endeudamiento": round(div(m["recursosAjenos"], m["totalActivo"]) * 100, 2),
        "garantia": round(div(m["totalActivo"], m["recursosAjenos"]), 4),
        "roe": round(div(m["resultado"], m["pn"]) * 100, 2),
        "roa": round(div(m["ebit"], m["totalActivo"]) * 100, 2),
        "liquidez": round(div(m["activoC"], m["pasC"]), 4),
    }


def _firma(lineas: Sequence[Linea]) -> tuple | None:
    """Huella de un ejercicio: con ella se detecta que dos años traen los mismos apuntes."""
    if not lineas:
        return None
    fechas = [l.fecha for l in lineas if l.fecha]
    return (len(lineas), round(sum(l.debe for l in lineas), 2), round(sum(l.haber for l in lineas), 2),
            min(fechas) if fechas else 0, max(fechas) if fechas else 0)


def _procedencia(anios: list[int], por_anio: dict[int, Sequence[Linea]]) -> list[dict[str, Any]]:
    """Para cada ejercicio: ¿es real, repite los apuntes de otro, o no hay datos?

    Es la salvaguarda de honestidad del informe: los años repetidos no se presentan como
    cifras auditadas del ejercicio que dicen ser.
    """
    firmas: dict[tuple, int] = {}
    salida = []
    for a in anios:  # del más reciente al más antiguo
        L = list(por_anio.get(a) or [])
        f = _firma(L)
        fechas = [anio_de(l.fecha) for l in L if l.fecha]
        anio_fechas = max(set(fechas), key=fechas.count) if fechas else 0
        estado, repite = "real", None
        if not L:
            estado = "sin_datos"
        elif f in firmas:
            estado, repite = "repetido", firmas[f]
        elif anio_fechas and anio_fechas != a:
            estado, repite = "otro_ejercicio", anio_fechas
        if f is not None and f not in firmas:
            firmas[f] = a
        salida.append({"year": a, "estado": estado, "repiteDe": repite,
                       "etiqueta": str(a) if estado == "real" else f"{a}*",
                       "nLineas": len(L), "anioFechas": anio_fechas,
                       "real": estado == "real"})
    return salida


def _etiqueta_anio(fila: dict[str, Any]) -> str:
    """`2024*` cuando el ejercicio no trae datos propios."""
    return str(fila["year"]) if fila["real"] else f'{fila["year"]}*'


def _nombre_tercero(t: str) -> str:
    """Nombre del tercero a partir del literal del ERP («INV/2025/0006-KOKKEN SURFACES SL»).

    El ERP no rellena `Tercero` en los apuntes de esta empresa: el nombre viaja al final de la
    descripción del apunte, detrás del último guion. Se normaliza sólo para poder agrupar.
    """
    t = (t or "").strip()
    if "-" in t:
        cola = t.rsplit("-", 1)[1].strip(" .")
        if len(cola) >= 3 and any(c.isalpha() for c in cola):
            return cola
    return t or "(sin tercero)"


def _terceros(lineas: Sequence[Linea], prefijos: Sequence[str], limite: int = 10) -> list[dict[str, Any]]:
    """Saldos por tercero (primitiva `por_tercero`) con los nombres ya normalizados."""
    agrupado: dict[str, dict[str, Any]] = {}
    for f in por_tercero(lineas, prefijos):
        clave = _nombre_tercero(f["tercero"])
        acc = agrupado.setdefault(clave, {"tercero": clave, "debe": 0.0, "haber": 0.0, "saldo": 0.0, "n": 0})
        for k in ("debe", "haber", "saldo", "n"):
            acc[k] += f[k]
    filas = sorted(agrupado.values(), key=lambda f: -abs(f["saldo"]))
    total = sum(f["saldo"] for f in filas) or 0.0
    for f in filas:
        f["peso"] = round(f["saldo"] / total * 100, 1) if total else 0.0
    return filas[:limite]


def _mensual_prefijos(lineas: Sequence[Linea]) -> list[dict[str, Any]]:
    """12 filas de ventas / gastos de explotación del ejercicio pedido."""
    return serie_mensual(lineas, P_INGRESOS_ACTIVIDAD, P_GASTOS_ACTIVIDAD)


def _saldos_mensuales(lineas: Sequence[Linea], prefijos: Sequence[str]) -> list[dict[str, Any]]:
    """12 filas de debe / haber / saldo para los prefijos indicados (secciones 7 y 9)."""
    filas = []
    for m in range(1, 13):
        saldos = saldos_por_cuenta([l for l in lineas if mes_de(l.fecha) == m])
        debe = round(suma_deudor(saldos, prefijos, recortar=False), 2)
        haber = round(suma_acreedor(saldos, prefijos, recortar=False), 2)
        filas.append({"mes": MESES[m - 1], "mesNum": m, "debe": debe, "haber": haber,
                      "saldo": round(debe - haber, 2)})
    return filas


def _por_cuenta(lineas: Sequence[Linea], prefijos: Sequence[str]) -> list[dict[str, Any]]:
    """Desglose por cuenta (los cuatro primeros dígitos) de los prefijos dados."""
    acc: dict[str, dict[str, Any]] = {}
    for l in lineas:
        if not any(l.cuenta.startswith(p) for p in prefijos):
            continue
        clave = l.cuenta[:4] if len(l.cuenta) >= 4 else l.cuenta
        r = acc.setdefault(clave, {"cuenta": clave, "debe": 0.0, "haber": 0.0, "n": 0})
        r["debe"] += l.debe
        r["haber"] += l.haber
        r["n"] += 1
    filas = sorted(acc.values(), key=lambda r: -abs(r["debe"] - r["haber"]))
    for r in filas:
        r["debe"] = round(r["debe"], 2)
        r["haber"] = round(r["haber"], 2)
        r["saldo"] = round(r["debe"] - r["haber"], 2)
        r["nombre"] = NOMBRE_CUENTA.get(r["cuenta"], "")
    return filas


def _partidas_555(lineas: Sequence[Linea]) -> dict[str, Any]:
    """Sección 8: partidas pendientes de aplicación de la cuenta 555."""
    pend = [l for l in lineas if l.cuenta.startswith("555")]
    pend.sort(key=lambda l: (l.fecha, l.documento), reverse=True)
    filas = [{
        "fecha": l.fecha, "concepto": l.descripcion or l.crudo.get("Concepto") or "",
        "documento": f"{l.serie}/{l.documento}" if l.serie else str(l.documento),
        "debe": round(l.debe, 2), "haber": round(l.haber, 2), "nCuenta": l.cuenta,
    } for l in pend[:10]]
    return {"filas": filas, "n": len(pend),
            "debe": round(sum(l.debe for l in pend), 2),
            "haber": round(sum(l.haber for l in pend), 2),
            "saldo": round(sum(l.debe - l.haber for l in pend), 2)}


def _fecha_es(f: Any) -> str:
    f = int(f or 0)
    if not f:
        return "—"
    return f"{f % 100:02d}/{(f // 100) % 100:02d}/{f // 10000}"


# ------------------------------------------------------------------ cálculo

def calcular(por_anio: dict[int, list[Linea]], ctx: dict) -> dict[str, Any]:
    """Todas las cifras del informe, en números (el formato es cosa de `informe_html`)."""
    year = int(ctx.get("year") or 0)
    anios = [year + d for d in DESPLAZAMIENTOS]
    datos_anio = {int(k): list(v or []) for k, v in (por_anio or {}).items()}
    por_anio_norm = {a: datos_anio.get(a, []) for a in anios}

    procedencia = _procedencia(anios, por_anio_norm)
    mags = {a: _mag(por_anio_norm[a]) for a in anios}
    rat = {a: _ratio(mags[a]) for a in anios}
    actual, anterior = mags.get(year, {}), mags.get(year - 1, {})

    avisos: list[str] = []
    reales = [f["year"] for f in procedencia if f["real"]]
    no_reales = [f for f in procedencia if not f["real"]]
    if len(reales) < len(anios):
        detalle = []
        for f in no_reales:
            if f["estado"] == "sin_datos":
                detalle.append(f'{f["year"]}: sin apuntes cargados')
            elif f["estado"] == "repetido":
                detalle.append(f'{f["year"]}: se han usado los mismos apuntes que en {f["repiteDe"]}')
            else:
                detalle.append(f'{f["year"]}: los apuntes que trae están fechados en {f["repiteDe"]}')
        avisos.append(
            f"Sólo hay {len(reales)} ejercicio(s) con datos propios ({', '.join(str(a) for a in reales)}) "
            f"de los {len(anios)} previstos. " + "; ".join(detalle) +
            ". Las columnas marcadas con asterisco (*) no son datos auditados de ese ejercicio: "
            "no deben usarse como serie histórica real.")

    cuadre = comprobar_cuadre(por_anio_norm[year]) if por_anio_norm.get(year) else {"descuadre": 0.0}
    if abs(cuadre.get("descuadre", 0.0)) > 1:
        avisos.append(f"El libro del ejercicio {year} no cuadra: ΣDebe − ΣHaber = "
                      f"{fmt(cuadre['descuadre'])}. Revisar antes de dar el informe por bueno.")
    cuadre_ant = comprobar_cuadre(por_anio_norm[year - 1]) if por_anio_norm.get(year - 1) else {"descuadre": 0.0}
    if abs(cuadre_ant.get("descuadre", 0.0)) > 1 and (year - 1) in reales:
        avisos.append(f"El libro del ejercicio {year - 1} tampoco cuadra "
                      f"(ΣDebe − ΣHaber = {fmt(cuadre_ant['descuadre'])}).")

    if not actual.get("nLineas"):
        avisos.append(f"El ejercicio {year} no tiene apuntes: el informe sale en blanco.")
    if actual.get("totalIng") and actual.get("totalIng", 0) <= 0:
        avisos.append("El importe neto de la cifra de negocios del ejercicio es cero o negativo: "
                      "revisar los ingresos del periodo.")

    # secciones 6 y 7
    proveedores = _terceros(por_anio_norm[year], P_PROVEEDORES, limite=10)
    clientes = _terceros(por_anio_norm[year], P_CLIENTES + P_OTROS_DEUDORES, limite=10)
    tesoreria_cuentas = _por_cuenta(por_anio_norm[year], P_TESORERIA)
    tesoreria_mensual = _saldos_mensuales(por_anio_norm[year], P_TESORERIA)
    if not tesoreria_cuentas:
        avisos.append("Los apuntes del ejercicio no traen cuentas de tesorería (grupo 57): no se puede "
                      "explicar la variación de efectivo ni cuadrar cobros y pagos con los bancos.")
    elif not any(f["debe"] or f["haber"] for f in tesoreria_mensual):
        avisos.append("Hay cuentas del grupo 57 pero sin movimientos en el ejercicio.")

    partidas = _partidas_555(por_anio_norm[year])
    if not partidas["n"]:
        avisos.append("No hay movimientos en la cuenta 555 (partidas pendientes de aplicación) "
                      "en el ejercicio.")

    personal_cuentas = _por_cuenta(por_anio_norm[year], P_PERSONAL)
    personal_mensual = _saldos_mensuales(por_anio_norm[year], P_PERSONAL)
    if not personal_cuentas:
        avisos.append("No hay gastos de personal (grupo 64) en los apuntes del ejercicio.")

    mensual = _mensual_prefijos(por_anio_norm[year])
    serie = [{
        "year": f["year"], "etiqueta": _etiqueta_anio(f), "real": f["real"],
        **{k: mags[f["year"]].get(k, 0.0) for k in
           ("totalIng", "ebitda", "ebit", "resultado", "cashFlow", "totalActivo", "pn",
            "pasC", "fm", "tesoreria", "clientes", "aprov", "gastPers", "otrosGast", "amort")},
        **rat[f["year"]],
    } for f in procedencia]

    # variación interanual de los epígrafes principales
    for i, fila in enumerate(serie):
        prev = serie[i - 1] if i else None
        for k in ("totalIng", "resultado", "ebitda", "totalActivo", "pn", "fm"):
            base = (prev or {}).get(k)
            fila[f"var_{k}"] = (round((fila[k] - base) / abs(base) * 100, 1)
                                if base else None)

    pyg = [{
        "desc": etiqueta, "clave": clave, "total": es_total,
        "actual": actual.get(clave, 0.0), "anterior": anterior.get(clave, 0.0),
        "pctActual": (round(actual.get(clave, 0.0) / actual["totalIng"] * 100, 1)
                      if actual.get("totalIng") else None),
    } for etiqueta, clave, es_total in PYG_FILAS]

    return {
        "empresa": ctx.get("empresa", ""), "codEmpresa": ctx.get("cod_empresa", ""),
        "year": year, "yearAnterior": year - 1, "anios": anios,
        "procedencia": procedencia, "etiquetas": [f["etiqueta"] for f in procedencia],
        "reales": reales, "noReales": no_reales,
        "actual": actual, "anterior": anterior, "magnitudes": mags, "ratiosPorAnio": rat,
        "magnitudesTabla": [{"desc": d, "clave": k, "total": t,
                             "valores": [mags[a].get(k, 0.0) for a in reversed(anios)]}
                            for d, k, t in MAGNITUDES],
        "serie": serie,
        "pyg": pyg,
        "balanceActivo": [
            ("Activo no corriente", "activoNC"), ("Existencias", "existencias"),
            ("Clientes", "clientes"), ("Otros deudores", "otrosDeudores"),
            ("Tesorería", "tesoreria"),
        ],
        "balancePasivo": [
            ("Patrimonio neto", "pn"), ("Pasivo no corriente", "pasNC"),
            ("Proveedores", "proveedores"), ("Otras deudas a corto plazo", "deudasCP"),
        ],
        "cuadre": {"ejercicio": cuadre.get("descuadre", 0.0), "anterior": cuadre_ant.get("descuadre", 0.0),
                   "activo": actual.get("totalActivo", 0.0),
                   "pasivoPN": actual.get("pn", 0.0) + actual.get("pasNC", 0.0) + actual.get("pasC", 0.0)},
        "evMensual": mensual,
        "clientes": clientes, "proveedores": proveedores,
        "tesoreria": {"cuentas": tesoreria_cuentas, "mensual": tesoreria_mensual,
                      "saldo": actual.get("tesoreria", 0.0),
                      "saldoAnterior": (mags.get(year - 1) or {}).get("tesoreria", 0.0),
                      "variacion": round(actual.get("tesoreria", 0.0)
                                         - (mags.get(year - 1) or {}).get("tesoreria", 0.0), 2)},
        "partidas555": partidas,
        "personal": {"cuentas": personal_cuentas, "mensual": personal_mensual,
                     "total": actual.get("gastPers", 0.0),
                     "totalAnterior": anterior.get("gastPers", 0.0)},
        "ratios": [{"nombre": n, "clave": k, "optimo": o, "formato": fo,
                    "valores": [rat[a].get(k, 0.0) for a in reversed(anios)]}
                   for n, k, o, fo in RATIOS],
        "avisos": avisos,
    }


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    """KPIs del panel: las cifras del ejercicio pedido, sin formatear."""
    a = datos.get("actual", {})
    return {
        "totalIngresos": a.get("totalIng", 0.0), "resultadoNeto": a.get("resultado", 0.0),
        "ebitda": a.get("ebitda", 0.0), "ebit": a.get("ebit", 0.0),
        "tesoreria": a.get("tesoreria", 0.0), "fondoManiobra": a.get("fm", 0.0),
        "totalActivo": a.get("totalActivo", 0.0), "patrimonioNeto": a.get("pn", 0.0),
        "pasivoCorriente": a.get("pasC", 0.0), "cashFlow": a.get("cashFlow", 0.0),
        "ratios": (datos.get("ratiosPorAnio") or {}).get(datos.get("year"), {}),
        "aniosReales": (datos.get("reales") or []),
        "avisos": len(datos.get("avisos") or []),
    }


# ------------------------------------------------------------------ maquetación

def _pct(v: Any, *, con_signo: bool = True) -> str:
    """Porcentaje coloreado; `None` cuando la base es cero o no hay dato."""
    if v is None:
        return '<span style="color:#8a97a8">—</span>'
    color = inf.NEGATIVO if v < 0 else (inf.POSITIVO if v > 0 else "#333")
    texto = f"{v:+,.1f}".replace(".", ",") if con_signo else f"{v:,.1f}".replace(".", ",")
    return f'<span style="color:{color};white-space:nowrap">{texto}%</span>'


def _valor_ratio(v: float, formato: str) -> str:
    if formato == "pct":
        return fmt_pct(v)
    return num(v)


def _tabla_magnitudes(datos: dict[str, Any]) -> str:
    filas = []
    for m in datos["magnitudesTabla"]:
        peso = "bold" if m["total"] else "normal"
        etiqueta = (f'<span style="font-weight:{peso}">{inf.esc(m["desc"])}</span>')
        filas.append([etiqueta] + [inf.importe(v, con_signo=m["total"]) for v in m["valores"]])
    return inf.tabla(["Concepto"] + datos["etiquetas"], filas,
                     anchos=["28%"] + ["14.4%"] * 5, alinear="right", primera_izquierda=True)


def _tabla_pyg(datos: dict[str, Any]) -> str:
    y, ya = datos["year"], datos["yearAnterior"]
    filas = []
    for f in datos["pyg"]:
        peso = "bold" if f["total"] else "normal"
        var = None
        if f["anterior"]:
            var = round((f["actual"] - f["anterior"]) / abs(f["anterior"]) * 100, 1)
        if f["desc"] in {"Aprovisionamientos", "Gastos de personal", "Otros gastos de explotación",
                         "Amortizaciones", "Impuesto sobre sociedades"}:
            a, b = -f["actual"], -f["anterior"]
        else:
            a, b = f["actual"], f["anterior"]
        filas.append([
            f'<span style="font-weight:{peso}">{inf.esc(f["desc"])}</span>',
            inf.importe(a),
            _pct(f["pctActual"], con_signo=False),
            inf.importe(b),
            _pct(var),
        ])
    return inf.tabla(["Concepto", f"Ejercicio {y}", "% s/ingresos", f"Ejercicio {ya}", "Variación"],
                     filas, anchos=["38%", "17%", "14%", "17%", "14%"],
                     alinear="right", primera_izquierda=True)


def _tabla_balance(datos: dict[str, Any]) -> str:
    a, ant = datos["actual"], datos["anterior"]
    y, ya = datos["year"], datos["yearAnterior"]

    filas_a = []
    for etiqueta, clave in datos["balanceActivo"]:
        filas_a.append([etiqueta, inf.importe(a.get(clave, 0.0)), inf.importe(ant.get(clave, 0.0))])
    filas_a.append([f'<b>Activo corriente</b>', inf.importe(a.get("activoC", 0.0)),
                    inf.importe(ant.get("activoC", 0.0))])
    filas_a.append([f'<b>TOTAL ACTIVO</b>', inf.importe(a.get("totalActivo", 0.0)),
                    inf.importe(ant.get("totalActivo", 0.0))])
    tabla_a = inf.tabla(["Activo", y, ya], filas_a, anchos=["52%", "24%", "24%"], alinear="right")

    filas_p = []
    for etiqueta, clave in datos["balancePasivo"]:
        filas_p.append([etiqueta, inf.importe(a.get(clave, 0.0)), inf.importe(ant.get(clave, 0.0))])
    filas_p.append([f'<b>Pasivo corriente</b>', inf.importe(a.get("pasC", 0.0)),
                    inf.importe(ant.get("pasC", 0.0))])
    filas_p.append([f'<b>TOTAL PATRIMONIO NETO Y PASIVO</b>',
                    inf.importe(a.get("pn", 0.0) + a.get("pasNC", 0.0) + a.get("pasC", 0.0)),
                    inf.importe(ant.get("pn", 0.0) + ant.get("pasNC", 0.0) + ant.get("pasC", 0.0))])
    tabla_p = inf.tabla(["Patrimonio neto y pasivo", y, ya], filas_p, anchos=["52%", "24%", "24%"],
                        alinear="right")
    return tabla_a + f'<div style="height:10px"></div>' + tabla_p


def _tabla_terceros(titulo: str, filas: list[dict[str, Any]], columna: str) -> str:
    if not filas:
        return inf.aviso(f"No se han podido agrupar {columna}: los apuntes no traen tercero "
                         "identificable.", tipo="info")
    return inf.tabla([titulo, "Debe", "Haber", "Saldo", "Peso"],
                     [[f["tercero"], inf.importe(f["debe"]), inf.importe(f["haber"]),
                       inf.importe(f["saldo"]), fmt_pct(f["peso"])] for f in filas],
                     anchos=["40%", "15%", "15%", "18%", "12%"], alinear="right")


def _tabla_tesoreria(datos: dict[str, Any]) -> str:
    t = datos["tesoreria"]
    if not t["cuentas"]:
        return inf.aviso("Los apuntes de este ejercicio no contienen cuentas del grupo 57 "
                         "(caja y bancos), así que no se puede detallar la tesorería ni la "
                         "variación de efectivo.", tipo="alerta", titulo="Sin datos de tesorería")
    filas = [[c["nombre"] or c["cuenta"], inf.importe(c["debe"]), inf.importe(c["haber"]),
              inf.importe(c["saldo"])] for c in t["cuentas"]]
    filas.append(['<b>Total</b>', inf.importe(sum(c["debe"] for c in t["cuentas"])),
                  inf.importe(sum(c["haber"] for c in t["cuentas"])), inf.importe(t["saldo"])])
    return inf.tabla(["Cuenta", "Cargos (entradas)", "Abonos (salidas)", "Saldo"],
                     filas, anchos=["40%", "20%", "20%", "20%"], alinear="right")


def _tabla_partidas555(datos: dict[str, Any]) -> str:
    p = datos["partidas555"]
    if not p["n"]:
        return inf.aviso("No hay movimientos en la cuenta 555 en el ejercicio.", tipo="ok",
                         titulo="Sin partidas pendientes")
    filas = [[_fecha_es(f["fecha"]), f["documento"], f["concepto"][:52],
              inf.importe(f["debe"]), inf.importe(f["haber"])] for f in p["filas"]]
    filas.append([f'<b>{p["n"]} apuntes</b>', "", "",
                  inf.importe(p["debe"]), inf.importe(p["haber"])])
    return inf.tabla(["Fecha", "Documento", "Concepto", "Debe", "Haber"], filas,
                     anchos=["11%", "16%", "41%", "16%", "16%"], alinear="right")


def _tabla_personal(datos: dict[str, Any]) -> str:
    p = datos["personal"]
    if not p["cuentas"]:
        return inf.aviso("No hay gastos de personal (grupo 64) en los apuntes del ejercicio.",
                         tipo="info")
    filas = [[c["nombre"] or c["cuenta"], inf.importe(c["debe"]), inf.importe(c["haber"]),
              inf.importe(c["saldo"])] for c in p["cuentas"]]
    filas.append([f'<b>Total</b>', inf.importe(sum(c["debe"] for c in p["cuentas"])),
                  inf.importe(sum(c["haber"] for c in p["cuentas"])),
                  inf.importe(p["total"])])
    return inf.tabla(["Concepto", "Debe", "Haber", "Gasto del ejercicio"], filas,
                     anchos=["40%", "20%", "20%", "20%"], alinear="right")


def _tabla_ratios(datos: dict[str, Any]) -> str:
    filas = []
    for r in datos["ratios"]:
        filas.append([r["nombre"], r["optimo"]]
                     + [_valor_ratio(v, r["formato"]) for v in r["valores"]])
    return inf.tabla(["Ratio", "Valor óptimo"] + datos["etiquetas"], filas,
                     anchos=["22%", "14%"] + ["12.8%"] * 5, alinear="right",
                     primera_izquierda=True)


def _seccion_procedencia(datos: dict[str, Any]) -> str:
    piezas = []
    for f in datos["procedencia"]:
        if f["estado"] == "real":
            texto, tipo = "datos propios del ejercicio", "ok"
        elif f["estado"] == "sin_datos":
            texto, tipo = "sin apuntes cargados", "error"
        elif f["estado"] == "repetido":
            texto, tipo = f'repite los apuntes de {f["repiteDe"]} (NO es dato del ejercicio)', "alerta"
        else:
            texto, tipo = f'los apuntes están fechados en {f["repiteDe"]}', "alerta"
        color = {"ok": inf.POSITIVO, "error": inf.NEGATIVO, "alerta": inf.AMBAR}[tipo]
        piezas.append(f'<tr><td style="padding:3px 8px;border-bottom:1px solid #eef2f8;'
                      f'font-weight:bold">{f["year"]}</td>'
                      f'<td style="padding:3px 8px;border-bottom:1px solid #eef2f8">{f["nLineas"]} apuntes</td>'
                      f'<td style="padding:3px 8px;border-bottom:1px solid #eef2f8;color:{color}">{inf.esc(texto)}</td></tr>')
    return ('<table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr>'
            f'<th style="text-align:left;padding:6px 8px;border-bottom:2px solid {inf.AZUL};color:{inf.AZUL}">Ejercicio</th>'
            f'<th style="text-align:left;padding:6px 8px;border-bottom:2px solid {inf.AZUL};color:{inf.AZUL}">Volumen</th>'
            f'<th style="text-align:left;padding:6px 8px;border-bottom:2px solid {inf.AZUL};color:{inf.AZUL}">Procedencia de los datos</th>'
            f'</tr></thead><tbody>{"".join(piezas)}</tbody></table>')


def _nota_anios(datos: dict[str, Any]) -> str:
    reales = ", ".join(str(a) for a in datos["reales"]) or "ninguno"
    if not datos["noReales"]:
        return f"Ejercicios calculados con apuntes propios del ERP: {reales}."
    partes = []
    for f in datos["noReales"]:
        if f["estado"] == "sin_datos":
            partes.append(f'{f["year"]} sin datos')
        else:
            partes.append(f'{f["year"]}* repetido de {f["repiteDe"]}')
    return (f"Años reales del ERP: {reales}. Sin datos propios: {', '.join(partes)}. "
            "Las columnas con asterisco se han calculado repitiendo los apuntes de otro ejercicio "
            "para poder mostrar la serie de cinco años: no son cifras auditadas de ese ejercicio.")


def informe_html(datos: dict[str, Any], ctx: dict) -> str:
    """HTML del informe (empieza por `<div`, CSS inline, sin markdown)."""
    y = datos["year"]
    a = datos["actual"]
    serie = datos["serie"]
    etiquetas = [s["etiqueta"] for s in serie]

    kpis = [
        ("Ingresos", inf.importe(a.get("totalIng", 0.0))),
        ("EBITDA", inf.importe(a.get("ebitda", 0.0))),
        ("Resultado", inf.importe(a.get("resultado", 0.0))),
        ("Fondo de maniobra", inf.importe(a.get("fm", 0.0))),
        ("Activo total", inf.importe(a.get("totalActivo", 0.0))),
        ("Patrimonio neto", inf.importe(a.get("pn", 0.0))),
        ("Pasivo corriente", inf.importe(a.get("pasC", 0.0))),
        ("Tesorería", inf.importe(a.get("tesoreria", 0.0))),
    ]

    avisos_html = "".join(
        inf.aviso(t, tipo="alerta", titulo="Años repetidos" if "auditados" in t else "Aviso")
        for t in datos["avisos"])

    # sección 2: evolución interanual
    graf_evol = inf.lineas_svg(
        etiquetas,
        [{"nombre": "Ingresos", "color": inf.AZUL, "valores": [s["totalIng"] for s in serie]},
         {"nombre": "EBITDA", "color": inf.POSITIVO, "valores": [s["ebitda"] for s in serie]},
         {"nombre": "Resultado", "color": "#c98a2b", "valores": [s["resultado"] for s in serie]}],
        titulo="Evolución de ingresos, EBITDA y resultado")
    graf_balance = inf.barras_svg(
        etiquetas,
        [{"nombre": "Activo total", "color": inf.AZUL, "valores": [s["totalActivo"] for s in serie]},
         {"nombre": "Patrimonio neto", "color": inf.POSITIVO, "valores": [s["pn"] for s in serie]},
         {"nombre": "Pasivo corriente", "color": inf.NEGATIVO, "valores": [s["pasC"] for s in serie]}],
        alto=170, titulo="Estructura del balance (5 ejercicios)")

    # sección 5: ventas
    mensual = datos["evMensual"]
    graf_ventas = inf.barras_svg(
        [f["mes"] for f in mensual],
        [{"nombre": "Ingresos", "color": inf.AZUL, "valores": [f["ingresos"] for f in mensual]},
         {"nombre": "Gastos de explotación", "color": "#c98a2b", "valores": [f["gastos"] for f in mensual]}],
        titulo="Ingresos y gastos de explotación por mes")
    tabla_ventas = inf.tabla(
        ["Mes", "Ingresos", "Gastos", "Resultado", "% del año"],
        [[f["mes"], inf.importe(f["ingresos"]), inf.importe(f["gastos"]),
          inf.importe(f["resultado"]),
          fmt_pct(f["ingresos"] / a["totalIng"] * 100 if a.get("totalIng") else 0.0)]
         for f in mensual]
        + [['<b>Total</b>', inf.importe(sum(f["ingresos"] for f in mensual)),
            inf.importe(sum(f["gastos"] for f in mensual)),
            inf.importe(sum(f["resultado"] for f in mensual)), "100,0%"]],
        anchos=["20%", "20%", "20%", "20%", "20%"], alinear="right")

    # sección 9: personal (gráfica mensual)
    graf_personal = inf.barras_svg(
        [f["mes"] for f in datos["personal"]["mensual"]],
        [{"nombre": "Gastos de personal", "color": inf.AZUL,
          "valores": [f["debe"] for f in datos["personal"]["mensual"]]}],
        alto=160, titulo="Gastos de personal por mes (debe de las cuentas 64)")

    # sección 7: tesorería (gráfica de saldo mensual acumulado)
    mensual_teso = datos["tesoreria"]["mensual"]
    acum, valores_teso = 0.0, []
    for f in mensual_teso:
        acum += f["saldo"]
        valores_teso.append(round(acum, 2))
    graf_teso = inf.lineas_svg([f["mes"] for f in mensual_teso],
                               [{"nombre": "Saldo acumulado", "color": inf.AZUL, "valores": valores_teso}],
                               alto=160, titulo="Variación acumulada de tesorería")

    evolucion_txt = " · ".join(
        f'{s["etiqueta"]}: {fmt(s["totalIng"])}' for s in serie)

    cuerpo = (
        avisos_html
        + inf.kpis(kpis)
        + inf.seccion("1. Principales magnitudes y procedencia de los datos", _tabla_magnitudes(datos)
                      + f'<div style="font-size:11.5px;color:#5b6b80;padding:6px 2px 0">'
                      f'Ejercicios calculados con datos reales: <b>{", ".join(str(x) for x in datos["reales"])}</b>. '
                      f'Los años marcados con <b>*</b> no son datos propios del ejercicio (ver pie).</div>'
                      + f'<div style="margin-top:8px">{_seccion_procedencia(datos)}</div>',
                      nota="Importes en euros. Los epígrafes con signo negativo llevan el color rojo.")
        + inf.seccion("2. Evolución de los últimos cinco ejercicios",
                      graf_evol + f'<div style="margin-top:12px">{graf_balance}</div>'
                      + f'<div style="font-size:11.5px;color:#5b6b80;padding:6px 2px 0">'
                      f'Cifra de negocios por ejercicio — {inf.esc(evolucion_txt)}</div>',
                      nota="Cifras tomadas de los apuntes cargados de cada ejercicio.")
        + inf.seccion("3. Cuenta de pérdidas y ganancias (comparativa)", _tabla_pyg(datos),
                      nota="Porcentajes sobre el total de ingresos de explotación del ejercicio.")
        + inf.seccion("4. Balance de situación", _tabla_balance(datos),
                      nota=f"Diferencia activo − (patrimonio neto + pasivo) en {y}: "
                           f"{fmt(datos['cuadre']['activo'] - datos['cuadre']['pasivoPN'])}.")
        + inf.seccion("5. Ventas: evolución mensual", graf_ventas
                      + f'<div style="margin-top:10px">{tabla_ventas}</div>'
                      + f'<div style="margin-top:12px">{"".join(inf.kpis([(f["tercero"][:34], inf.importe(f["saldo"])) for f in datos["clientes"][:4]], columnas=4)) if datos["clientes"] else ""}</div>',
                      nota="Principales clientes por saldo vivo (cuentas 43x y deudores asimilados).")
        + inf.seccion("6. Proveedores", _tabla_terceros("Proveedor", datos["proveedores"],
                                                        "proveedores"),
                      nota="Saldo vivo por acreedor (cuentas 40x). Peso = parte del saldo total.")
        + inf.seccion("7. Tesorería", _tabla_tesoreria(datos)
                      + f'<div style="margin-top:10px">{graf_teso}</div>'
                      + f'<div style="font-size:11.5px;color:#5b6b80;padding:6px 2px 0">'
                      f'Saldo a 31/12/{y}: <b>{fmt(datos["tesoreria"]["saldo"])}</b> · '
                      f'Variación respecto a {y - 1}: <b>{fmt(datos["tesoreria"]["variacion"])}</b>. '
                      f'Cash-flow generado según la cuenta de resultados (resultado + amortizaciones): '
                      f'<b>{fmt(a.get("cashFlow", 0.0))}</b>.</div>',
                      nota="Cargos = entradas de efectivo, abonos = salidas. El cash-flow de la "
                           "cuenta de resultados no incluye las variaciones de circulante.")
        + inf.seccion("8. Partidas pendientes de aplicación (cuenta 555)", _tabla_partidas555(datos),
                      nota="Últimos diez movimientos de la cuenta 555 y su saldo total.")
        + inf.seccion("9. Personal", _tabla_personal(datos)
                      + f'<div style="margin-top:10px">{graf_personal}</div>'
                      + f'<div style="font-size:11.5px;color:#5b6b80;padding:6px 2px 0">'
                      f'Gasto de personal de {y}: <b>{fmt(datos["personal"]["total"])}</b> · '
                      f'{y - 1}: <b>{fmt(datos["personal"]["totalAnterior"])}</b>. '
                      f'Coste medio mensual: <b>{fmt(datos["personal"]["total"] / 12)}</b>.</div>',
                      nota="Cuentas 640 a 649. El detalle por empleado no está en los apuntes.")
        + inf.seccion("10. Ratios (cinco ejercicios)", _tabla_ratios(datos)
                      + f'<div style="margin-top:8px">{inf.kpis([("Prueba ácida", num(datos["ratios"][0]["valores"][-1])), ("Solvencia", num(datos["ratios"][1]["valores"][-1])), ("Endeudamiento", fmt_pct(datos["ratios"][2]["valores"][-1])), ("Garantía", num(datos["ratios"][3]["valores"][-1]))])}</div>'
                      + f'<div style="margin-top:8px">{inf.kpis([("ROE", fmt_pct(datos["ratios"][4]["valores"][-1])), ("ROA", fmt_pct(datos["ratios"][5]["valores"][-1])), ("Cash-flow", inf.importe(a.get("cashFlow", 0.0))), ("Tesorería", inf.importe(a.get("tesoreria", 0.0)))])}</div>',
                      nota="Prueba ácida = (clientes + tesorería) / pasivo corriente · "
                           "Solvencia = activo corriente / pasivo corriente · "
                           "Endeudamiento = (pasivo no corriente + corriente) / activo total · "
                           "Garantía = activo total / recursos ajenos.")
    )

    return inf.envoltura(
        titulo=TITULO,
        subtitulo=f"Ejercicio {y} · serie de cinco ejercicios (hasta {min(datos['anios'])})",
        empresa=datos.get("empresa") or ctx.get("empresa", ""), ejercicio=y, cuerpo=cuerpo,
        interno=INTERNO,
        meta={"Datos": "ERP apiCON (apuntes del ejercicio)",
              "Años reales": ", ".join(str(x) for x in datos["reales"]) or "—",
              "Años repetidos": ", ".join(str(f["year"]) for f in datos["noReales"]) or "ninguno"},
        extra_pie=_nota_anios(datos),
    )


__all__ = ["NOMBRE", "TITULO", "INTERNO", "DESPLAZAMIENTOS", "PARAMETROS",
           "calcular", "informe_html", "metricas_dashboard"]
