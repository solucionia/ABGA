"""Módulo `proyecciones` — REQ-02 Proyecciones financieras.

Portado del nodo Code «Calcular Proyecciones» del workflow de n8n. Aquel nodo hacía una
«regresión lineal ponderada» que en realidad no lo era: mezclaba una media de Y ponderada
por antigüedad con una media de X sin ponderar, de modo que la pendiente no era la de
ningún ajuste real. Aquí se porta el objetivo (tendencia de 4 ejercicios → proyección del
siguiente, con escenarios y reparto temporal) corrigiendo ocho cosas:

1. **Regresión mal construida.** Ahora es un ajuste por mínimos cuadrados ponderado (WLS)
   coherente: pesos de recencia 1..n sobre ambos momentos, R² ponderado y pendiente
   relativa al nivel medio (el original comparaba una pendiente en € con una media en €
   multiplicada por 5 %, lo que ni siquiera es el mismo orden de magnitud).
2. **Años ausentes contaminando el ajuste.** El original pasaba siempre cuatro valores y
   sustituía los ejercicios sin datos por 0, con lo que un año perdido hundía la
   tendencia. Aquí los ejercicios sin líneas se excluyen del ajuste (y se avisa); la
   coordenada X es el año natural, así que los huecos no deforman la pendiente.
3. **Tasa de crecimiento.** El original dividía por `nº de valores válidos − 1`, ignorando
   los huecos. Aquí se anualiza sobre el salto real de años: compuesta (CAGR) cuando la
   serie es positiva, y lineal sobre el primer valor cuando hay signos mezclados.
4. **Recorte a cero.** El `Math.max(0, …)` del original borraba la información de los
   saldos negativos (tesorería en descubierto, resultado de pérdidas, gastos financieros
   con signo contrario). Se conserva el signo en todo el histórico y en los resultados
   proyectados; sólo se acota a cero —avisando— en las magnitudes que por definición no
   pueden ser negativas (ventas, gastos, deudores, acreedores).
5. **Escenarios incompletos.** El original calculaba las tres cifras de resultado con una
   fórmula propia (`Math.max(-ing, rai * 0,75)`) desconectada del resto del PyG. Aquí cada
   escenario se calcula como un PyG completo (EBITDA → EBIT → RAI → impuesto → resultado →
   margen → caja) con la misma cascada que el escenario base.
6. **Ingresos financieros, impuesto y amortización.** El original ignoraba los ingresos
   financieros al calcular el RAI, y proyectaba la amortización con el valor del año en
   curso sin tendencia. Aquí entran en la cascada los tres y la amortización se ajusta por
   tendencia (si hay serie) con el último valor como suelo.
7. **Reparto mensual.** El original repartía el ejercicio siguiente con los pesos del año
   en curso y, si un mes no tenía datos, le asignaba un peso plano 1/12 (y 0 si el año no
   tenía ingresos todavía). Aquí los pesos son factores estacionales reales: la media, por
   mes, del peso de ese mes sobre el total del ejercicio en los años con los 12 meses
   observados. Con eso se reparte el año proyectado y se *completan* los meses que faltan
   del año en curso (gross-up estacional), que es lo que el portal necesita cuando se
   ejecuta en septiembre.
8. **Tesorería.** El original proyectaba el saldo de cierres 57x por regresión sin mirar si
   había datos. En el ERP de ABGA los apuntes de esta empresa no traen movimientos de
   tesorería (570-577) en 2024 ni 2025, así que aquel informe salía con tesorería 0,00 € en
   todos los años. Aquí, si no hay cuentas 57x, se avisa y se informa de la **caja generada
   por explotación** (resultado + amortización, acumulada) mes a mes y por ejercicio, que sí
   es calculable con los datos disponibles.

Mismas agrupaciones de cuentas que `pyg` (se importan de allí) para que la base de la
proyección cuadre con el PyG del portal.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from .. import informes as inf
from ..ledger import (MESES, a_float, comprobar_cuadre, fmt, fmt_pct, mes_de, num,
                      por_mes, saldos_por_cuenta, suma_acreedor, suma_deudor)
from .pyg import (P_AMORTIZACIONES, P_APROVISIONAMIENTOS, P_DEUDORES,
                  P_GASTOS_FINANCIEROS, P_IMPUESTO, P_ING_FINANCIEROS, P_OTROS_GASTOS,
                  P_OTROS_INGRESOS, P_PERSONAL, P_PROVEEDORES, P_TESORERIA, P_VENTAS)

NOMBRE = "proyecciones"
TITULO = "Proyecciones financieras"
INTERNO = False
# Tendencia de los cuatro ejercicios (año, −1, −2, −3) → proyección del siguiente.
DESPLAZAMIENTOS = [0, -1, -2, -3]
PARAMETROS: dict[str, Any] = {
    "tipo_impuesto": 25.0,   # tipo del IS aplicado al RAI proyectado (el ERP no trae la 630)
    "mes_corte": None,       # mes de corte del año en curso; None = deducirlo de los datos
    "factor_ing_optimista": 1.15,
    "factor_gasto_optimista": 0.95,
    "factor_ing_conservador": 0.85,
    "factor_gasto_conservador": 1.05,
}

P_INGRESOS_EXPLOTACION = P_VENTAS + P_OTROS_INGRESOS
P_GASTOS_EXPLOTACION = P_APROVISIONAMIENTOS + P_PERSONAL + P_OTROS_GASTOS
# magnitudes que por definición no pueden ser negativas; sólo aquí se acota a cero
NO_NEGATIVAS = ("ingresos", "ventas", "aprovisionamientos", "gastosPersonal", "otrosGastos",
                "amortizaciones", "deudores", "proveedores")

COLOR_INGRESOS = inf.AZUL
COLOR_GASTOS = "#c98a2b"
COLOR_RESULTADO = inf.POSITIVO
COLOR_TESORERIA = "#6a3fa0"
COLOR_CAJA = "#00838f"


# ---------------------------------------------------------------- magnitudes

def magnitudes(lineas: Sequence, previas: Sequence | None = None) -> dict[str, Any]:
    """PyG y saldos de un ejercicio, con los mismos criterios que el módulo `pyg`.

    Nunca recorta los saldos contrarios (`recortar=False`): un gasto financiero abonado o
    un resultado negativo son información, no ruido.
    """
    s = saldos_por_cuenta(lineas)
    ventas = suma_acreedor(s, P_VENTAS, recortar=False)
    otros_ingresos = suma_acreedor(s, P_OTROS_INGRESOS, recortar=False)
    ingresos = ventas + otros_ingresos
    aprovisionamientos = suma_deudor(s, P_APROVISIONAMIENTOS, recortar=False)
    gastos_personal = suma_deudor(s, P_PERSONAL, recortar=False)
    otros_gastos = suma_deudor(s, P_OTROS_GASTOS, recortar=False)
    amortizaciones = suma_deudor(s, P_AMORTIZACIONES, recortar=False)
    gastos_explotacion = aprovisionamientos + gastos_personal + otros_gastos
    ebitda = ingresos - gastos_explotacion
    ebit = ebitda - amortizaciones
    ingresos_financieros = suma_acreedor(s, P_ING_FINANCIEROS, recortar=False)
    gastos_financieros = suma_deudor(s, P_GASTOS_FINANCIEROS, recortar=False)
    rai = ebit + ingresos_financieros - gastos_financieros
    impuesto = suma_deudor(s, P_IMPUESTO, recortar=False)
    resultado = rai - impuesto
    tesoreria = suma_deudor(s, P_TESORERIA, recortar=False)
    deudores = suma_deudor(s, P_DEUDORES, recortar=False)
    proveedores = suma_acreedor(s, P_PROVEEDORES, recortar=False)
    cash_flow = resultado + amortizaciones

    d_previos: dict[str, float] = {}
    if previas:
        d_previos = magnitudes(previas) if not isinstance(previas, dict) else previas
    else:
        d_previos = {}
    var_deudores = deudores - a_float(d_previos.get("deudores")) if d_previos else 0.0
    var_proveedores = proveedores - a_float(d_previos.get("proveedores")) if d_previos else 0.0
    flujo_operativo = cash_flow - var_deudores + var_proveedores

    def pct(n: float, d: float) -> float:
        return n / d * 100 if d else 0.0

    return {
        "ingresos": round(ingresos, 2), "ventas": round(ventas, 2),
        "otrosIngresos": round(otros_ingresos, 2),
        "aprovisionamientos": round(aprovisionamientos, 2),
        "gastosPersonal": round(gastos_personal, 2), "otrosGastos": round(otros_gastos, 2),
        "gastosExplotacion": round(gastos_explotacion, 2),
        "amortizaciones": round(amortizaciones, 2),
        "ebitda": round(ebitda, 2), "ebit": round(ebit, 2),
        "ingresosFinancieros": round(ingresos_financieros, 2),
        "gastosFinancieros": round(gastos_financieros, 2),
        "rai": round(rai, 2), "impuesto": round(impuesto, 2), "resultado": round(resultado, 2),
        "margenEbitda": round(pct(ebitda, ingresos), 2), "margenNeto": round(pct(resultado, ingresos), 2),
        "tesoreria": round(tesoreria, 2), "deudores": round(deudores, 2),
        "proveedores": round(proveedores, 2), "cashFlow": round(cash_flow, 2),
        "flujoOperativo": round(flujo_operativo, 2),
        "varDeudores": round(var_deudores, 2), "varProveedores": round(var_proveedores, 2),
        "nLineas": len(lineas),
    }


def serie_mensual_completa(lineas: Sequence) -> list[dict[str, Any]]:
    """12 filas por mes: ingresos, gastos, amortización, resultado y saldos acumulados.

    Los saldos de tesorería (57x), deudores (43x) y acreedores (40x-41x) se acumulan mes a
    mes, que es lo que permite reconstruir la caja generada cuando el ERP no trae bancos.
    """
    por_m = por_mes(lineas)
    filas: list[dict[str, Any]] = []
    acum = {"tesoreria": 0.0, "deudores": 0.0, "proveedores": 0.0,
            "resultado": 0.0, "amortizaciones": 0.0}
    for m in range(1, 13):
        ls = por_m.get(m, [])
        saldos = saldos_por_cuenta(ls)
        ingresos = suma_acreedor(saldos, P_INGRESOS_EXPLOTACION, recortar=False)
        gastos = suma_deudor(saldos, P_GASTOS_EXPLOTACION, recortar=False)
        amort = suma_deudor(saldos, P_AMORTIZACIONES, recortar=False)
        ing_fin = suma_acreedor(saldos, P_ING_FINANCIEROS, recortar=False)
        gas_fin = suma_deudor(saldos, P_GASTOS_FINANCIEROS, recortar=False)
        resultado = ingresos - gastos - amort + ing_fin - gas_fin
        acum["tesoreria"] += suma_deudor(saldos, P_TESORERIA, recortar=False)
        acum["deudores"] += suma_deudor(saldos, P_DEUDORES, recortar=False)
        acum["proveedores"] += suma_acreedor(saldos, P_PROVEEDORES, recortar=False)
        acum["resultado"] += resultado
        acum["amortizaciones"] += amort
        filas.append({
            "mes": MESES[m - 1], "mes_num": m, "nLineas": len(ls),
            "ingresos": round(ingresos, 2), "gastos": round(gastos, 2),
            "amortizaciones": round(amort, 2), "resultado": round(resultado, 2),
            "cajaGenerada": round(acum["resultado"] + acum["amortizaciones"], 2),
            "tesoreria": round(acum["tesoreria"], 2),
            "deudores": round(acum["deudores"], 2), "proveedores": round(acum["proveedores"], 2),
        })
    return filas


# ---------------------------------------------------------------- regresión

def regresion(puntos: Sequence[tuple[int, float]], *, pesos: Sequence[float] | None = None,
              proyectar_en: int | None = None, no_negativa: bool = False) -> dict[str, Any]:
    """Ajuste lineal ponderado (WLS) sobre `puntos` = [(año, valor), …].

    Pesos por defecto 1..n (el ejercicio más reciente pesa más, como pretendía el nodo
    original). La coordenada X es el año natural: los ejercicios ausentes no deforman la
    pendiente porque simplemente no entran. Devuelve la proyección para `proyectar_en`
    (por defecto, el año siguiente al último punto) y métricas de fiabilidad.
    """
    validos = [(int(x), a_float(v)) for x, v in puntos if v is not None]
    if not validos:
        return {"proyeccion": 0.0, "proyeccionCruda": 0.0, "pendiente": 0.0, "intercepto": 0.0,
                "r2": 0.0, "n": 0, "tendencia": "SIN DATOS", "tasaCrecimiento": 0.0,
                "fiabilidad": "sin datos", "recortada": False, "primero": None, "ultimo": None}
    x_ultimo = validos[-1][0]
    objetivo = proyectar_en if proyectar_en is not None else x_ultimo + 1
    if len(validos) < 2:
        valor = validos[0][1]
        return {"proyeccion": max(0.0, valor) if no_negativa and valor < 0 else valor,
                "proyeccionCruda": valor, "pendiente": 0.0, "intercepto": valor, "r2": 0.0,
                "n": 1, "tendencia": "ESTABLE", "tasaCrecimiento": 0.0, "fiabilidad": "baja",
                "recortada": bool(no_negativa and valor < 0), "primero": valor, "ultimo": valor}

    xs = [float(x) for x, _ in validos]
    ys = [float(v) for _, v in validos]
    ws = [float(w) for w in (pesos or [i + 1 for i in range(len(validos))])][:len(validos)]
    if len(ws) < len(validos):
        ws = ws + [float(len(validos))] * (len(validos) - len(ws))
    suma_w = sum(ws) or 1.0
    media_x = sum(w * x for w, x in zip(ws, xs)) / suma_w
    media_y = sum(w * y for w, y in zip(ws, ys)) / suma_w
    num = sum(w * (x - media_x) * (y - media_y) for w, x, y in zip(ws, xs, ys))
    den = sum(w * (x - media_x) ** 2 for w, x in zip(ws, xs))
    pendiente = num / den if den else 0.0
    intercepto = media_y - pendiente * media_x
    proyeccion_cruda = intercepto + pendiente * objetivo
    recortada = bool(no_negativa and proyeccion_cruda < 0)
    proyeccion = 0.0 if recortada else proyeccion_cruda

    var_resid = sum(w * (y - (intercepto + pendiente * x)) ** 2 for w, x, y in zip(ws, xs, ys))
    var_total = sum(w * (y - media_y) ** 2 for w, y in zip(ws, ys))
    r2 = 1 - var_resid / var_total if var_total else (1.0 if var_resid == 0 else 0.0)

    rel = pendiente / abs(media_y) if media_y else (1.0 if pendiente else 0.0)
    tendencia = "CRECIENTE" if rel > 0.05 else ("DECRECIENTE" if rel < -0.05 else "ESTABLE")

    primero, ultimo = ys[0], ys[-1]
    salto = max(1, x_ultimo - validos[0][0])
    if primero > 0 and ultimo > 0:
        tasa = ((ultimo / primero) ** (1 / salto) - 1) * 100
    elif primero != 0:
        tasa = (ultimo - primero) / salto / abs(primero) * 100
    else:
        tasa = 0.0

    n = len(validos)
    fiabilidad = "alta" if n >= 4 and r2 >= 0.5 else ("media" if n >= 3 else "baja")
    return {"proyeccion": round(proyeccion, 2), "proyeccionCruda": round(proyeccion_cruda, 2),
            "pendiente": round(pendiente, 2), "intercepto": round(intercepto, 2),
            "r2": round(max(0.0, min(1.0, r2)), 4), "n": n, "tendencia": tendencia,
            "tasaCrecimiento": round(tasa, 2), "fiabilidad": fiabilidad, "recortada": recortada,
            "primero": round(primero, 2), "ultimo": round(ultimo, 2),
            "objetivo": objetivo, "pesos": [int(w) if float(w).is_integer() else w for w in ws]}


# ---------------------------------------------------------------- PyG proyectado

def _pyg_proyectado(ingresos: float, aprovisionamientos: float, gastos_personal: float,
                    otros_gastos: float, amortizaciones: float, ingresos_financieros: float,
                    gastos_financieros: float, tipo_impuesto: float) -> dict[str, Any]:
    """Cascada completa del PyG proyectado; el impuesto sólo grava un RAI positivo."""
    gastos_explotacion = aprovisionamientos + gastos_personal + otros_gastos
    ebitda = ingresos - gastos_explotacion
    ebit = ebitda - amortizaciones
    rai = ebit + ingresos_financieros - gastos_financieros
    impuesto = rai * tipo_impuesto / 100 if rai > 0 else 0.0
    resultado = rai - impuesto
    return {
        "ingresos": round(ingresos, 2), "aprovisionamientos": round(aprovisionamientos, 2),
        "gastosPersonal": round(gastos_personal, 2), "otrosGastos": round(otros_gastos, 2),
        "gastosExplotacion": round(gastos_explotacion, 2),
        "amortizaciones": round(amortizaciones, 2), "ebitda": round(ebitda, 2),
        "ebit": round(ebit, 2), "ingresosFinancieros": round(ingresos_financieros, 2),
        "gastosFinancieros": round(gastos_financieros, 2), "rai": round(rai, 2),
        "impuesto": round(impuesto, 2), "resultado": round(resultado, 2),
        "margenEbitda": round(ebitda / ingresos * 100, 2) if ingresos else 0.0,
        "margenNeto": round(resultado / ingresos * 100, 2) if ingresos else 0.0,
        "cashFlow": round(resultado + amortizaciones, 2),
    }


# ---------------------------------------------------------------- estacionalidad

def _factores_estacionales(por_anio: dict[int, Sequence], anios: Sequence[int]) -> tuple[list[float], list[float], int]:
    """Peso de cada mes sobre el total del ejercicio, promediado en los años completos.

    Sólo se usan ejercicios con los 12 meses observados: así el factor de un mes sin datos
    en el año en curso sale del histórico (que es justo lo que el nodo original perdía al
    asignarle 1/12 plano). Si no hay ningún año completo, se reparte a partes iguales.
    """
    acc_ing = [0.0] * 12
    acc_gas = [0.0] * 12
    completos = 0
    for a in anios:
        filas = serie_mensual_completa(por_anio.get(a) or [])
        if any(f["nLineas"] == 0 for f in filas):
            continue
        total_ing = sum(f["ingresos"] for f in filas)
        total_gas = sum(f["gastos"] for f in filas)
        if total_ing <= 0:
            continue
        completos += 1
        for i, f in enumerate(filas):
            acc_ing[i] += f["ingresos"] / total_ing
            acc_gas[i] += f["gastos"] / total_gas if total_gas else 1 / 12
    if not completos:
        return [1 / 12] * 12, [1 / 12] * 12, 0
    fact_ing = [v / completos for v in acc_ing]
    fact_gas = [v / completos for v in acc_gas]
    for factores in (fact_ing, fact_gas):
        total = sum(factores) or 1.0
        for i in range(12):
            factores[i] = factores[i] / total
    return fact_ing, fact_gas, completos


def meses_restantes(anio: int, ctx: dict, por_anio: dict[int, Sequence]) -> dict[str, Any]:
    """Detecta si el ejercicio en curso está incompleto y qué meses quedan por proyectar."""
    lineas = por_anio.get(anio) or []
    filas = serie_mensual_completa(lineas)
    observados = [f["mes_num"] for f in filas if f["nLineas"] > 0]
    ultimo_observado = max(observados) if observados else 0
    corte = ctx.get("mes_corte")
    corte = int(corte) if corte not in (None, "", 0) else None
    if corte is None:
        corte = ultimo_observado if len(observados) < 12 else 12
    parcial = corte < 12
    return {"mesCorte": corte, "ultimoMesConDatos": ultimo_observado,
            "mesesObservados": len(observados), "esParcial": parcial,
            "mesesProyectados": list(range(corte + 1, 13)) if parcial else [],
            "mesesProyectadosN": 12 - corte if parcial else 0,
            "filas": filas}


# ---------------------------------------------------------------- cálculo

def _normalizar_entrada(por_anio: Any, ctx: dict) -> dict[int, list]:
    """Acepta `{año: [Linea]}` (contrato) o una lista suelta de líneas del año pedido."""
    if isinstance(por_anio, dict):
        salida: dict[int, list] = {}
        for k, v in por_anio.items():
            try:
                salida[int(k)] = list(v or [])
            except (TypeError, ValueError):
                continue
        return salida
    if isinstance(por_anio, (list, tuple)):
        anio = int(ctx.get("year") or 0)
        return {anio: list(por_anio)}
    return {}


def calcular(por_anio: Any, ctx: dict | None = None) -> dict[str, Any]:
    """Series comparativas, tendencias, escenarios y proyección mensual, en números."""
    ctx = dict(ctx or {})
    por_anio = _normalizar_entrada(por_anio, ctx)
    anios_presentes = sorted(a for a, ls in por_anio.items() if ls)
    if not anios_presentes:
        return {"avisos": ["No hay apuntes cargados: no puede calcularse ninguna proyección."],
                "alertas": [{"nivel": "ALTA", "mensaje": "Sin datos de partida."}],
                "nivelGlobal": "ALTA", "year": None, "yearProyectado": None, "disponible": False}

    year = int(ctx.get("year") or max(anios_presentes))
    year_proy = year + 1
    anios = sorted({year + d for d in DESPLAZAMIENTOS})
    tipo_impuesto = a_float(ctx.get("tipo_impuesto", PARAMETROS["tipo_impuesto"]))
    f_opt_ing = a_float(ctx.get("factor_ing_optimista", PARAMETROS["factor_ing_optimista"]))
    f_opt_gas = a_float(ctx.get("factor_gasto_optimista", PARAMETROS["factor_gasto_optimista"]))
    f_con_ing = a_float(ctx.get("factor_ing_conservador", PARAMETROS["factor_ing_conservador"]))
    f_con_gas = a_float(ctx.get("factor_gasto_conservador", PARAMETROS["factor_gasto_conservador"]))

    avisos: list[str] = []
    alertas: list[dict[str, str]] = []
    faltan = [a for a in anios if not por_anio.get(a)]

    # ---------- series comparativas ----------
    historico: list[dict[str, Any]] = []
    previo: dict[str, Any] | None = None
    for a in anios:
        lineas = por_anio.get(a)
        if not lineas:
            historico.append({"year": a, "sinDatos": True, "ingresos": None, "resultado": None,
                              "tesoreria": None, "ebitda": None, "nLineas": 0})
            previo = None
            continue
        m = magnitudes(lineas, previo)
        m["year"] = a
        m["sinDatos"] = False
        m["varIngresos"] = ((m["ingresos"] - previo["ingresos"]) / abs(previo["ingresos"]) * 100
                            if previo and previo.get("ingresos") else 0.0)
        cuadre = comprobar_cuadre(lineas)
        m["descuadre"] = cuadre["descuadre"]
        historico.append(m)
        previo = m

    if faltan:
        avisos.append("Los ejercicios " + ", ".join(str(a) for a in faltan)
                      + " no tienen apuntes cargados: la tendencia se ajusta sólo con los "
                        "ejercicios disponibles (no se rellenan con ceros).")
    con_datos = [h for h in historico if not h["sinDatos"]]
    if len(con_datos) < 2:
        avisos.append("Con un único ejercicio no hay tendencia: la proyección repite el último "
                      "dato disponible y la fiabilidad es baja.")
    descuadres = [h for h in historico if not h["sinDatos"] and abs(h.get("descuadre") or 0) > 0.01]
    if descuadres:
        avisos.append("El ejercicio " + ", ".join(str(h["year"]) for h in descuadres)
                      + " no cuadra (ΣDebe ≠ ΣHaber): los asientos cargados están incompletos, "
                        "así que las magnitudes de ese año son parciales.")

    # ---------- regresiones ----------
    claves = ("ingresos", "aprovisionamientos", "gastosPersonal", "otrosGastos", "amortizaciones",
              "ingresosFinancieros", "gastosFinancieros", "tesoreria", "deudores", "proveedores",
              "resultado", "cashFlow")
    tendencias: dict[str, dict[str, Any]] = {}
    for clave in claves:
        puntos = [(h["year"], h[clave]) for h in historico if not h["sinDatos"]]
        # la amortización no sigue una tendencia de mercado: se proyecta con el último dato
        # como suelo para no quedarse sin dotación cuando el ajuste sale a la baja
        r = regresion(puntos, no_negativa=clave in NO_NEGATIVAS)
        if clave == "amortizaciones" and puntos:
            ultimo = a_float(puntos[-1][1])
            if r["proyeccion"] < ultimo:
                r["proyeccion"] = round(ultimo, 2)
                r["proyeccionCruda"] = max(r["proyeccionCruda"], round(ultimo, 2))
                r["nota"] = "Proyectada con el último ejercicio como suelo."
        tendencias[clave] = r

    if tendencias["ingresos"]["recortada"]:
        avisos.append("La tendencia de ingresos proyecta un valor negativo; se acota a cero "
                      "(el informe original ya lo hacía) y se marca como alerta.")

    hay_tesoreria = any(a_float(h.get("tesoreria")) != 0 for h in con_datos)
    if not hay_tesoreria:
        avisos.append("El ERP no devuelve movimientos de tesorería (cuentas 570-577) en los "
                      "ejercicios cargados: el saldo bancario proyectado no es reconstruible. "
                      "Se informa de la caja generada por explotación (resultado + amortización).")

    # ---------- PyG del ejercicio proyectado (escenario base) ----------
    t = tendencias
    amort_proy = t["amortizaciones"]["proyeccion"]
    fin_proy = (t["ingresosFinancieros"]["proyeccion"], t["gastosFinancieros"]["proyeccion"])
    base = _pyg_proyectado(t["ingresos"]["proyeccion"], t["aprovisionamientos"]["proyeccion"],
                           t["gastosPersonal"]["proyeccion"], t["otrosGastos"]["proyeccion"],
                           amort_proy, fin_proy[0], fin_proy[1], tipo_impuesto)

    # ---------- escenarios ----------
    gastos_expl_proy = (t["aprovisionamientos"]["proyeccion"] + t["gastosPersonal"]["proyeccion"]
                        + t["otrosGastos"]["proyeccion"])
    tesoreria_proy = t["tesoreria"]["proyeccion"]
    escenarios: dict[str, dict[str, Any]] = {}
    for nombre, f_ing, f_gas in (("conservador", f_con_ing, f_con_gas),
                                 ("base", 1.0, 1.0),
                                 ("optimista", f_opt_ing, f_opt_gas)):
        ing = t["ingresos"]["proyeccion"] * f_ing
        gas = gastos_expl_proy * f_gas
        escala = gas / (gastos_expl_proy or 1.0)
        pyg = _pyg_proyectado(ing, t["aprovisionamientos"]["proyeccion"] * escala,
                              t["gastosPersonal"]["proyeccion"] * escala,
                              t["otrosGastos"]["proyeccion"] * escala,
                              amort_proy, fin_proy[0], fin_proy[1], tipo_impuesto)
        # la amortización es la misma en los tres escenarios: el flujo de caja sólo cambia
        # con el resultado, así que la tesorería estimada se desplaza en la misma cuantía
        pyg["cajaGenerada"] = round(pyg["cashFlow"], 2)
        pyg["tesoreriaEstimada"] = round(tesoreria_proy + (pyg["resultado"] - base["resultado"]), 2)
        pyg["factorIngresos"] = f_ing
        pyg["factorGastos"] = f_gas
        pyg["variacionResultado"] = round(pyg["resultado"] - base["resultado"], 2)
        pyg["esBase"] = nombre == "base"
        escenarios[nombre] = pyg

    # ---------- estacionalidad y meses restantes ----------
    fact_ing, fact_gas, anios_completos = _factores_estacionales(por_anio, anios)
    curso = meses_restantes(year, ctx, por_anio)
    filas_mes = curso["filas"]
    obs = [f for f in filas_mes if f["nLineas"] > 0]
    corte = curso["mesCorte"]
    ing_ytd = sum(f["ingresos"] for f in filas_mes[:corte])
    gas_ytd = sum(f["gastos"] for f in filas_mes[:corte])
    peso_ing_obs = sum(fact_ing[:corte]) or 1.0
    peso_gas_obs = sum(fact_gas[:corte]) or 1.0
    ing_est_anio = ing_ytd / peso_ing_obs if obs else t["ingresos"]["proyeccion"]
    gas_est_anio = gas_ytd / peso_gas_obs if obs else t["aprovisionamientos"]["proyeccion"]

    caja_acum = filas_mes[corte - 1]["cajaGenerada"] if corte else 0.0
    tesoreria_base = filas_mes[corte - 1]["tesoreria"] if corte else 0.0
    for f in filas_mes:
        m = f["mes_num"]
        if m <= corte:
            f["proyectado"] = False
        else:
            f["proyectado"] = True
            f["ingresos"] = round(ing_est_anio * fact_ing[m - 1], 2)
            f["gastos"] = round(gas_est_anio * fact_gas[m - 1], 2)
            f["resultado"] = round(f["ingresos"] - f["gastos"] - f["amortizaciones"], 2)
            caja_acum += f["resultado"] + f["amortizaciones"]
            tesoreria_base += f["resultado"] + f["amortizaciones"]
            f["cajaGenerada"] = round(caja_acum, 2)
            f["tesoreria"] = round(tesoreria_base, 2)
    cierre_estimado = {
        "ingresos": round(sum(f["ingresos"] for f in filas_mes), 2),
        "gastos": round(sum(f["gastos"] for f in filas_mes), 2),
        "resultado": round(sum(f["resultado"] for f in filas_mes), 2),
        "cajaGenerada": round(caja_acum, 2),
        "mesesProyectados": curso["mesesProyectadosN"],
    }
    # reparto mensual del ejercicio proyectado con los mismos factores estacionales
    mensual_proyectado = []
    for m in range(1, 13):
        ing = base["ingresos"] * fact_ing[m - 1]
        gas = base["gastosExplotacion"] * fact_gas[m - 1]
        mensual_proyectado.append({
            "mes": MESES[m - 1], "mes_num": m, "pesoIngresos": round(fact_ing[m - 1] * 100, 2),
            "pesoGastos": round(fact_gas[m - 1] * 100, 2),
            "ingresos": round(ing, 2), "gastos": round(gas, 2),
            "resultado": round(ing - gas - base["amortizaciones"] / 12, 2),
        })
    trimestral = []
    for q in range(4):
        trozo = mensual_proyectado[q * 3:(q + 1) * 3]
        ingresos_q = sum(x["ingresos"] for x in trozo)
        gastos_q = sum(x["gastos"] for x in trozo)
        res_q = sum(x["resultado"] for x in trozo)
        trimestral.append({
            "trimestre": f"T{q + 1}", "ingresos": round(ingresos_q, 2), "gastos": round(gastos_q, 2),
            "resultado": round(res_q, 2),
            "margen": round(res_q / ingresos_q * 100, 2) if ingresos_q else 0.0,
            "peso": round(ingresos_q / base["ingresos"] * 100, 2) if base["ingresos"] else 0.0,
        })

    # ---------- comparativa con el año en curso ----------
    actual = next((h for h in historico if h.get("year") == year and not h["sinDatos"]), None)
    if actual:
        base["varIngresos"] = (round((base["ingresos"] - actual["ingresos"]) / abs(actual["ingresos"]) * 100, 2)
                               if actual["ingresos"] else 0.0)
        base["varResultado"] = (round((base["resultado"] - actual["resultado"]) / abs(actual["resultado"]) * 100, 2)
                                if actual["resultado"] else 0.0)
        base["varEbitda"] = (round((base["ebitda"] - actual["ebitda"]) / abs(actual["ebitda"]) * 100, 2)
                             if actual["ebitda"] else 0.0)
    else:
        base["varIngresos"] = base["varResultado"] = base["varEbitda"] = 0.0

    # ---------- alertas ----------
    ti = t["ingresos"]
    tp = t["gastosPersonal"]
    if ti["tendencia"] == "DECRECIENTE":
        alertas.append({"nivel": "ALTA", "mensaje":
                        f"Tendencia de ingresos decreciente ({fmt_pct(ti['tasaCrecimiento'])}/año). "
                        f"Se proyecta una cifra de {fmt(ti['proyeccion'])} en {year_proy}."})
    if tp["tendencia"] == "CRECIENTE" and tp["tasaCrecimiento"] > 10:
        alertas.append({"nivel": "MEDIA", "mensaje":
                        f"Gastos de personal en crecimiento acelerado "
                        f"({fmt_pct(tp['tasaCrecimiento'])}/año) sobre una estructura de "
                        f"{fmt(tp['proyeccion'])}."})
    if base["ingresos"] > 0 and base["margenNeto"] < 5:
        alertas.append({"nivel": "MEDIA", "mensaje":
                        f"Margen neto proyectado bajo ({fmt_pct(base['margenNeto'])}). "
                        "Margen de seguridad reducido."})
    if hay_tesoreria and t["tesoreria"]["tendencia"] == "DECRECIENTE":
        alertas.append({"nivel": "ALTA", "mensaje":
                        "Tesorería con tendencia decreciente: posible tensión de liquidez."})
    if not hay_tesoreria:
        alertas.append({"nivel": "MEDIA", "mensaje":
                        "Sin cuentas de tesorería (570-577) en el ERP: la liquidez no puede "
                        "proyectarse por saldos; use la caja generada como aproximación."})
    if base["resultado"] < 0:
        alertas.append({"nivel": "ALTA", "mensaje":
                        f"El escenario base proyecta pérdidas de {fmt(abs(base['resultado']))} "
                        f"en {year_proy}: el resultado del año en curso no sostiene la estructura."})
    if escenarios["conservador"]["resultado"] < 0 <= base["resultado"]:
        alertas.append({"nivel": "MEDIA", "mensaje":
                        "El escenario conservador entra en pérdidas: conviene revisar el "
                        "punto de equilibrio antes de comprometer gastos."})
    if amort_proy == 0 and not any(a_float(h.get("amortizaciones")) for h in con_datos):
        alertas.append({"nivel": "INFO", "mensaje":
                        "No hay dotaciones a la amortización (68x) contabilizadas en los "
                        "ejercicios cargados: EBIT y EBITDA coinciden."})
    if t["ingresos"]["n"] < 2:
        alertas.append({"nivel": "ALTA", "mensaje":
                        "Menos de dos ejercicios con datos: no hay tendencia calculable."})
    elif t["ingresos"]["n"] < 4 or ti["fiabilidad"] == "baja":
        alertas.append({"nivel": "INFO", "mensaje":
                        f"La tendencia se ajusta con {ti['n']} ejercicio(s) (R²={num(ti['r2'])}) "
                        "en lugar de los cuatro previstos."})
    if curso["esParcial"]:
        alertas.append({"nivel": "INFO", "mensaje":
                        f"El ejercicio {year} está incompleto (datos hasta "
                        f"{MESES[curso['ultimoMesConDatos'] - 1] if curso['ultimoMesConDatos'] else 'sin datos'}"
                        f"); se proyectan los {curso['mesesProyectadosN']} meses restantes."})
    if not alertas:
        alertas.append({"nivel": "INFO", "mensaje":
                        "Proyecciones estables. Sin alertas relevantes para el próximo ejercicio."})
    avisos.extend(a["mensaje"] for a in alertas if a["nivel"] in {"ALTA", "MEDIA"}
                  and a["mensaje"] not in avisos)

    nivel_global = ("ALTA" if any(a["nivel"] == "ALTA" for a in alertas)
                    else "MEDIA" if any(a["nivel"] == "MEDIA" for a in alertas) else "INFO")

    return {
        "disponible": True,
        "year": year, "yearProyectado": year_proy, "anios": anios,
        "aniosConDatos": [h["year"] for h in con_datos],
        "historico": historico, "tendencias": tendencias, "magnitudesActual": actual,
        "proyeccionBase": base, "escenarios": escenarios,
        "mesEnCurso": filas_mes, "mesCorte": corte, "esParcial": curso["esParcial"],
        "mesesProyectadosN": curso["mesesProyectadosN"],
        "factorEstacionalIngresos": [round(v * 100, 2) for v in fact_ing],
        "mesMensualProyectado": mensual_proyectado, "trimestralProyectado": trimestral,
        "aniosCompletosEstacionalidad": anios_completos,
        "cierreEstimadoAnioEnCurso": cierre_estimado,
        "hayTesoreria": hay_tesoreria, "tesoreriaProyectada": tesoreria_proy,
        "tipoImpuesto": tipo_impuesto, "nivelGlobal": nivel_global,
        "alertas": alertas, "avisos": avisos,
    }


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    """KPIs para el panel: escenario base, escenarios alternativos y calidad del ajuste."""
    if not datos.get("disponible"):
        return {"disponible": False, "nivelGlobal": datos.get("nivelGlobal", "ALTA")}
    base = datos["proyeccionBase"]
    esc = datos["escenarios"]
    ti = datos["tendencias"]["ingresos"]
    return {
        "disponible": True,
        "yearProyectado": datos["yearProyectado"],
        "ingresosProyectados": base["ingresos"],
        "resultadoProyectado": base["resultado"],
        "ebitdaProyectado": base["ebitda"],
        "margenProyectado": base["margenNeto"],
        "tesoreriaProyectada": datos["tesoreriaProyectada"] if datos["hayTesoreria"] else None,
        "cajaGeneradaProyectada": base["cashFlow"],
        "resultadoConservador": esc["conservador"]["resultado"],
        "resultadoOptimista": esc["optimista"]["resultado"],
        "ingresosConservador": esc["conservador"]["ingresos"],
        "ingresosOptimista": esc["optimista"]["ingresos"],
        "tendenciaIngresos": ti["tendencia"],
        "tasaCrecimientoIngresos": ti["tasaCrecimiento"],
        "varIngresosProy": base.get("varIngresos", 0.0),
        "varResultadoProy": base.get("varResultado", 0.0),
        "fiabilidadAjuste": ti["fiabilidad"],
        "r2Ingresos": ti["r2"],
        "nivelGlobal": datos["nivelGlobal"],
        "nAlertas": len(datos["alertas"]),
        "esParcial": datos["esParcial"],
        "mesesProyectados": datos["mesesProyectadosN"],
    }


# ---------------------------------------------------------------- informe

def _tabla_historico(datos: dict[str, Any]) -> str:
    filas = []
    for h in datos["historico"]:
        etiqueta = f"{h['year']} (sin datos)" if h["sinDatos"] else str(h["year"])
        if h["sinDatos"]:
            filas.append([etiqueta] + ["—"] * 6)
            continue
        filas.append([
            etiqueta, inf.importe(h["ingresos"]), inf.importe(-h["gastosExplotacion"]),
            inf.importe(h["ebitda"]), inf.importe(h["resultado"]),
            inf.importe(h["tesoreria"]) if datos["hayTesoreria"] else inf.importe(h["cashFlow"]),
            fmt_pct(h["varIngresos"]) if h.get("varIngresos") else "—",
        ])
    ultima = "Tesorería" if datos["hayTesoreria"] else "Caja generada"
    return inf.tabla(
        ["Ejercicio", "Ingresos", "Gastos explot.", "EBITDA", "Resultado neto", ultima,
         "Var. ingresos"],
        filas, anchos=["12%", "15%", "15%", "14%", "15%", "15%", "12%"],
    )


def _tabla_tendencias(datos: dict[str, Any]) -> str:
    etiquetas = [
        ("ingresos", "Ingresos de explotación"), ("aprovisionamientos", "Aprovisionamientos"),
        ("gastosPersonal", "Gastos de personal"), ("otrosGastos", "Otros gastos de explotación"),
        ("amortizaciones", "Amortización del inmovilizado"),
        ("gastosFinancieros", "Gastos financieros"),
        ("resultado", "Resultado del ejercicio"),
        ("tesoreria", "Tesorería (saldos 57x)") if datos["hayTesoreria"]
        else ("cashFlow", "Caja generada (resultado + amortización)"),
    ]
    filas = []
    for clave, etiqueta in etiquetas:
        t = datos["tendencias"][clave]
        if not t["n"]:
            filas.append([etiqueta] + ["—"] * 5)
            continue
        filas.append([
            etiqueta, inf.importe(t["proyeccion"]) if t["n"] > 1 else inf.importe(t["ultimo"]),
            t["tendencia"], fmt_pct(t["tasaCrecimiento"]), num(t["r2"]), str(t["n"]),
        ])
    return inf.tabla(
        ["Magnitud", f"Proyección {datos['yearProyectado']}", "Tendencia", "Tasa anual",
         "R² (0-1)", "Años"],
        filas, anchos=["34%", "20%", "15%", "15%", "8%", "8%"],
    )


def _tabla_pyg_proyectado(datos: dict[str, Any]) -> str:
    base = datos["proyeccionBase"]
    actual = datos.get("magnitudesActual") or {}
    totales_pyg = {"Resultado bruto de explotación (EBITDA)",
                   "Resultado de explotación (EBIT)",
                   "Resultado antes de impuestos (RAI)",
                   "Resultado del ejercicio"}
    partidas = [
        ("Importe neto de la cifra de negocios", "ingresos", 1),
        ("Aprovisionamientos", "aprovisionamientos", -1),
        ("Gastos de personal", "gastosPersonal", -1),
        ("Otros gastos de explotación", "otrosGastos", -1),
        ("Resultado bruto de explotación (EBITDA)", "ebitda", 1),
        ("Amortización del inmovilizado", "amortizaciones", -1),
        ("Resultado de explotación (EBIT)", "ebit", 1),
        ("Ingresos financieros", "ingresosFinancieros", 1),
        ("Gastos financieros", "gastosFinancieros", -1),
        ("Resultado antes de impuestos (RAI)", "rai", 1),
        (f"Impuesto sobre sociedades ({num(datos['tipoImpuesto'])}%)", "impuesto", -1),
        ("Resultado del ejercicio", "resultado", 1),
    ]
    filas = []
    for etiqueta, clave, signo in partidas:
        valor = signo * base[clave]
        anterior = signo * a_float(actual.get(clave)) if actual else None
        var = "—"
        if anterior:
            var = fmt_pct((valor - anterior) / abs(anterior) * 100)
        negrita = "font-weight:bold" if etiqueta in totales_pyg else "normal"
        etiqueta_html = (f'<span style="{negrita}">{inf.esc(etiqueta)}</span>')
        filas.append([etiqueta_html, inf.importe(anterior) if actual else "—",
                      inf.importe(valor, con_signo=etiqueta in totales_pyg), var])
    return inf.tabla(
        ["Cuenta de pérdidas y ganancias proyectada", f"{datos['year']} (actual)",
         f"{datos['yearProyectado']} (proyección)", "Variación"],
        filas, anchos=["44%", "19%", "21%", "16%"],
    )


def _tabla_escenarios(datos: dict[str, Any]) -> str:
    esc = datos["escenarios"]
    nombres = [("conservador", "Conservador"), ("base", "Base"), ("optimista", "Optimista")]
    filas = []
    for clave, etiqueta in nombres:
        e = esc[clave]
        hipotesis = (f"{num(e['factorIngresos'])}× ingresos · {num(e['factorGastos'])}× gastos"
                     if not e["esBase"] else "Tendencia ajustada (escenario central)")
        filas.append([
            etiqueta, hipotesis, inf.importe(e["ingresos"]), inf.importe(e["ebitda"]),
            inf.importe(e["resultado"]), fmt_pct(e["margenNeto"]),
            inf.importe(e["cajaGenerada"]),
        ])
    return inf.tabla(
        ["Escenario", "Hipótesis", "Ingresos", "EBITDA", "Resultado neto", "Margen", "Caja generada"],
        filas, anchos=["13%", "25%", "14%", "13%", "14%", "9%", "12%"],
    )


def _tabla_mensual_curso(datos: dict[str, Any]) -> str:
    filas = []
    for f in datos["mesEnCurso"]:
        marca = "proyección" if f["proyectado"] else ("real" if f["nLineas"] else "sin datos")
        filas.append([
            f["mes"], marca, inf.importe(f["ingresos"]), inf.importe(-f["gastos"]),
            inf.importe(f["resultado"]),
            inf.importe(f["tesoreria"]) if datos["hayTesoreria"] else inf.importe(f["cajaGenerada"]),
        ])
    ultima = "Saldo tesorería" if datos["hayTesoreria"] else "Caja generada"
    return inf.tabla(
        ["Mes", "Origen", "Ingresos", "Gastos", "Resultado", ultima],
        filas, anchos=["9%", "13%", "19%", "19%", "20%", "20%"],
    )


def _tabla_mensual_proyectado(datos: dict[str, Any]) -> str:
    filas = []
    for f in datos["mesMensualProyectado"]:
        filas.append([f["mes"], fmt_pct(f["pesoIngresos"]), inf.importe(f["ingresos"]),
                      inf.importe(-f["gastos"]), inf.importe(f["resultado"])])
    return inf.tabla(
        ["Mes", "Peso estacional", "Ingresos", "Gastos", "Resultado"],
        filas, anchos=["14%", "20%", "22%", "22%", "22%"],
    )


def _tabla_trimestral(datos: dict[str, Any]) -> str:
    filas = [[q["trimestre"], inf.importe(q["ingresos"]), inf.importe(-q["gastos"]),
              inf.importe(q["resultado"]), fmt_pct(q["margen"]), fmt_pct(q["peso"])]
             for q in datos["trimestralProyectado"]]
    return inf.tabla(["Trimestre", "Ingresos", "Gastos", "Resultado", "Margen", "% del año"],
                     filas, anchos=["16%", "20%", "20%", "20%", "12%", "12%"])


def informe_html(datos: dict[str, Any], ctx: dict | None = None, *, empresa: str = "",
                 year: int | None = None) -> str:
    """HTML obligatorio (empieza por `<div`): histórico, tendencias, escenarios y mes a mes."""
    ctx = dict(ctx or {})
    empresa = ctx.get("empresa") or empresa or ""
    year = int(year or ctx.get("year") or datos.get("year") or 0)
    if not datos.get("disponible"):
        cuerpo = inf.aviso("No hay apuntes cargados para este ejercicio: no puede calcularse "
                           "ninguna proyección.", tipo="error", titulo="Sin datos")
        return inf.envoltura(titulo=TITULO, subtitulo="Sin datos", cuerpo=cuerpo,
                             empresa=empresa, ejercicio=year or "",
                             meta={"Origen": "ERP apiCON"})

    year_proy = datos["yearProyectado"]
    base = datos["proyeccionBase"]
    esc = datos["escenarios"]
    ti = datos["tendencias"]["ingresos"]

    kpis = [
        ("Ingresos proyectados", inf.importe(base["ingresos"])),
        ("Resultado proyectado", inf.importe(base["resultado"], con_signo=True)),
        ("Margen neto", fmt_pct(base["margenNeto"])),
        ("Caja generada", inf.importe(base["cashFlow"])),
        (f"Tesorería a cierre {year_proy}",
         inf.importe(datos["tesoreriaProyectada"]) if datos["hayTesoreria"]
         else '<span style="font-size:12px;color:#b26a00">sin cuentas 57x</span>'),
        ("Tendencia de ingresos", f'{ti["tendencia"].title()} ({fmt_pct(ti["tasaCrecimiento"])}/año)'),
        ("Escenario conservador", inf.importe(esc["conservador"]["resultado"], con_signo=True)),
        ("Escenario optimista", inf.importe(esc["optimista"]["resultado"], con_signo=True)),
    ]

    bloques_avisos = "".join(
        inf.aviso(a["mensaje"], tipo={"ALTA": "error", "MEDIA": "alerta", "INFO": "info"}.get(a["nivel"], "info"),
                  titulo={"ALTA": "Alerta alta", "MEDIA": "Alerta media", "INFO": "Nota"}.get(a["nivel"], "Nota"))
        for a in datos["alertas"])

    historico = [h for h in datos["historico"] if not h["sinDatos"]]
    categorias = [str(h["year"]) for h in historico] + [f"{year_proy} (proy)"]
    grafico_historico = inf.lineas_svg(
        categorias,
        [
            {"nombre": "Ingresos", "color": COLOR_INGRESOS,
             "valores": [h["ingresos"] for h in historico] + [base["ingresos"]]},
            {"nombre": "Resultado neto", "color": COLOR_RESULTADO,
             "valores": [h["resultado"] for h in historico] + [base["resultado"]]},
            {"nombre": "Caja generada", "color": COLOR_CAJA,
             "valores": [h["cashFlow"] for h in historico] + [base["cashFlow"]]},
        ],
        titulo=f"Evolución hasta {year} y proyección de {year_proy}",
    )
    grafico_escenarios = inf.barras_svg(
        ["Conservador", "Base", "Optimista"],
        [
            {"nombre": "Ingresos", "color": COLOR_INGRESOS,
             "valores": [esc["conservador"]["ingresos"], esc["base"]["ingresos"],
                         esc["optimista"]["ingresos"]]},
            {"nombre": "Resultado neto", "color": COLOR_RESULTADO,
             "valores": [esc["conservador"]["resultado"], esc["base"]["resultado"],
                         esc["optimista"]["resultado"]]},
        ],
        alto=180, titulo=f"Escenarios para {year_proy}",
    )
    grafico_mensual = inf.barras_svg(
        [f["mes"] for f in datos["mesEnCurso"]],
        [
            {"nombre": "Ingresos", "color": COLOR_INGRESOS,
             "valores": [f["ingresos"] for f in datos["mesEnCurso"]]},
            {"nombre": "Gastos", "color": COLOR_GASTOS,
             "valores": [f["gastos"] for f in datos["mesEnCurso"]]},
        ],
        alto=180, titulo=f"Mes a mes de {year} (los meses sin datos van proyectados)",
    )
    grafico_caja = inf.lineas_svg(
        [f["mes"] for f in datos["mesEnCurso"]],
        [{"nombre": "Saldo de tesorería" if datos["hayTesoreria"] else "Caja generada acumulada",
          "color": COLOR_TESORERIA if datos["hayTesoreria"] else COLOR_CAJA,
          "valores": [f["tesoreria"] if datos["hayTesoreria"] else f["cajaGenerada"]
                      for f in datos["mesEnCurso"]]}],
        titulo=f"Liquidez acumulada de {year}",
    )
    grafico_estacional = inf.barras_svg(
        [f["mes"] for f in datos["mesMensualProyectado"]],
        [
            {"nombre": "Ingresos", "color": COLOR_INGRESOS,
             "valores": [f["ingresos"] for f in datos["mesMensualProyectado"]]},
            {"nombre": "Gastos", "color": COLOR_GASTOS,
             "valores": [f["gastos"] for f in datos["mesMensualProyectado"]]},
        ],
        alto=180, titulo=f"Reparto mensual estimado de {year_proy}",
    )

    barra_tendencia = inf.barra_pct(
        min(100.0, max(0.0, 100 - abs(ti["tasaCrecimiento"]))),
        etiqueta=f"Sostenibilidad de la tendencia de ingresos "
                 f"({ti['tendencia'].lower()}, R²={num(ti['r2'])}, {ti['n']} ejercicio(s))")

    meta = {
        "Origen": "ERP apiCON (apuntes por ejercicio)",
        "Método": "Regresión lineal ponderada (pesos 1..n) sobre los ejercicios disponibles",
        "Ejercicios": ", ".join(str(a) for a in datos["aniosConDatos"]),
        "Calidad": f"fiabilidad {ti['fiabilidad']} (R²={num(ti['r2'])})",
    }
    if datos["esParcial"]:
        meta["Aviso"] = f"Año {year} incompleto: {datos['mesesProyectadosN']} meses proyectados"

    cuerpo = (
        inf.kpis(kpis)
        + bloques_avisos
        + inf.seccion("1. Series comparativas de los últimos ejercicios", _tabla_historico(datos),
                      nota="Saldos reales sin recortar a cero. El ejercicio marcado como «sin datos» "
                           "no entra en el ajuste de la tendencia.")
        + inf.seccion(f"2. Tendencia y proyección de {year_proy}", grafico_historico
                      + f'<div style="margin-top:12px">{_tabla_tendencias(datos)}</div>',
                      nota="Proyección = ajuste ponderado evaluado en "
                           f"{year_proy} (coordenada X = año natural; los huecos no deforman la pendiente).")
        + inf.seccion("3. Cuenta de pérdidas y ganancias proyectada",
                      _tabla_pyg_proyectado(datos)
                      + f'<div style="font-size:11.5px;color:#5b6b80;padding:4px 2px">'
                        f'Impuesto al {num(datos["tipoImpuesto"])}% sobre un RAI positivo; '
                        f'variación de ingresos frente a {year}: <b>{fmt_pct(base.get("varIngresos", 0.0))}</b> · '
                        f'variación del resultado: <b>{fmt_pct(base.get("varResultado", 0.0))}</b></div>')
        + inf.seccion("4. Escenarios", grafico_escenarios + _tabla_escenarios(datos),
                      nota="El escenario base es la tendencia ajustada; los escenarios alternativos "
                           "mueven ingresos y gastos de explotación con los factores indicados.")
        + inf.seccion(f"5. Mes a mes de {year}"
                      + (f" (datos hasta {MESES[datos['mesCorte'] - 1]})" if datos["esParcial"] else ""),
                      _tabla_mensual_curso(datos) + f'<div style="margin-top:10px">{grafico_mensual}'
                      + f'<div style="margin-top:12px">{grafico_caja}</div></div>',
                      nota=("Los meses posteriores al corte se estiman subiendo el acumulado real "
                            "con los factores estacionales del histórico (gross-up estacional)."
                            if datos["esParcial"] else
                            "Ejercicio completo: no quedan meses por proyectar; el reparto mensual "
                            f"de {year_proy} se calcula más abajo con los mismos factores."))
        + inf.seccion(f"6. Reparto temporal de {year_proy}",
                      grafico_estacional + f'<div style="margin-top:12px">{_tabla_trimestral(datos)}</div>'
                      + f'<div style="margin-top:12px">{_tabla_mensual_proyectado(datos)}</div>',
                      nota=f"Factores estacionales calculados sobre "
                           f"{datos['aniosCompletosEstacionalidad']} ejercicio(s) con los 12 meses "
                           "observados; si no hay ninguno, se reparte a partes iguales.")
        + inf.seccion("7. Metodología y control", barra_tendencia
                      + f'<div style="font-size:11.5px;color:#3c4a5c;padding:6px 2px">'
                        "<b>Regresión:</b> mínimos cuadrados ponderados con pesos 1..n (el ejercicio "
                        "más reciente pesa más), evaluada en el año siguiente. "
                        "<b>Signos:</b> sin recortes a cero (sólo se acotan ventas, gastos, deudores "
                        "y acreedores, avisando si ocurre). "
                        "<b>Impuesto:</b> tipo nominal sobre RAI positivo, porque los ejercicios "
                        "cargados no traen la cuenta 630. "
                        "<b>Caja:</b> resultado + amortización; " 
                      + ("la tesorería se reconstruye desde los saldos 57x." if datos["hayTesoreria"]
                         else "no hay saldos 57x en el ERP, así que no se reconstruye el saldo "
                              "bancario y se informa de la caja generada.")
                      + "</div>"
                      + ("".join(f"<div style='font-size:11.5px;color:#5b6b80;padding:2px 2px'>· {inf.esc(a)}</div>"
                                 for a in datos["avisos"]) if datos["avisos"] else "")),
    )
    return inf.envoltura(
        titulo=TITULO,
        subtitulo=f"Tendencia {'-'.join(str(a) for a in datos['aniosConDatos'])} · "
                  f"proyección del ejercicio {year_proy}",
        empresa=empresa, ejercicio=year, cuerpo=cuerpo, meta=meta,
        extra_pie=f"Documento generado a partir de {sum(h['nLineas'] for h in historico):,} "
                  f"apuntes del ERP apiCON.".replace(",", "."),
    )


__all__ = ["calcular", "informe_html", "metricas_dashboard", "magnitudes",
           "serie_mensual_completa", "regresion", "NOMBRE", "TITULO", "INTERNO",
           "DESPLAZAMIENTOS", "PARAMETROS"]
