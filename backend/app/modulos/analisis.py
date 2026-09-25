"""Motor de análisis con semáforo de riesgo.

Inspirado en el NetAnálisis 360º de NetAsesor (el producto que ABGA quiere igualar): en vez de
un informe más, este módulo es un **catálogo de comprobaciones automáticas** que se ejecutan
sobre los apuntes y salen clasificadas por riesgo (verde / naranja / rojo).

Cómo se añade un análisis: **una entrada en `REGLAS` y nada más**. Cada regla declara qué
comprueba, cómo se calcula y una función que recibe el contexto ya calculado y devuelve uno de
los cuatro niveles. Si el dato no está en los apuntes, la regla devuelve `no_evaluable` con el
motivo; **nunca inventa una cifra** (es la regla de la casa: el sistema anterior estimaba el
inmovilizado y los vencimientos y se presentaban como datos del ERP).

Niveles:
    alerta       rojo     #c62828   hay que actuar
    aviso        naranja  #b26a00   hay que revisarlo
    ok           verde    #2e7d32   comprobado y correcto
    no_evaluable gris     #6b7280   los apuntes no dan el dato (con motivo)
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .. import informes as inf
from ..ledger import (Linea, comprobar_cuadre, fmt, fmt_pct, mes_de, nombre_tercero,
                      por_mes, por_tercero, saldos_por_cuenta, suma_acreedor, suma_deudor)
from . import conciliacion as mod_conciliacion
from . import duplicados as mod_duplicados
from . import pyg as mod_pyg

NOMBRE = "analisis"
TITULO = "Análisis y alertas"
INTERNO = False
DESPLAZAMIENTOS = [0, -1]
PARAMETROS: dict[str, Any] = {"familia": None}

ALERTA, AVISO, OK, NO_EVALUABLE = "alerta", "aviso", "ok", "no_evaluable"
ORDEN_NIVEL = {ALERTA: 0, AVISO: 1, NO_EVALUABLE: 2, OK: 3}

COLOR = {ALERTA: "#c62828", AVISO: "#b26a00", OK: "#2e7d32", NO_EVALUABLE: "#6b7280"}
FONDO = {ALERTA: "#fdecec", AVISO: "#fff6e6", OK: "#eaf6ec", NO_EVALUABLE: "#f1f3f6"}
ETIQUETA = {ALERTA: "Rojo · actuar", AVISO: "Naranja · revisar", OK: "Verde · correcto",
            NO_EVALUABLE: "No evaluable"}

FAMILIAS = [("contable", "Análisis contables"), ("fiscal", "Análisis fiscales"),
            ("financiero", "Análisis financieros"), ("mercantil", "Análisis mercantiles"),
            ("laboral", "Análisis laborales")]

# Umbrales (se declaran aquí para que se puedan discutir y ajustar sin tocar las reglas)
UMBRAL_347 = 3005.06          # obligación de incluir a un tercero en el modelo 347
UMBRAL_CONCENTRACION = 35.0   # % del saldo de clientes en un solo cliente
UMBRAL_ANTIGUEDAD = 90        # días
UMBRAL_ENDEUDAMIENTO = 75.0   # % sobre el activo
TIPO_IS = 0.18                # tipo general del Impuesto de Sociedades (estimación del 202)
# Magnitudes del deber de auditarse: hay que superar DOS de las TRES durante DOS ejercicios seguidos.
AUDITORIA = {"activo": 2_500_000.0, "cifra_negocios": 5_000_000.0, "empleados": 50}


@dataclass
class Regla:
    id: str
    familia: str
    titulo: str
    comprueba: str
    como: str
    evaluar: Callable[[dict[str, Any]], dict[str, Any]]


# ------------------------------------------------------------------ utilidades

def _res(nivel: str, detalle: str, *, importe: float | None = None, recomendacion: str = "",
         datos: Sequence[Any] = (), magnitud: dict[str, Any] | None = None) -> dict[str, Any]:
    """`importe` es SIEMPRE dinero (es lo que suma el importe en riesgo). Las medidas que no son
    dinero (días, porcentajes) van en `magnitud`, para no mezclar unidades."""
    return {"nivel": nivel, "detalle": detalle, "importe": importe,
            "magnitud": magnitud, "recomendacion": recomendacion, "datos": list(datos)}


def _seg(nivel: str, *, importe: float | None = None, recomendacion: str = "", datos: Sequence[Any] = ()) -> dict[str, Any]:
    return {"nivel": nivel, "importe": importe, "recomendacion": recomendacion, "datos": list(datos)}


def _num_documento(documento: str) -> tuple[str, int] | None:
    """Separa un documento en (serie alfabética, número) — `FV/2025/00042` → ('FV/2025/', 42)."""
    m = re.match(r"^(.*?)(\d+)\s*$", str(documento or "").strip())
    if not m:
        return None
    return m.group(1).upper(), int(m.group(2))


def _meses_con_movimiento(lineas: Iterable[Linea], prefijos: Sequence[str]) -> set[int]:
    return {mes_de(l.fecha) for l in lineas if any(l.cuenta.startswith(p) for p in prefijos)}


# ------------------------------------------------------------------ contexto

def _duplicados(lineas: list[Linea]) -> dict[str, Any]:
    """Reutiliza el módulo `duplicados` (no duplica su lógica) y separa venta / compra."""
    params = mod_duplicados.PARAMETROS
    asientos = [a for a in mod_duplicados.asientos_de_lineas(lineas)
                if a.importe > params["importe_minimo"]]
    pares = mod_duplicados.pares_candidatos(asientos, dias=params["dias_proximidad"])
    hallazgos: list[dict[str, Any]] = []
    for i, j in pares:
        h = mod_duplicados.puntuar(asientos[i], asientos[j], umbral=params["umbral"],
                                   dias=params["dias_proximidad"])
        if not h:
            continue
        a, b = asientos[i], asientos[j]
        tipo = "venta" if (a.clientes or b.clientes) else (
            "compra" if (a.proveedores or b.proveedores) else "otro")
        hallazgos.append({**h, "tipo": tipo})
    por_tipo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for h in hallazgos:
        por_tipo[h["tipo"]].append(h)

    def _nivel(lista: list[dict[str, Any]]) -> str:
        if any(h["nivel"] == "PROBABLE" for h in lista):
            return ALERTA
        if any(h["nivel"] == "POSIBLE" for h in lista):
            return AVISO
        if lista:
            return AVISO
        return OK

    def _importe(lista: list[dict[str, Any]]) -> float:
        return round(sum(h.get("importeRiesgo") or 0.0 for h in lista
                         if h["nivel"] in ("PROBABLE", "POSIBLE")), 2)

    return {"hallazgos": hallazgos, "venta": por_tipo.get("venta", []),
            "compra": por_tipo.get("compra", []), "otros": por_tipo.get("otro", []),
            "nivel_venta": _nivel(por_tipo.get("venta", [])),
            "nivel_compra": _nivel(por_tipo.get("compra", [])),
            "importe_venta": _importe(por_tipo.get("venta", [])),
            "importe_compra": _importe(por_tipo.get("compra", []))}


def _contexto(por_anio: dict[int, list[Linea]], ctx: dict[str, Any]) -> dict[str, Any]:
    year = int(ctx.get("year") or 0)
    lineas = list(por_anio.get(year) or [])
    anterior = list(por_anio.get(year - 1) or [])
    saldos = saldos_por_cuenta(lineas)
    meses = por_mes(lineas)
    ref = max((l.fecha for l in lineas), default=0)
    pg = mod_pyg.calcular_lineas(lineas, anterior)
    return {
        "year": year, "ctx": ctx, "lineas": lineas, "anterior": anterior,
        "saldos": saldos, "meses": meses,
        "cuadre": comprobar_cuadre(lineas),
        "pg": pg,
        "anomalias": mod_conciliacion.detectar_anomalias(lineas),
        "resumen_cuentas": mod_conciliacion.resumen_cuentas(lineas, ref, dias_aviso=UMBRAL_ANTIGUEDAD),
        "duplicados": _duplicados(lineas),
        "n_lineas": len(lineas),
        "n_asientos": len({(l.serie, l.documento, l.fecha) for l in lineas}),
    }


# ------------------------------------------------------------------ reglas: contables

def _r_cuadre(c: dict) -> dict:
    d = c["cuadre"]
    if not c["n_lineas"]:
        return _res(NO_EVALUABLE, "no hay apuntes en el ejercicio.")
    if abs(d["descuadre"]) < 0.01:
        n_txt = f"{d['n_lineas']:,}".replace(",", ".")
        return _res(OK, f"ΣDebe = ΣHaber = {fmt(d['debe'])} en {n_txt} líneas.")
    return _res(ALERTA, f"El libro descuadra en {fmt(d['descuadre'])}: "
                        f"ΣDebe {fmt(d['debe'])} frente a ΣHaber {fmt(d['haber'])}.",
                importe=d["descuadre"],
                recomendacion="Revisar los asientos descuadrados antes de emitir ningún informe.")


def _r_balance(c: dict) -> dict:
    pg = c["pg"].get("cuadre") or {}
    dif = abs(float(pg.get("diferencia") or 0.0))
    huerfanas = pg.get("huerfanas") or []
    if c["n_lineas"] and dif < 0.01:
        return _res(OK, f"Activo = Patrimonio neto + Pasivo, con diferencia de {fmt(0.0)}.")
    if not c["n_lineas"]:
        return _res(NO_EVALUABLE, "no hay apuntes en el ejercicio.")
    return _res(ALERTA, f"El balance no cuadra: diferencia de {fmt(dif)}.",
                importe=dif,
                datos=huerfanas[:12],
                recomendacion="Hay cuentas sin clasificar en el cuadro; revisar los grupos PGC.")


def _r_apertura(c: dict) -> dict:
    gastos = list(c["meses"].get(1, [])) + list(c["meses"].get(12, []))
    tiene_capital = any(l.cuenta.startswith(("10", "11", "12")) for l in c["lineas"])
    if tiene_capital:
        return _res(OK, "Los apuntes traen cuentas de patrimonio neto (10x-12x).")
    if not gastos and not c["lineas"]:
        return _res(NO_EVALUABLE, "no hay apuntes en el ejercicio.")
    return _res(NO_EVALUABLE,
                "Los apuntes de este ejercicio no traen asiento de apertura ni cuentas 10x-12x "
                "(capital y reservas), así que no se puede comprobar el saldo de apertura.",
                recomendacion="El patrimonio neto del balance está incompleto a propósito: "
                              "falta el capital y las reservas.")


def _r_dup_venta(c: dict) -> dict:
    return _res(c["duplicados"]["nivel_venta"],
                _texto_dup("venta", c["duplicados"]["venta"]),
                importe=c["duplicados"]["importe_venta"],
                recomendacion="Contrastar con el cliente antes de reclamar o de emitir el informe.")


def _r_dup_compra(c: dict) -> dict:
    return _res(c["duplicados"]["nivel_compra"],
                _texto_dup("compra", c["duplicados"]["compra"]),
                importe=c["duplicados"]["importe_compra"],
                recomendacion="Comprobar si son dos registros de la misma factura de gasto.")


def _texto_dup(etiqueta: str, lista: Sequence[dict]) -> str:
    if not lista:
        return f"Sin facturas de {etiqueta} repetidas con los criterios actuales."
    prob = sum(1 for h in lista if h["nivel"] == "PROBABLE")
    pos = sum(1 for h in lista if h["nivel"] == "POSIBLE")
    imp = sum(h.get("importeRiesgo") or 0.0 for h in lista if h["nivel"] in ("PROBABLE", "POSIBLE"))
    return (f"{len(lista)} pares sospechosos de facturas de {etiqueta} "
            f"({prob} probables y {pos} posibles), con {fmt(imp)} en riesgo.")


def _r_saltos_numeracion(c: dict) -> dict:
    series: dict[str, list[int]] = defaultdict(list)
    for l in c["lineas"]:
        if not l.cuenta.startswith(("700", "701", "702", "703", "704", "705")):
            continue
        par = _num_documento(l.documento)
        if par:
            series[par[0]].append(par[1])
    if not series:
        return _res(NO_EVALUABLE, "no se han podido leer números de factura en las cuentas de ventas.")
    saltos = []
    for serie, numeros in series.items():
        orden = sorted(set(numeros))
        for a, b in zip(orden, orden[1:]):
            if b - a > 1:
                saltos.append({"serie": serie, "desde": a, "hasta": b, "faltan": b - a - 1})
    total = sum(s["faltan"] for s in saltos)
    if not saltos:
        return _res(OK, f"Numeración de ventas continua en {len(series)} serie(s).")
    return _res(AVISO if total < 5 else ALERTA,
                f"{len(saltos)} salto(s) de numeración en las facturas de venta: "
                f"{total} número(s) sin usar.",
                datos=saltos[:12],
                recomendacion="Un salto puede ser una factura anulada, una serie distinta o una "
                              "factura emitida y no contabilizada: revisar.")


def _r_clientes_sin_movimiento(c: dict) -> dict:
    return _sin_movimiento(c, "clientes", ("43", "44"), "cobrar")


def _r_proveedores_sin_movimiento(c: dict) -> dict:
    return _sin_movimiento(c, "proveedores", ("40", "41"), "pagar")


def _sin_movimiento(c: dict, etiqueta: str, prefijos: Sequence[str], verbo: str) -> dict:
    if not c["anterior"]:
        return _res(NO_EVALUABLE,
                    f"sin el ejercicio anterior no se puede saber si hay cuentas de {etiqueta} "
                    "que se han quedado sin movimiento.")
    actuales = {l.cuenta for l in c["lineas"]}
    acumulado: dict[str, dict[str, Any]] = {}
    for l in c["anterior"]:
        if not any(l.cuenta.startswith(p) for p in prefijos) or l.cuenta in actuales:
            continue
        d = acumulado.setdefault(l.cuenta, {"debe": 0.0, "haber": 0.0, "nombre": ""})
        d["debe"] += l.debe
        d["haber"] += l.haber
        d["nombre"] = nombre_tercero(l.tercero, l.descripcion)
    pendientes = {k: v for k, v in acumulado.items() if abs(v["debe"] - v["haber"]) > 0.01}
    total = sum(abs(v["debe"] - v["haber"]) for v in pendientes.values())
    filas = sorted(([k, round(v["debe"] - v["haber"], 2), v["nombre"]] for k, v in pendientes.items()),
                   key=lambda f: -abs(f[1]))
    if not pendientes:
        return _res(OK, f"Ninguna cuenta de {etiqueta} con saldo se ha quedado sin movimiento.")
    return _res(AVISO if total < 6000 else ALERTA,
                f"{len(pendientes)} cuenta(s) de {etiqueta} con saldo del ejercicio anterior y "
                f"sin ningún movimiento en este: {fmt(total)} pendientes de {verbo}.",
                importe=round(total, 2), datos=filas[:12],
                recomendacion="Revisar si el saldo sigue vivo (y reclamar) o hay que depurarlo.")


def _r_partidas_555(c: dict) -> dict:
    saldo = suma_deudor(c["saldos"], ["555"], recortar=False)
    if abs(saldo) < 0.01:
        return _res(OK, "No hay partidas pendientes de aplicación en la cuenta 555.")
    return _res(ALERTA, f"Hay {fmt(abs(saldo))} en partidas pendientes de aplicación (555).",
                importe=round(saldo, 2),
                recomendacion="Aplicar las partidas a su cuenta definitiva: distorsionan el "
                              "resultado y el IVA.")


def _r_saldos_contrarios(c: dict) -> dict:
    tipos = {"CLIENTE_SALDO_NEGATIVO": "cliente con saldo acreedor",
             "PROVEEDOR_SALDO_NEGATIVO": "proveedor con saldo deudor"}
    encontrados = [a for a in c["anomalias"] if a.get("tipo") in tipos]
    if not encontrados:
        return _res(OK, "Ninguna cuenta de clientes o proveedores con saldo contrario a su naturaleza.")
    total = sum(abs(a.get("importe") or 0.0) for a in encontrados)
    filas = [[a.get("cuenta", ""), round(a.get("importe") or 0.0, 2), tipos[a["tipo"]]]
             for a in encontrados]
    return _res(AVISO if total < 5000 else ALERTA,
                f"{len(encontrados)} cuenta(s) con saldo contrario a su naturaleza, "
                f"{fmt(total)} en total.",
                importe=round(total, 2), datos=filas[:12],
                recomendacion="Suele ser un cobro o un pago mal asignado o un anticipo sin compensar.")


def _r_gastos_personal(c: dict) -> dict:
    prefijos = ("640", "641", "642")
    if not any(l.cuenta.startswith(prefijos) for l in c["lineas"]):
        return _res(AVISO, "No se ha contabilizado ningún gasto de personal (640-642) en todo el "
                           "ejercicio.",
                    recomendacion="Comprobar si la empresa no tiene plantilla o si faltan nóminas.")
    meses_ok = _meses_con_movimiento(c["lineas"], prefijos)
    ultimo = max((mes_de(l.fecha) for l in c["lineas"]), default=0)
    esperados = {m for m in range(1, (ultimo or 12) + 1)}
    faltan = sorted(esperados - meses_ok)
    if not faltan:
        return _res(OK, f"Gastos de personal contabilizados en los {len(esperados)} meses del ejercicio.")
    return _res(AVISO, f"Hay {len(faltan)} mes(es) sin ningún gasto de personal: "
                       + ", ".join(f"mes {m}" for m in faltan) + ".",
                recomendacion="Revisar si faltan nóminas por contabilizar en esos meses.")


def _r_gastos_signo(c: dict) -> dict:
    contrarios = []
    for cuenta, s in c["saldos"].items():
        if cuenta.startswith(("60", "62", "63", "64", "68")) and s.acreedor > 0.01 and s.deudor < -0.01:
            contrarios.append([cuenta, round(s.deudor, 2)])
        elif cuenta.startswith("70") and s.deudor > 0.01:
            contrarios.append([cuenta, round(s.deudor, 2)])
    if not contrarios:
        return _res(OK, "Las cuentas de gasto son deudoras y las de ingreso acreedoras.")
    total = sum(abs(f[1]) for f in contrarios)
    return _res(AVISO, f"{len(contrarios)} cuenta(s) de gasto o ingreso con el signo cambiado, "
                       f"{fmt(total)} en total.",
                importe=round(total, 2), datos=contrarios[:12],
                recomendacion="Suele ser un abono o una devolución sin su asiento inverso.")


def _r_variacion_existencias(c: dict) -> dict:
    var = suma_deudor(c["saldos"], ["610", "611", "612"], recortar=False)
    existe = suma_deudor(c["saldos"], [str(n) for n in range(300, 360)], recortar=False)
    if abs(var) < 0.01 and abs(existe) < 0.01:
        return _res(OK, "No hay existencias ni variación de existencias que cuadrar.")
    if abs(var) > 0.01 and abs(existe) < 0.01:
        return _res(AVISO, f"Hay {fmt(abs(var))} de variación de existencias pero ningún saldo en "
                           "las cuentas 30x-35x.",
                    importe=round(var, 2),
                    recomendacion="Contrastar con el inventario: o falta el saldo de existencias o "
                                  "la variación está mal imputada.")
    if abs(var) < 0.01:
        return _res(AVISO, f"Hay {fmt(abs(existe))} de existencias pero no se ha registrado la "
                           "variación de existencias (610).",
                    importe=round(existe, 2),
                    recomendacion="Comprobar el asiento de regularización de existencias.")
    return _res(OK, f"Existencias por {fmt(abs(existe))} y variación registrada por {fmt(abs(var))}.")


# ------------------------------------------------------------------ reglas: fiscales

def _r_socios_55(c: dict) -> dict:
    saldo = suma_deudor(c["saldos"], [str(n) for n in range(550, 560)], recortar=False)
    if abs(saldo) < 0.01:
        return _res(OK, "Sin saldos con socios y administradores (55x).")
    return _res(ALERTA, f"Hay {fmt(abs(saldo))} en cuentas con socios (55x).",
                importe=round(saldo, 2),
                recomendacion="En una sociedad, los saldos con socios tienen tratamiento fiscal: "
                              "revisar antes del cierre.")


def _r_tesoreria_negativa(c: dict) -> dict:
    cuentas = [c2 for c2 in c["saldos"] if c2.startswith(("570", "571", "572", "573", "574", "575", "576", "577"))]
    if not cuentas:
        return _res(NO_EVALUABLE,
                    "El ERP no devuelve movimientos de tesorería (grupo 57) en esta empresa: "
                    "no se puede comprobar si la caja o los bancos están en negativo.",
                    recomendacion="Los saldos de banco hay que comprobarlos fuera de los apuntes.")
    negativos = [[cu, round(c["saldos"][cu].deudor, 2)] for cu in cuentas if c["saldos"][cu].deudor < -0.01]
    if not negativos:
        return _res(OK, f"Las {len(cuentas)} cuenta(s) de tesorería están en positivo.")
    total = sum(abs(f[1]) for f in negativos)
    return _res(ALERTA, f"{len(negativos)} cuenta(s) de tesorería en negativo, {fmt(total)}.",
                importe=round(-total, 2), datos=negativos,
                recomendacion="Un saldo negativo en caja o banco suele ser un extracto sin "
                              "conciliar; nunca se debe presentar así.")


def _r_resultado_negativo(c: dict) -> dict:
    r = float(c["pg"].get("resultadoNeto") or 0.0)
    if r < 0:
        return _res(ALERTA, f"El ejercicio cierra con pérdidas de {fmt(abs(r))}.",
                    importe=round(r, 2),
                    recomendacion="Comprobar el cumplimiento de los requisitos de disolución y "
                                  "las medidas de corrección.")
    return _res(OK, f"El ejercicio cierra con beneficio de {fmt(r)}.")


def _r_fondos_propios(c: dict) -> dict:
    pn = float(c["pg"].get("patrimonioNeto") or 0.0)
    incompleto = not any(l.cuenta.startswith(("10", "11", "12")) for l in c["lineas"])
    detalle = (f"Patrimonio neto de {fmt(pn)}."
               + (" Ojo: los apuntes no traen capital ni reservas (10x-12x), así que el dato está "
                  "incompleto." if incompleto else ""))
    if pn < 0:
        return _res(ALERTA, f"Fondos propios negativos: {fmt(pn)}.",
                    importe=round(pn, 2),
                    recomendacion="Situación de desbalance patrimonial: revisar obligaciones "
                                  "societarias.")
    return _res(AVISO if incompleto else OK, detalle)


def _r_iva(c: dict) -> dict:
    repercutido = suma_acreedor(c["saldos"], ["477"], recortar=False)
    soportado = suma_deudor(c["saldos"], ["472"], recortar=False)
    if abs(repercutido) < 0.01 and abs(soportado) < 0.01:
        return _res(NO_EVALUABLE, "No hay saldos de IVA (472/477) en los apuntes.")
    dif = repercutido - soportado
    if dif >= 0:
        return _res(OK, f"IVA: repercutido {fmt(repercutido)} frente a soportado {fmt(soportado)}: "
                        f"{fmt(dif)} a ingresar.")
    return _res(AVISO, f"IVA: soportado {fmt(soportado)} mayor que el repercutido "
                       f"{fmt(repercutido)}: {fmt(abs(dif))} a compensar o devolver.",
                importe=round(dif, 2),
                recomendacion="Con el saldo a compensar conviene planificar las declaraciones del "
                              "periodo siguiente.")


def _r_deudas_aeat(c: dict) -> dict:
    partidas = [("475", "Hacienda acreedora (retenciones)"), ("476", "Organismos de la Seguridad Social"),
                ("477", "IVA repercutido pendiente"), ("4751", "Retenciones de trabajo pendientes")]
    filas = []
    for prefijo, etiqueta in partidas:
        s = suma_acreedor(c["saldos"], [prefijo], recortar=False)
        filas.append([prefijo, etiqueta, round(s, 2)])
    total = sum(f[2] for f in filas)
    if abs(total) < 0.01:
        return _res(OK, "Sin deudas pendientes con Hacienda ni con la Seguridad Social.")
    return _res(AVISO, f"{fmt(total)} pendientes de pago a administraciones públicas.",
                importe=round(total, 2), datos=filas,
                recomendacion="Comprobar los plazos de ingreso de cada modelo.")


def _r_modelo_347(c: dict) -> dict:
    """Las operaciones del 347 son las facturas, no los cobros ni los pagos: en las cuentas de
    clientes (deudoras) se suma el Debe y en las de proveedores (acreedoras) el Haber. Sumar
    Debe+Haber contaría dos veces cada factura."""
    totales: dict[str, float] = defaultdict(float)
    for l in c["lineas"]:
        if l.cuenta.startswith(("43", "44")):
            totales[nombre_tercero(l.tercero, l.descripcion)] += l.debe
        elif l.cuenta.startswith(("40", "41")):
            totales[nombre_tercero(l.tercero, l.descripcion)] += l.haber
    obligados = sorted(([n, round(v, 2)] for n, v in totales.items() if v > UMBRAL_347),
                       key=lambda f: -f[1])
    if not obligados:
        return _res(OK, f"Ningún tercero supera los {fmt(UMBRAL_347)} de operaciones del modelo 347.")
    return _res(AVISO, f"{len(obligados)} tercero(s) superan los {fmt(UMBRAL_347)} de operaciones y "
                       "hay que incluirlos en el modelo 347.",
                datos=obligados[:12],
                recomendacion="Comprobarlo con los totales del 347 presentado.")


def _r_modelo_202(c: dict) -> dict:
    base = float(c["pg"].get("resultadoNeto") or 0.0)
    if not c["n_lineas"]:
        return _res(NO_EVALUABLE, "no hay apuntes en el ejercicio.")
    cuota = round(max(0.0, base) * TIPO_IS, 2)
    return _res(AVISO, f"Pago fraccionado del Impuesto de Sociedades (modelo 202) estimado en "
                       f"{fmt(cuota)} al {fmt_pct(TIPO_IS * 100)} sobre el resultado de {fmt(base)}.",
                importe=cuota,
                recomendacion="Es una ESTIMACIÓN sobre el resultado contable: la base del 202 sale "
                              "del resultado de la cuenta de PyG del periodo, no de la base "
                              "imponible. Confirmar con el asesor.")


# ------------------------------------------------------------------ reglas: financieras

def _r_deudas_lp(c: dict) -> dict:
    saldo = suma_acreedor(c["saldos"], [str(n) for n in range(170, 180)], recortar=False)
    if abs(saldo) < 0.01:
        return _res(OK, "Sin deudas a largo plazo con entidades de crédito (17x).")
    return _res(AVISO, f"Deudas a largo plazo por {fmt(saldo)} (cuentas 17x).",
                importe=round(saldo, 2),
                recomendacion="Comprobar el cuadro de vencimientos y los intereses del periodo.")


def _r_pmc(c: dict) -> dict:
    ingresos = suma_acreedor(c["saldos"], mod_pyg.P_INGRESOS_ACTIVIDAD, recortar=False)
    clientes = suma_deudor(c["saldos"], ["43", "44"], recortar=False)
    if ingresos <= 0:
        return _res(NO_EVALUABLE, "no hay ingresos de actividad en el ejercicio: no se puede "
                                  "calcular el periodo medio de cobro.")
    dias = round(clientes / ingresos * 365)
    nivel = OK if dias <= 60 else (AVISO if dias <= 90 else ALERTA)
    return _res(nivel, f"Periodo medio de cobro: {dias} días ({fmt(clientes)} pendientes sobre "
                       f"{fmt(ingresos)} de ingresos).",
                magnitud={"valor": dias, "unidad": "días"},
                recomendacion="Por encima de 90 días, el circulante se financia con deuda.")


def _r_pmp(c: dict) -> dict:
    compras = suma_deudor(c["saldos"], mod_pyg.P_APROVISIONAMIENTOS, recortar=False)
    proveedores = suma_acreedor(c["saldos"], [str(n) for n in range(400, 420)], recortar=False)
    if compras <= 0:
        return _res(NO_EVALUABLE, "no hay compras en el ejercicio: no se puede calcular el periodo "
                                  "medio de pago.")
    dias = round(proveedores / compras * 365)
    nivel = OK if dias <= 90 else AVISO
    return _res(nivel, f"Periodo medio de pago: {dias} días ({fmt(proveedores)} pendientes sobre "
                       f"{fmt(compras)} de compras).", magnitud={"valor": dias, "unidad": "días"})


def _r_concentracion(c: dict) -> dict:
    filas = [t for t in por_tercero(c["lineas"], ["43", "44"]) if t["saldo"] > 0.01]
    total = sum(t["saldo"] for t in filas)
    if total <= 0 or not filas:
        return _res(NO_EVALUABLE, "no hay saldo pendiente de cobro suficiente para medir la "
                                  "concentración.")
    primero = max(filas, key=lambda t: t["saldo"])
    pct = primero["saldo"] / total * 100
    if pct <= UMBRAL_CONCENTRACION:
        return _res(OK, f"Ningún cliente concentra más del {fmt_pct(UMBRAL_CONCENTRACION)} del saldo "
                        f"pendiente (el mayor, {fmt_pct(pct)}).")
    return _res(AVISO if pct < 50 else ALERTA,
                f"{primero['tercero']} concentra el {fmt_pct(pct)} del saldo pendiente de cobro "
                f"({fmt(primero['saldo'])} de {fmt(total)}).",
                importe=round(primero["saldo"], 2),
                recomendacion="Un cliente que pesa tanto es riesgo de impago y de dependencia.")


def _r_antiguedad(c: dict) -> dict:
    filas = [f for f in c["resumen_cuentas"]
             if str(f.get("cuenta", "")).startswith(("43", "44")) and abs(f.get("saldo") or 0.0) > 0.01]
    viejos = [f for f in filas if (f.get("antiguedad_dias") or 0) > UMBRAL_ANTIGUEDAD]
    if not filas:
        return _res(NO_EVALUABLE, "no hay cuentas de clientes con saldo pendiente.")
    total = sum(abs(f.get("saldo") or 0.0) for f in viejos)
    if not viejos:
        return _res(OK, f"Ninguna de las {len(filas)} cuenta(s) de clientes con saldo supera los "
                        f"{UMBRAL_ANTIGUEDAD} días de antigüedad.")
    orden = sorted(viejos, key=lambda f: -(abs(f.get("saldo") or 0.0)))
    datos = [[f.get("cuenta", ""), round(f.get("saldo") or 0.0, 2), f.get("antiguedad_dias") or 0,
              f.get("fecha_antigua_es", "")] for f in orden]
    return _res(AVISO if total < 10000 else ALERTA,
                f"{len(viejos)} cuenta(s) de clientes con movimientos de más de "
                f"{UMBRAL_ANTIGUEDAD} días y saldo vivo: {fmt(total)}.",
                importe=round(total, 2), datos=datos[:12],
                recomendacion="Revisar el cobro y valorar la dotación por deterioro.")


def _r_endeudamiento(c: dict) -> dict:
    activo = float(c["pg"].get("totalActivo") or 0.0)
    if activo <= 0:
        return _res(NO_EVALUABLE, "el total de activo es cero o no se ha podido calcular.")
    deuda = sum(s.acreedor for c2, s in c["saldos"].items()
                if c2.startswith(("16", "17", "40", "41", "50", "51", "52", "53", "55")))
    pct = deuda / activo * 100
    nivel = OK if pct <= UMBRAL_ENDEUDAMIENTO else (AVISO if pct <= 90 else ALERTA)
    return _res(nivel, f"Endeudamiento del {fmt_pct(pct)} sobre un activo de {fmt(activo)} "
                       f"({fmt(deuda)} de deuda).", magnitud={"valor": round(pct, 1), "unidad": "%"},
                recomendacion="Por encima del 75% el margen de maniobra es pequeño.")


def _r_fondo_maniobra(c: dict) -> dict:
    fm = c["pg"].get("fondoManiobra")
    if fm is None:
        return _res(NO_EVALUABLE, "no se ha podido calcular el fondo de maniobra.")
    fm = float(fm)
    if fm < 0:
        return _res(ALERTA, f"Fondo de maniobra negativo: {fmt(fm)}.",
                    importe=round(fm, 2),
                    recomendacion="El circulante no cubre las deudas a corto plazo: revisar "
                                  "cobros y refinanciación.")
    return _res(OK, f"Fondo de maniobra positivo: {fmt(fm)}.")


# ------------------------------------------------------------------ reglas: mercantiles

def _r_auditoria(c: dict) -> dict:
    activo = float(c["pg"].get("totalActivo") or 0.0)
    cifra = suma_acreedor(c["saldos"], mod_pyg.P_INGRESOS_ACTIVIDAD, recortar=False)
    supera = [activo > AUDITORIA["activo"], cifra > AUDITORIA["cifra_negocios"]]
    n = sum(1 for s in supera if s)
    if n >= 2:
        return _res(AVISO, f"Se superan dos de los tres límites de auditoría (activo {fmt(activo)} y "
                           f"cifra de negocios {fmt(cifra)}), así que hay que auditarse si pasa en "
                           "dos ejercicios seguidos.",
                    recomendacion="Comprobar el ejercicio anterior y el número de empleados.")
    return _res(NO_EVALUABLE,
                "No se puede determinar la obligación de auditarse: se superan "
                f"{n} de los 3 límites (activo {fmt(activo)} y cifra {fmt(cifra)}) y en los "
                "apuntes no hay número de empleados.",
                recomendacion="La obligación exige superar 2 de 3 durante 2 ejercicios seguidos.")


def _r_concurso(c: dict) -> dict:
    capital = suma_acreedor(c["saldos"], mod_pyg.P_CAPITAL, recortar=False)
    pn = float(c["pg"].get("patrimonioNeto") or 0.0)
    if capital <= 0.01:
        return _res(NO_EVALUABLE,
                    "No hay capital social en los apuntes (cuenta 100): no se puede comparar el "
                    "patrimonio neto con la mitad del capital.",
                    recomendacion="Es uno de los parámetros de la causa de disolución del art. 363 "
                                  "de la Ley de Sociedades de Capital.")
    mitad = capital / 2
    if pn < mitad:
        return _res(ALERTA, f"El patrimonio neto ({fmt(pn)}) está por debajo de la mitad del "
                            f"capital social ({fmt(capital)}).",
                    importe=round(pn - mitad, 2),
                    recomendacion="Causa de disolución si se mantiene: revisar el art. 363 LSC.")
    return _res(OK, f"Patrimonio neto ({fmt(pn)}) por encima de la mitad del capital ({fmt(capital)}).")


def _r_capital_social(c: dict) -> dict:
    contable = suma_acreedor(c["saldos"], mod_pyg.P_CAPITAL, recortar=False)
    if abs(contable) < 0.01:
        return _res(NO_EVALUABLE, "Los apuntes no traen la cuenta 100 (capital social).")
    return _res(NO_EVALUABLE,
                f"Capital contabilizado: {fmt(contable)}. No hay dato de capital escriturado con "
                "el que compararlo.",
                recomendacion="Comparar con la escritura para detectar diferencias de capital.")


# ------------------------------------------------------------------ reglas: laborales

def _r_plantilla(c: dict) -> dict:
    return _res(NO_EVALUABLE,
                "Los apuntes no dan plantilla ni nóminas por trabajador, así que no se pueden "
                "comprobar análisis laborales (SMI, contratos, brecha salarial, antigüedad).",
                recomendacion="Estos análisis necesitan los datos de nóminas (otra fuente), no el "
                              "libro mayor.")


REGLAS: list[Regla] = [
    Regla("cuadre_libro", "contable", "Cuadre del libro de diario",
          "ΣDebe = ΣHaber en todas las líneas del ejercicio",
          "suma de la columna Debe menos la del Haber (ledger.comprobar_cuadre)", _r_cuadre),
    Regla("balance_cuadra", "contable", "Cuadre del balance",
          "Activo = Patrimonio neto + Pasivo",
          "comparación del activo con la suma de pasivo y patrimonio neto, y listado de las "
          "cuentas sin clasificar", _r_balance),
    Regla("apertura", "contable", "Saldo y asiento de apertura",
          "que el ejercicio arranque con el asiento de apertura y las cuentas de patrimonio neto",
          "presencia de las cuentas 10x-12x y de movimientos de apertura", _r_apertura),
    Regla("dup_venta", "contable", "Facturas de venta repetidas",
          "facturas de venta registradas dos veces",
          "puntuación por importe, documento, cuentas y descripción con proximidad de fechas "
          "(umbral del módulo duplicados)", _r_dup_venta),
    Regla("dup_compra", "contable", "Facturas de compra o gasto repetidas",
          "facturas de compra o gasto registradas dos veces",
          "mismo motor de duplicados que las ventas", _r_dup_compra),
    Regla("saltos_numeracion", "contable", "Saltos de numeración en facturas de venta",
          "que no falten números en las series de factura emitida",
          "se ordenan los números de documento por serie (700-705) y se buscan huecos", _r_saltos_numeracion),
    Regla("clientes_sin_movimiento", "contable", "Clientes con saldo y sin movimientos",
          "cuentas de clientes con saldo del ejercicio anterior y ningún apunte en este",
          "comparación de las cuentas 43x/44x del ejercicio anterior con las que tienen movimiento",
          _r_clientes_sin_movimiento),
    Regla("proveedores_sin_movimiento", "contable", "Proveedores con saldo y sin movimientos",
          "cuentas de proveedores con saldo del ejercicio anterior y ningún apunte en este",
          "igual que los clientes, con las cuentas 40x/41x", _r_proveedores_sin_movimiento),
    Regla("partidas_555", "contable", "Partidas pendientes de aplicación (555)",
          "que no queden partidas sin aplicar",
          "saldo de la cuenta 555", _r_partidas_555),
    Regla("saldos_contrarios", "contable", "Saldos contrarios a su naturaleza",
          "clientes con saldo acreedor y proveedores con saldo deudor",
          "recuento de anomalías del módulo de conciliación", _r_saldos_contrarios),
    Regla("gastos_personal", "contable", "Gastos de personal por meses",
          "que haya nóminas contabilizadas en todos los meses del ejercicio",
          "presencia de líneas en las cuentas 640-642 mes a mes", _r_gastos_personal),
    Regla("signos_gasto", "contable", "Signo de gastos e ingresos",
          "que los gastos sean deudores y los ingresos acreedores",
          "saldo de cada cuenta 60x/62x/63x/64x/68x y 70x", _r_gastos_signo),
    Regla("variacion_existencias", "contable", "Existencias y su variación",
          "que la variación de existencias cuadre con las cuentas de existencias",
          "comparación del saldo de 30x-35x con las cuentas 610-612", _r_variacion_existencias),
    Regla("socios_55", "fiscal", "Saldos con socios y administradores",
          "que no haya saldos pendientes con socios (55x)",
          "saldo de las cuentas 550-559", _r_socios_55),
    Regla("tesoreria_negativa", "fiscal", "Caja y bancos en negativo",
          "que ninguna cuenta de tesorería esté en negativo",
          "saldo de las cuentas 570-577", _r_tesoreria_negativa),
    Regla("resultado_negativo", "fiscal", "Resultado del ejercicio",
          "que el ejercicio no cierre con pérdidas",
          "resultado neto de la cuenta de pérdidas y ganancias", _r_resultado_negativo),
    Regla("fondos_propios", "fiscal", "Fondos propios",
          "que el patrimonio neto sea positivo",
          "patrimonio neto del balance", _r_fondos_propios),
    Regla("iva", "fiscal", "IVA repercutido y soportado",
          "comparación del IVA repercutido (477) con el soportado (472)",
          "saldos de las cuentas 477 y 472", _r_iva),
    Regla("deudas_aeat", "fiscal", "Deudas con Hacienda y Seguridad Social",
          "que no queden modelos pendientes de ingreso",
          "saldos de las cuentas 475, 476, 477 y 4751", _r_deudas_aeat),
    Regla("modelo_347", "fiscal", "Modelo 347",
          "terceros que superan los 3.005,06 € de operaciones en el año",
          "suma de debe y haber por tercero (43x/44x y 40x/41x)", _r_modelo_347),
    Regla("modelo_202", "fiscal", "Pago fraccionado del Impuesto de Sociedades",
          "estimación del modelo 202 sobre el resultado del ejercicio",
          "resultado de la cuenta de PyG por el tipo general (estimación)", _r_modelo_202),
    Regla("deudas_lp", "financiero", "Deudas a largo plazo",
          "saldos vivos con entidades de crédito a largo plazo (17x)",
          "saldo de las cuentas 170-179", _r_deudas_lp),
    Regla("pmc", "financiero", "Periodo medio de cobro",
          "días que se tarda de media en cobrar",
          "saldo de clientes entre ingresos de actividad, por 365", _r_pmc),
    Regla("pmp", "financiero", "Periodo medio de pago",
          "días que se tarda de media en pagar",
          "saldo de proveedores entre compras, por 365", _r_pmp),
    Regla("concentracion", "financiero", "Concentración de clientes",
          "que ningún cliente pese más del 35% del saldo pendiente de cobro",
          "mayor saldo por tercero sobre el total de clientes", _r_concentracion),
    Regla("antiguedad_clientes", "financiero", "Antigüedad de la deuda de clientes",
          "importes pendientes con más de 90 días",
          "antigüedad del saldo por cuenta según la conciliación", _r_antiguedad),
    Regla("endeudamiento", "financiero", "Endeudamiento",
          "que la deuda no supere el 75% del activo",
          "deuda con entidades, proveedores y acreedores sobre el activo total", _r_endeudamiento),
    Regla("fondo_maniobra", "financiero", "Fondo de maniobra",
          "que el activo corriente cubra el pasivo corriente",
          "activo corriente menos pasivo corriente (del balance)", _r_fondo_maniobra),
    Regla("auditoria", "mercantil", "Obligación de auditarse",
          "superar dos de los tres límites durante dos ejercicios seguidos",
          f"activo > {fmt(AUDITORIA['activo'])}, cifra de negocios > "
          f"{fmt(AUDITORIA['cifra_negocios'])} y más de {AUDITORIA['empleados']} empleados",
          _r_auditoria),
    Regla("concurso", "mercantil", "Causa de disolución",
          "que el patrimonio neto no baje de la mitad del capital social",
          "patrimonio neto frente a la mitad de la cuenta 100", _r_concurso),
    Regla("capital_social", "mercantil", "Capital social contabilizado",
          "que el capital contable coincida con el escriturado",
          "saldo de las cuentas 100-109 frente al capital escriturado", _r_capital_social),
    Regla("plantilla", "laboral", "Análisis laborales",
          "nóminas, contratos, SMI y brecha salarial",
          "requiere datos de plantilla y nóminas, que no están en el libro mayor", _r_plantilla),
]


# ------------------------------------------------------------------ cálculo

def _evaluar(c: dict) -> list[dict[str, Any]]:
    salida = []
    for regla in REGLAS:
        try:
            r = regla.evaluar(c)
        except Exception as e:  # una regla rota no puede tumbar el informe entero
            r = _res(NO_EVALUABLE, f"la comprobación no se ha podido ejecutar ({type(e).__name__}).")
        r = {**r, "id": regla.id, "familia": regla.familia, "titulo": regla.titulo,
             "comprueba": regla.comprueba, "como": regla.como}
        salida.append(r)
    salida.sort(key=lambda r: (ORDEN_NIVEL.get(r["nivel"], 9), r["familia"], r["id"]))
    return salida


def calcular(por_anio: dict[int, list[Linea]], ctx: dict[str, Any]) -> dict[str, Any]:
    c = _contexto(por_anio, ctx)
    hallazgos = _evaluar(c)

    recuento = {n: sum(1 for h in hallazgos if h["nivel"] == n)
                for n in (ALERTA, AVISO, OK, NO_EVALUABLE)}
    por_familia: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for h in hallazgos:
        por_familia[h["familia"]].append(h)

    if recuento[ALERTA]:
        nivel_global = ALERTA
    elif recuento[AVISO]:
        nivel_global = AVISO
    elif recuento[NO_EVALUABLE] == len(hallazgos):
        nivel_global = NO_EVALUABLE
    else:
        nivel_global = OK

    n_evaluables = len(hallazgos) - recuento[NO_EVALUABLE]
    avisos = [
        "Son comprobaciones automáticas sobre los apuntes del ERP: señalan dónde mirar, "
        "no sustituyen a la revisión del asesor.",
    ]
    if not c["n_lineas"]:
        avisos.append(f"El ejercicio {c['year']} no tiene apuntes cargados.")
    if recuento[NO_EVALUABLE]:
        avisos.append(f"{recuento[NO_EVALUABLE]} de las {len(hallazgos)} comprobaciones no se han "
                      "podido evaluar porque los apuntes no traen el dato; cada una dice por qué.")
    if not c["anterior"]:
        avisos.append("Sin el ejercicio anterior no se pueden comparar saldos de apertura ni "
                      "cuentas que se hayan quedado sin movimiento.")

    return {
        "year": c["year"],
        "empresa": ctx.get("empresa", ""),
        "cod_empresa": str(ctx.get("cod_empresa", "")),
        "resumen": {
            "n_total": len(hallazgos), "n_evaluables": n_evaluables,
            "n_rojo": recuento[ALERTA], "n_naranja": recuento[AVISO], "n_verde": recuento[OK],
            "n_no_evaluable": recuento[NO_EVALUABLE], "nivel_global": nivel_global,
            "importe_riesgo": round(sum(abs(h["importe"] or 0.0) for h in hallazgos
                                        if h["nivel"] in (ALERTA, AVISO)), 2),
        },
        "hallazgos": hallazgos,
        "por_familia": {f: por_familia.get(f, []) for f, _ in FAMILIAS},
        "n_lineas": c["n_lineas"],
        "cuadre": c["cuadre"],
        "avisos": avisos,
    }


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    r = datos.get("resumen") or {}
    return {
        "n_total": r.get("n_total", 0), "n_rojo": r.get("n_rojo", 0),
        "n_naranja": r.get("n_naranja", 0), "n_verde": r.get("n_verde", 0),
        "n_no_evaluable": r.get("n_no_evaluable", 0), "nivel_global": r.get("nivel_global", ""),
        "importe_riesgo": r.get("importe_riesgo", 0.0),
    }


# ------------------------------------------------------------------ informe

def _badge(nivel: str) -> str:
    return (f'<span style="display:inline-block;padding:1px 7px;border-radius:10px;'
            f'font-size:10px;font-weight:bold;color:#fff;background:{COLOR[nivel]};'
            f'white-space:nowrap">{ETIQUETA[nivel]}</span>')


def _semaforo(datos: dict[str, Any]) -> str:
    r = datos["resumen"]
    cajas = [(f"{r['n_total']}", "comprobaciones", inf.AZUL),
             (f"{r['n_rojo']}", "en rojo (actuar)", COLOR[ALERTA]),
             (f"{r['n_naranja']}", "en naranja (revisar)", COLOR[AVISO]),
             (f"{r['n_verde']}", "en verde (correcto)", COLOR[OK]),
             (f"{r['n_no_evaluable']}", "no evaluables", COLOR[NO_EVALUABLE])]
    cuerpo = ['<table width="100%" cellspacing="0" cellpadding="6" style="border-collapse:collapse">',
              "<tr>"]
    for valor, etiqueta, color in cajas:
        cuerpo.append(
            f'<td align="center" style="border:1px solid {inf.BORDE};background:#fff">'
            f'<div style="font-size:22px;font-weight:bold;color:{color}">{inf.esc(valor)}</div>'
            f'<div style="font-size:10px;color:#5a6b80">{inf.esc(etiqueta)}</div></td>')
    cuerpo += ["</tr></table>"]
    return "".join(cuerpo)


def _celda_importe(h: dict[str, Any]) -> str:
    """El importe va en su propia columna (no dentro de la frase) y SIEMPRE en dinero; las
    magnitudes que no son dinero (días, porcentajes) se muestran con su unidad."""
    if h.get("importe") is not None:
        return inf.importe(h["importe"])
    if h.get("magnitud"):
        m = h["magnitud"]
        return f'<span style="color:#5a6b80">{inf.esc(m["valor"])} {inf.esc(m["unidad"])}</span>'
    return '<span style="color:#b9c2cf">—</span>'


def _tabla_familia(hallazgos: Sequence[dict[str, Any]]) -> str:
    partes = ['<table width="100%" cellspacing="0" cellpadding="6" '
              f'style="border-collapse:collapse;font-size:12px;border:1px solid {inf.BORDE}">',
              f'<tr style="background:{inf.AZUL};color:#fff">'
              '<th align="left" style="width:19%">Análisis</th>'
              '<th align="left" style="width:9%">Riesgo</th>'
              '<th align="right" style="width:12%">Importe</th>'
              '<th align="left" style="width:37%">Qué dice la comprobación</th>'
              '<th align="left" style="width:23%">Recomendación</th></tr>']
    for i, h in enumerate(hallazgos):
        fondo = "#fff" if i % 2 == 0 else inf.GRIS
        partes.append(
            f'<tr style="background:{fondo}">'
            f'<td valign="top"><b>{inf.esc(h["titulo"])}</b><div style="font-size:10px;color:#5a6b80">'
            f'{inf.esc(h["comprueba"])}</div></td>'
            f'<td valign="top">{_badge(h["nivel"])}</td>'
            f'<td valign="top" align="right">{_celda_importe(h)}</td>'
            f'<td valign="top" style="color:{COLOR[h["nivel"]]}">{inf.esc(h["detalle"])}'
            f'{_detalle_datos(h)}</td>'
            f'<td valign="top" style="color:#5a6b80">{inf.esc(h["recomendacion"])}</td></tr>')
    partes.append("</table>")
    return "".join(partes)


def _detalle_datos(h: dict[str, Any]) -> str:
    datos = h.get("datos") or []
    if not datos or h["nivel"] == OK:
        return ""
    filas = []
    for d in datos[:8]:
        if isinstance(d, dict):
            filas.append(" · ".join(f"{k}: {v}" for k, v in d.items()))
        elif isinstance(d, (list, tuple)):
            filas.append(" · ".join(str(x) for x in d))
        else:
            filas.append(str(d))
    if not filas:
        return ""
    lista = "".join(f'<li style="margin:0 0 1px 0">{inf.esc(f)}</li>' for f in filas)
    return (f'<ul style="margin:4px 0 0 14px;padding:0;font-size:10px;color:#5a6b80;'
            f'list-style:disc">{lista}</ul>')


def informe_html(datos: dict[str, Any], ctx: dict[str, Any]) -> str:
    r = datos["resumen"]
    global_aviso = {ALERTA: ("error", f"{r['n_rojo']} comprobaciones en rojo requieren actuación."),
                    AVISO: ("alerta", f"{r['n_naranja']} comprobaciones en naranja conviene revisarlas."),
                    OK: ("ok", "Todas las comprobaciones evaluables han salido correctas."),
                    NO_EVALUABLE: ("info", "Los apuntes no permiten evaluar ninguna comprobación.")}[r["nivel_global"]]

    partes = [
        _semaforo(datos),
        inf.aviso(global_aviso[1], tipo=global_aviso[0], titulo="Resultado del semáforo"),
    ]

    rojos = [h for h in datos["hallazgos"] if h["nivel"] in (ALERTA, AVISO)]
    if rojos:
        filas = [[h["titulo"], ETIQUETA[h["nivel"]]] + [h["detalle"]] for h in rojos[:12]]
        partes.append(inf.seccion("Lo primero que hay que mirar", inf.tabla(
            ["Análisis", "Riesgo", "Qué ocurre"], filas, alinear="left",
            anchos=["26%", "14%", "60%"]), nota="Los análisis en rojo y naranja, de mayor a menor gravedad."))

    for clave, titulo in FAMILIAS:
        lista = datos["por_familia"].get(clave) or []
        if not lista:
            continue
        pendientes = [h for h in lista if h["nivel"] != OK]
        nota = (f"{len(lista)} comprobaciones, {len(pendientes)} con algo que revisar."
                if pendientes else f"{len(lista)} comprobaciones, todas correctas.")
        partes.append(inf.seccion(titulo, _tabla_familia(lista), nota=nota))

    partes.append(inf.seccion("Cómo funciona este informe", inf.aviso(
        "Cada análisis comprueba una cosa concreta sobre los apuntes y la clasifica en cuatro "
        "niveles: rojo (hay que actuar), naranja (hay que revisarlo), verde (correcto) y gris "
        "(los apuntes no traen el dato, y se dice cuál falta). Ninguna cifra está estimada: "
        "cuando un análisis no se puede calcular, se declara en lugar de rellenarlo.")))

    return inf.envoltura(
        titulo=TITULO,
        subtitulo=f"Comprobaciones automáticas del ejercicio {datos['year']}",
        cuerpo="".join(partes),
        interno=INTERNO,
        empresa=ctx.get("empresa", ""),
        ejercicio=datos["year"],
        meta={"Comprobaciones": str(r["n_total"]), "Evaluables": str(r["n_evaluables"]),
              "En rojo": str(r["n_rojo"]), "En naranja": str(r["n_naranja"]),
              "En verde": str(r["n_verde"]), "No evaluables": str(r["n_no_evaluable"]),
              "Líneas analizadas": f"{datos['n_lineas']:,}".replace(",", ".")},
    )
