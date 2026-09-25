"""Módulo `conciliacion` — REQ-01 Conciliación de mayores. **Informe de uso interno.**

Sustituye al nodo Code «Conciliar Mayores» del workflow REQ-01 de n8n. El original
recibía `$('GET Apuntes Clientes (43x)')`, expandía los `Detalles` de cada asiento,
agrupaba por cuenta y buscaba cinco tipos de anomalía (clientes y proveedores con saldo
contrario, cobros y pagos en tesorería sin contrapartida, partidas de la 555 y asientos
repetidos). Aquí se porta esa lógica y se añade lo que el informe necesitaba de verdad:
**el estado del punteo**.

Qué hace ahora:

1. **Punteo.** Cada línea trae `PunteoCuenta` y `PunteoBancario`. El ERP los devuelve
   como `null`, como cadena `"None"`, como cadena vacía o como `"0"` cuando la partida
   **no** está conciliada, y con una marca real (una fecha, una letra) cuando sí lo está.
   Comparar con `is None` o `== ""` falla: la cadena `"None"` es *truthy* en Python y
   colaría 3.712 partidas sin puntear como si estuvieran punteadas (ver `ES_SIN_PUNTEO`).
   Una partida está pendiente si **ninguno** de los dos punteos trae marca.
2. **Resumen por cuenta y por tercero** del saldo pendiente, con el número de partidas y
   la fecha de la más antigua.
3. **Orden por riesgo**: importe pendiente absoluto ponderado por la antigüedad
   (`|importe| × (1 + años)`, `riesgo`), no sólo por importe. Una cuenta de 2.000 € de
   hace tres años pesa más que una de 2.000 € del mes pasado.
4. **Avisos** cuando hay cuentas con movimientos muy antiguos sin puntear, cuando el
   libro descuadra o cuando no hay ni una sola partida punteada (señal de que la
   exportación no trae punteos).
5. **Los cinco bloques heredados** del JS, como sección de anomalías.

Correcciones sobre el JS original (el resto del comportamiento se mantiene):

- `.slice(0, 10)` en tesorería y duplicados escondía el resto de hallazgos: ahora se
  cuentan **todos** y sólo se recorta la lista que se pinta (`PARAMETROS`).
- El orden sólo miraba `nivel`, así que dentro de un nivel el orden era el de inserción.
  Ahora desempata por importe descendente.
- El recuento de duplicados agrupaba por fecha + importe redondeado. Se añade la
  comprobación de que sean **documentos distintos** (dos líneas del mismo asiento no son
  un duplicado) y se exige que el asiento tenga al menos dos apuntes.
- `importeRiesgo` sólo sumaba los niveles ALTA y MEDIA: aquí el importe pendiente se
  calcula sobre todas las partidas, con o sin anomalía.

El módulo no habla con el ERP ni con la caché y **no imprime nada**: devuelve números en
`datos` y deja los avisos en `datos["avisos"]`.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable, Sequence

from .. import informes as inf
from ..ledger import (Linea, comprobar_cuadre, fecha_a_int, fmt, fmt_pct, num,
                      saldos_por_cuenta)

NOMBRE = "conciliacion"
TITULO = "Conciliación de mayores"
INTERNO = False
DESPLAZAMIENTOS = [0]
PARAMETROS: dict[str, Any] = {
    "top_cuentas": 12,        # cuentas que se pintan (se ordenan por riesgo)
    "top_terceros": 10,
    "dias_antiguedad": 365,   # a partir de aquí la partida pendiente es «muy antigua»
    "limite_hallazgos": 25,   # filas de la tabla de anomalías (se cuentan todas)
    "minimo_pendiente": 100.0,  # no se pintan cuentas por debajo de esto
}

# --- clasificación de cuentas -------------------------------------------------

GRUPOS_CUENTA: list[tuple[tuple[str, ...], str]] = [
    (("43", "44"), "Clientes y deudores"),
    (("40", "41"), "Proveedores y acreedores"),
    (("57",), "Tesorería"),
    (("52", "17"), "Deudas a corto plazo"),
    (("47", "48"), "Hacienda y ajustes"),
    (("46",), "Personal y otros"),
    (("20", "21", "22", "23"), "Inmovilizado"),
    (("3",), "Existencias"),
    (("5",), "Cuentas financieras"),
    (("6",), "Gastos"),
    (("7",), "Ingresos"),
    (("1",), "Financiación y patrimonio"),
]

PREFIJOS_CLIENTES = ("43", "44")
PREFIJOS_PROVEEDORES = ("40", "41")
PREFIJOS_TESORERIA = ("57", "52")
PREFIJO_PARTIDAS = "555"

# Umbrales de nivel heredados del JS (ALTA > 5.000, MEDIA > 1.000).
UMBRAL_ALTA = 5000.0
UMBRAL_MEDIA = 1000.0


def _grupo_cuenta(cuenta: str) -> str:
    for prefijos, etiqueta in GRUPOS_CUENTA:
        if cuenta.startswith(prefijos):
            return etiqueta
    return "Otras"


# --- punteo -------------------------------------------------------------------

#: Valores con los que el ERP dice «sin puntear». Se comparan en minúsculas: `None`
#: llega ya convertido a `""` por el ledger, pero la cadena `"None"` llega tal cual.
ES_SIN_PUNTEO = {
    "", "-", "--", "none", "null", "nan", "false", "no", "sin puntear", "pendiente",
    "0", "0.0", "0,00", "0.00",
}


def marca_punteo(valor: Any) -> bool:
    """¿El campo de punteo trae una marca real (fecha, letra, identificador)?"""
    texto = str("" if valor is None else valor).strip().lower()
    return bool(texto) and texto not in ES_SIN_PUNTEO


def esta_punteada(linea: Linea) -> bool:
    """Una partida está conciliada si trae marca en el punteo de cuenta o en el bancario."""
    return marca_punteo(linea.punteo_cuenta) or marca_punteo(linea.punteo_bancario)


def esta_pendiente(linea: Linea) -> bool:
    """Sin conciliar: ni punteo de cuenta ni punteo bancario."""
    return not esta_punteada(linea)


# --- fechas -------------------------------------------------------------------

def _fecha(v: Any) -> dt.date | None:
    f = fecha_a_int(v)
    if not f or f < 19000101:
        return None
    try:
        return dt.date(f // 10000, (f // 100) % 100, f % 100)
    except ValueError:
        return None


def _dias(desde: Any, hasta: Any) -> int:
    a, b = _fecha(desde), _fecha(hasta)
    return (b - a).days if a and b else 0


def fecha_es(fecha: Any) -> str:
    f = _fecha(fecha)
    return f"{f.day:02d}/{f.month:02d}/{f.year}" if f else "—"


def _referencia(lineas: list[Linea], year: int, ctx: dict) -> int:
    """Fecha con la que se mide la antigüedad.

    Por defecto el último apunte del ejercicio, para que el informe sea reproducible.
    `ctx["fecha_referencia"]` (YYYYMMDD o ISO) manda si viene.
    """
    pedida = fecha_a_int(ctx.get("fecha_referencia")) if ctx.get("fecha_referencia") else 0
    if pedida:
        return pedida
    fechas = [fecha_a_int(l.fecha) for l in lineas if fecha_a_int(l.fecha)]
    if fechas:
        return max(fechas)
    return year * 10000 + 1231


# --- terceros -----------------------------------------------------------------

_RE_LETRAS = re.compile(r"[^\W\d_]", re.UNICODE)


def _plausible(texto: str) -> bool:
    """Un nombre de tercero razonable: al menos cuatro letras y no sólo dígitos."""
    return len(_RE_LETRAS.findall(texto or "")) >= 4


def nombre_tercero(linea: Linea) -> str:
    """Nombre del tercero.

    El campo `Tercero` de los apuntes viene vacío en el ERP, así que el nombre se deduce
    de la descripción del asiento («ED/2025/00001-MARÍA SERRA CAÑELLAS» → la parte que
    va detrás del guión), que es lo que el asesor reconoce. Si no hay nada aprovechable
    se devuelve la propia descripción recortada.
    """
    propio = (linea.tercero or "").strip()
    if propio:
        return propio
    desc = (linea.descripcion or "").strip()
    if not desc:
        return "(sin identificar)"
    candidatos: list[str] = []
    for sep in (" - ", "-", "/", ":", " "):
        if sep in desc:
            candidatos.append(desc.rsplit(sep, 1)[1].strip(" .,;-"))
    candidatos.append(desc)
    for c in candidatos:
        if _plausible(c):
            return c[:60]
    return desc[:48]


# --- agregaciones -------------------------------------------------------------

def _nueva_fila(cuenta: str) -> dict[str, Any]:
    return {
        "cuenta": cuenta, "grupo": _grupo_cuenta(cuenta),
        "debe": 0.0, "haber": 0.0, "n": 0,
        "n_pendientes": 0, "pendiente": 0.0, "fecha_antigua": 0, "fecha_reciente": 0,
        "n_punteadas": 0, "punteado": 0.0,
    }


def _cerrar_fila(f: dict[str, Any], ref: int, *, dias_aviso: int) -> dict[str, Any]:
    f["saldo"] = round(f["debe"] - f["haber"], 2)
    f["pendiente"] = round(f["pendiente"], 2)
    f["punteado"] = round(f["punteado"], 2)
    f["debe"] = round(f["debe"], 2)
    f["haber"] = round(f["haber"], 2)
    f["pct_pendiente"] = round(f["n_pendientes"] / f["n"] * 100, 1) if f["n"] else 0.0
    f["antiguedad_dias"] = _dias(f["fecha_antigua"], ref) if f["fecha_antigua"] else 0
    f["anios"] = round(f["antiguedad_dias"] / 365, 1)
    f["riesgo"] = round(abs(f["pendiente"]) * (1 + f["antiguedad_dias"] / 365), 2)
    f["nivel"] = nivel_riesgo(f["pendiente"], f["antiguedad_dias"], dias_aviso)
    f["fecha_antigua_es"] = fecha_es(f["fecha_antigua"])
    return f


def nivel_riesgo(pendiente: float, antiguedad_dias: int, dias_aviso: int) -> str:
    """ALTA/MEDIA/INFO: importe pendiente y, si es antiguo, se sube de nivel."""
    importe = abs(pendiente or 0.0)
    antiguo = antiguedad_dias > dias_aviso
    if importe > UMBRAL_ALTA or (antiguo and importe > UMBRAL_MEDIA):
        return "ALTA"
    if importe > UMBRAL_MEDIA or (antiguo and importe > 0):
        return "MEDIA"
    return "INFO"


def resumen_cuentas(lineas: Iterable[Linea], ref: int, *, dias_aviso: int) -> list[dict[str, Any]]:
    """Saldo pendiente por cuenta de mayor, con antigüedad y riesgo. Ordenado por riesgo."""
    acc: dict[str, dict[str, Any]] = {}
    for l in lineas:
        if not l.cuenta:
            continue
        f = acc.get(l.cuenta)
        if f is None:
            f = acc[l.cuenta] = _nueva_fila(l.cuenta)
        f["debe"] += l.debe
        f["haber"] += l.haber
        f["n"] += 1
        if esta_pendiente(l):
            f["n_pendientes"] += 1
            f["pendiente"] += l.importe
            fecha = fecha_a_int(l.fecha)
            if fecha and (not f["fecha_antigua"] or fecha < f["fecha_antigua"]):
                f["fecha_antigua"] = fecha
            if fecha > f["fecha_reciente"]:
                f["fecha_reciente"] = fecha
        else:
            f["n_punteadas"] += 1
            f["punteado"] += l.importe
    filas = [_cerrar_fila(f, ref, dias_aviso=dias_aviso) for f in acc.values()]
    filas.sort(key=lambda f: (-f["riesgo"], -abs(f["pendiente"]), f["cuenta"]))
    return filas


def resumen_terceros(lineas: Iterable[Linea], ref: int, *, dias_aviso: int,
                     prefijos: Sequence[str] | None = None,
                     max_cuentas: int = 3) -> list[dict[str, Any]]:
    """Saldo pendiente por tercero (sólo partidas sin puntear). Ordenado por riesgo."""
    acc: dict[str, dict[str, Any]] = {}
    for l in lineas:
        if not l.cuenta or (prefijos and not l.cuenta.startswith(tuple(prefijos))):
            continue
        if not esta_pendiente(l):
            continue
        clave = nombre_tercero(l)
        f = acc.get(clave)
        if f is None:
            f = acc[clave] = {"tercero": clave, "grupo": _grupo_cuenta(l.cuenta),
                              "cuentas": [], "n_pendientes": 0, "pendiente": 0.0,
                              "debe": 0.0, "haber": 0.0, "fecha_antigua": 0,
                              "grupos": set()}
        f["n_pendientes"] += 1
        f["pendiente"] += l.importe
        f["debe"] += l.debe
        f["haber"] += l.haber
        f["grupos"].add(_grupo_cuenta(l.cuenta))
        if l.cuenta not in f["cuentas"]:
            f["cuentas"].append(l.cuenta)
        fecha = fecha_a_int(l.fecha)
        if fecha and (not f["fecha_antigua"] or fecha < f["fecha_antigua"]):
            f["fecha_antigua"] = fecha
    filas = []
    for f in acc.values():
        f["pendiente"] = round(f["pendiente"], 2)
        f["saldo"] = round(f["debe"] - f["haber"], 2)
        f["debe"] = round(f["debe"], 2)
        f["haber"] = round(f["haber"], 2)
        f["antiguedad_dias"] = _dias(f["fecha_antigua"], ref) if f["fecha_antigua"] else 0
        f["anios"] = round(f["antiguedad_dias"] / 365, 1)
        f["riesgo"] = round(abs(f["pendiente"]) * (1 + f["antiguedad_dias"] / 365), 2)
        f["nivel"] = nivel_riesgo(f["pendiente"], f["antiguedad_dias"], dias_aviso)
        f["fecha_antigua_es"] = fecha_es(f["fecha_antigua"])
        f["grupo"] = " · ".join(sorted(f["grupos"]))
        f["n_cuentas"] = len(f["cuentas"])
        f["cuentas_texto"] = ", ".join(f["cuentas"][:max_cuentas]) + (
            f" (+{len(f['cuentas']) - max_cuentas})" if len(f["cuentas"]) > max_cuentas else "")
        del f["grupos"]
        filas.append(f)
    filas.sort(key=lambda f: (-f["riesgo"], -abs(f["pendiente"]), f["tercero"]))
    return filas


def tramos_antiguedad(lineas: Iterable[Linea], ref: int) -> list[dict[str, Any]]:
    """Importe y partidas pendientes por tramo de antigüedad (para la gráfica)."""
    tramos = [("Hasta 3 meses", 0, 91), ("3-6 meses", 92, 182), ("6-12 meses", 183, 365),
              ("> 12 meses", 366, 10 ** 6)]
    acumulado = {nombre: {"tramo": nombre, "n": 0, "importe": 0.0} for nombre, _, _ in tramos}
    for l in lineas:
        if not esta_pendiente(l):
            continue
        dias = abs(_dias(l.fecha, ref))
        for nombre, desde, hasta in tramos:
            if desde <= dias <= hasta:
                acumulado[nombre]["n"] += 1
                acumulado[nombre]["importe"] += l.importe
                break
    salida = []
    for nombre, _, _ in tramos:
        fila = acumulado[nombre]
        fila["importe"] = round(fila["importe"], 2)
        fila["importe_abs"] = round(abs(fila["importe"]), 2)
        salida.append(fila)
    return salida


# --- asientos reconstruidos (para los bloques heredados) ----------------------

def _clave_asiento(l: Linea) -> tuple[str, str]:
    if l.documento or l.serie:
        return (l.serie, l.documento)
    return ("", f"{l.fecha}|{l.descripcion[:24]}")


def agrupar_asientos(lineas: Iterable[Linea]) -> dict[tuple[str, str], list[Linea]]:
    """Reconstruye los asientos a partir de las líneas (el módulo recibe líneas sueltas)."""
    grupos: dict[tuple[str, str], list[Linea]] = {}
    for l in lineas:
        grupos.setdefault(_clave_asiento(l), []).append(l)
    return grupos


def _hallazgo(tipo: str, nivel: str, *, cuenta: str = "", fecha: Any = 0, documento: str = "",
              importe: float = 0.0, descripcion: str = "", **extra: Any) -> dict[str, Any]:
    h = {"tipo": tipo, "nivel": nivel, "cuenta": cuenta, "fecha": fecha_a_int(fecha),
         "documento": documento, "importe": round(abs(importe), 2),
         "descripcion": descripcion}
    h.update(extra)
    return h


def detectar_anomalias(lineas: list[Linea], *, limite: int | None = None) -> list[dict[str, Any]]:
    """Los cinco bloques del nodo Code original, sobre las líneas del ejercicio.

    Se conservan los umbrales del JS (100 € de movimiento, 1.000/5.000 € de nivel).
    `limite` recorta la lista devuelta (los recuentos por tipo se calculan siempre sobre
    el total, que es la diferencia con el `.slice(0, 10)` original).
    """
    saldos = saldos_por_cuenta(lineas)
    hallazgos: list[dict[str, Any]] = []

    # 1. Clientes (43x/44x) con saldo contrario: el normal es deudor.
    for cuenta, s in saldos.items():
        if not cuenta.startswith(PREFIJOS_CLIENTES):
            continue
        saldo = s.deudor
        if saldo < -0.01:
            hallazgos.append(_hallazgo(
                "CLIENTE_SALDO_NEGATIVO", nivel_riesgo(saldo, 0, 10 ** 6), cuenta=cuenta,
                importe=saldo, nivel_importe=abs(round(saldo, 2)), n_lineas=s.n,
                descripcion="Saldo contrario (acreedor) en cuenta de cliente: cobro de más, "
                            "cobro duplicado o factura pendiente de emitir."))

    # 2. Proveedores (40x/41x) con saldo contrario: el normal es acreedor.
    for cuenta, s in saldos.items():
        if not cuenta.startswith(PREFIJOS_PROVEEDORES):
            continue
        saldo = s.acreedor
        if saldo < -0.01:
            hallazgos.append(_hallazgo(
                "PROVEEDOR_SALDO_NEGATIVO", nivel_riesgo(saldo, 0, 10 ** 6), cuenta=cuenta,
                importe=saldo, nivel_importe=abs(round(saldo, 2)), n_lineas=s.n,
                descripcion="Saldo contrario (deudor) en cuenta de proveedor: pago duplicado, "
                            "anticipo sin aplicar o factura recibida dos veces."))

    # 3. Tesorería con cobro/pago sin contrapartida de cliente o proveedor en el mismo asiento.
    for clave, apuntes in agrupar_asientos(lineas).items():
        if len(apuntes) < 2:
            continue
        if not any(a.cuenta.startswith(PREFIJOS_TESORERIA) for a in apuntes):
            continue
        tiene_cliente = any(a.cuenta.startswith(PREFIJOS_CLIENTES) for a in apuntes)
        tiene_proveedor = any(a.cuenta.startswith(PREFIJOS_PROVEEDORES) for a in apuntes)
        for a in apuntes:
            if not a.cuenta.startswith(PREFIJOS_TESORERIA):
                continue
            if a.haber > 100 and not tiene_cliente:
                hallazgos.append(_hallazgo(
                    "COBRO_SIN_CONTRAPARTIDA", nivel_riesgo(a.haber, 0, 10 ** 6), cuenta=a.cuenta,
                    fecha=a.fecha, documento=a.documento, importe=a.haber,
                    descripcion="Entrada en tesorería sin cuenta de cliente en el asiento: "
                                "cobro sin identificar."))
            if a.debe > 100 and not tiene_proveedor:
                hallazgos.append(_hallazgo(
                    "PAGO_SIN_CONTRAPARTIDA", nivel_riesgo(a.debe, 0, 10 ** 6), cuenta=a.cuenta,
                    fecha=a.fecha, documento=a.documento, importe=a.debe,
                    descripcion="Salida de tesorería sin cuenta de proveedor en el asiento: "
                                "pago sin identificar."))

    # 4. Partidas de la 555 pendientes de aplicar.
    for cuenta, s in saldos.items():
        if not cuenta.startswith(PREFIJO_PARTIDAS):
            continue
        saldo = abs(s.deudor)
        if saldo > 0.01:
            hallazgos.append(_hallazgo(
                "PARTIDA_PENDIENTE_555", nivel_riesgo(saldo, 0, 10 ** 6), cuenta=cuenta,
                importe=saldo, n_lineas=s.n,
                descripcion="Partida pendiente de aplicación en la 555: hay que identificarla "
                            "y llevarla a su cuenta definitiva."))

    # 5. Asientos repetidos: misma fecha e importe, en documentos distintos.
    por_importe: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for clave, apuntes in agrupar_asientos(lineas).items():
        if len(apuntes) < 2:
            continue
        total_debe = round(sum(a.debe for a in apuntes), 2)
        fecha = fecha_a_int(apuntes[0].fecha)
        if not fecha or total_debe <= 100:
            continue
        por_importe.setdefault((fecha, int(round(total_debe))), []).append({
            "documento": apuntes[0].documento or f"{apuntes[0].serie}/{apuntes[0].documento}",
            "fecha": fecha, "importe": total_debe,
            "descripcion": apuntes[0].descripcion or "",
            "cuentas": sorted({a.cuenta for a in apuntes})[:3],
        })
    for (fecha, _), grupo in por_importe.items():
        docs = {g["documento"] for g in grupo}
        if len(grupo) >= 2 and len(docs) >= 2:
            importe = grupo[0]["importe"]
            hallazgos.append(_hallazgo(
                "ASIENTO_DUPLICADO", nivel_riesgo(importe, 0, 10 ** 6), fecha=fecha,
                documento=" / ".join(sorted(docs)[:6]), importe=importe,
                n_asientos=len(grupo),
                descripcion=f"{len(grupo)} asientos con el mismo importe ({num(importe)}) y la "
                            f"misma fecha en documentos distintos: revisar si es duplicado o "
                            f"una operación repetida legítima."))

    orden = {"ALTA": 0, "MEDIA": 1, "INFO": 2}
    hallazgos.sort(key=lambda h: (orden.get(h["nivel"], 3), -abs(h.get("importe") or 0), h["tipo"]))
    return hallazgos[:limite] if limite else hallazgos


# --- cálculo ------------------------------------------------------------------

def calcular(por_anio: dict[int, list[Linea]], ctx: dict) -> dict[str, Any]:
    """Todas las cifras de la conciliación, en números y listo para serializar."""
    year = int(ctx.get("year") or 0)
    lineas = list(por_anio.get(year) or [])
    avisos: list[str] = []
    if not lineas and por_anio:
        # el llamador puede haber cargado sólo otro ejercicio: se usa el más reciente
        year_con_datos = max(a for a, ls in por_anio.items() if ls)
        lineas = list(por_anio[year_con_datos])
        avisos.append(f"No hay apuntes de {year}; el informe se ha calculado con los de "
                      f"{year_con_datos}.")

    top_cuentas = int(ctx.get("top_cuentas") or PARAMETROS["top_cuentas"])
    top_terceros = int(ctx.get("top_terceros") or PARAMETROS["top_terceros"])
    dias_aviso = int(ctx.get("dias_antiguedad") or PARAMETROS["dias_antiguedad"])
    limite_hallazgos = int(ctx.get("limite_hallazgos") or PARAMETROS["limite_hallazgos"])
    minimo = float(ctx.get("minimo_pendiente") or PARAMETROS["minimo_pendiente"])
    ref = _referencia(lineas, year, ctx)

    # ---------- cifras de punteo ----------
    n_pendientes = 0
    pendiente = 0.0
    pendiente_abs = 0.0
    punteado = 0.0
    n_punteadas = 0
    n_marca_cuenta = n_marca_bancaria = 0
    n_antiguas = 0
    importe_antiguo = 0.0
    for l in lineas:
        if marca_punteo(l.punteo_cuenta):
            n_marca_cuenta += 1
        if marca_punteo(l.punteo_bancario):
            n_marca_bancaria += 1
        if esta_pendiente(l):
            n_pendientes += 1
            pendiente += l.importe
            pendiente_abs += abs(l.importe)
            if _dias(l.fecha, ref) > dias_aviso:
                n_antiguas += 1
                importe_antiguo += l.importe
        else:
            n_punteadas += 1
            punteado += l.importe

    cuadre = comprobar_cuadre(lineas)
    cuentas = resumen_cuentas(lineas, ref, dias_aviso=dias_aviso)
    cuentas_con_pendiente = [c for c in cuentas if abs(c["pendiente"]) >= 0.01]
    cuentas_pintadas = [c for c in cuentas if abs(c["pendiente"]) >= minimo][:top_cuentas]
    terceros = resumen_terceros(lineas, ref, dias_aviso=dias_aviso)
    tramos = tramos_antiguedad(lineas, ref)

    # ---------- anomalías heredadas ----------
    todos_los_hallazgos = detectar_anomalias(lineas)
    hallazgos = todos_los_hallazgos[:limite_hallazgos]
    recuento: dict[str, int] = {}
    for h in todos_los_hallazgos:
        recuento[h["tipo"]] = recuento.get(h["tipo"], 0) + 1
    importe_anomalias = round(sum(h["importe"] for h in todos_los_hallazgos), 2)

    # ---------- avisos ----------
    cuentas_antiguas = [c for c in cuentas_con_pendiente
                        if c["antiguedad_dias"] > dias_aviso and abs(c["pendiente"]) >= minimo]
    if cuentas_antiguas:
        avisos.append(
            f"{len(cuentas_antiguas)} cuentas con saldo pendiente de más de "
            f"{dias_aviso // 30} meses ({fmt(sum(c['pendiente'] for c in cuentas_antiguas))}): "
            + ", ".join(c["cuenta"] for c in cuentas_antiguas[:5])
            + ("…" if len(cuentas_antiguas) > 5 else "") + ".")
    if lineas and not n_punteadas:
        avisos.append("No hay ni una sola partida punteada en el ejercicio: o está todo sin "
                      "conciliar, o la exportación del ERP no trae los punteos. Se trata todo "
                      "el ejercicio como pendiente.")
    elif lineas and n_pendientes / len(lineas) > 0.5:
        avisos.append(f"Más de la mitad del ejercicio sigue sin puntear "
                      f"({n_pendientes} de {len(lineas)} partidas).")
    if abs(cuadre["descuadre"]) > 0.01:
        avisos.append(f"El libro no cuadra: diferencia de {fmt(cuadre['descuadre'])} entre debe "
                      f"y haber. Suele ser un asiento partido en el corte de datos o una línea "
                      f"fuera del ejercicio.")
    if not lineas:
        avisos.append("No hay apuntes que analizar en el ejercicio.")
    if todos_los_hallazgos:
        altas = sum(1 for h in todos_los_hallazgos if h["nivel"] == "ALTA")
        avisos.append(f"{len(todos_los_hallazgos)} anomalías detectadas "
                      f"({altas} de nivel alto), por {fmt(importe_anomalias)}.")
    if all(not marca_punteo(l.punteo_bancario) for l in lineas) and lineas:
        avisos.append("Ningún apunte trae punteo bancario: no se puede saber todavía si las "
                      "entradas y salidas de tesorería están conciliadas con el banco.")

    datos: dict[str, Any] = {
        "year": year,
        "fecha_referencia": ref,
        "fecha_referencia_es": fecha_es(ref),
        "totales": {
            "n_asientos": len({(l.serie, l.documento) for l in lineas if l.documento or l.serie}),
            "n_lineas": len(lineas),
            "n_cuentas": len({l.cuenta for l in lineas if l.cuenta}),
            "debe": cuadre["debe"],
            "haber": cuadre["haber"],
            "descuadre": cuadre["descuadre"],
            "n_grupos": len({_grupo_cuenta(l.cuenta) for l in lineas if l.cuenta}),
        },
        "punteo": {
            "n_total": len(lineas),
            "n_pendientes": n_pendientes,
            "n_punteadas": n_punteadas,
            "n_marca_cuenta": n_marca_cuenta,
            "n_marca_bancaria": n_marca_bancaria,
            "pct_pendientes": round(n_pendientes / len(lineas) * 100, 1) if lineas else 0.0,
            "importe_pendiente": round(pendiente, 2),
            "importe_pendiente_abs": round(pendiente_abs, 2),
            "importe_punteado": round(punteado, 2),
            "n_antiguas": n_antiguas,
            "importe_antiguo": round(importe_antiguo, 2),
            "dias_antiguedad": dias_aviso,
        },
        "cuentas": cuentas_pintadas,
        "cuentas_todas": cuentas,
        "n_cuentas_pendientes": len(cuentas_con_pendiente),
        "terceros": terceros[:top_terceros],
        "tramos_antiguedad": tramos,
        "hallazgos": hallazgos,
        "hallazgos_recuento": recuento,
        "n_hallazgos": len(todos_los_hallazgos),
        "importe_anomalias": importe_anomalias,
        "avisos": avisos,
    }
    datos["kpis"] = metricas_dashboard(datos)
    return datos


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    """KPIs numéricos (los que guarda el registro de ejecuciones y enseña el panel)."""
    p = datos.get("punteo") or {}
    return {
        "n_lineas": p.get("n_total", 0),
        "n_pendientes": p.get("n_pendientes", 0),
        "pct_pendientes": p.get("pct_pendientes", 0.0),
        "importe_pendiente": p.get("importe_pendiente", 0.0),
        "importe_pendiente_abs": p.get("importe_pendiente_abs", 0.0),
        "n_antiguas": p.get("n_antiguas", 0),
        "importe_antiguo": p.get("importe_antiguo", 0.0),
        "n_cuentas_pendientes": datos.get("n_cuentas_pendientes", 0),
        "n_hallazgos": datos.get("n_hallazgos", 0),
        "importe_anomalias": datos.get("importe_anomalias", 0.0),
        "descuadre": (datos.get("totales") or {}).get("descuadre", 0.0),
    }


# --- maquetación --------------------------------------------------------------

ETIQUETA_TIPO = {
    "CLIENTE_SALDO_NEGATIVO": "Cliente con saldo contrario",
    "PROVEEDOR_SALDO_NEGATIVO": "Proveedor con saldo contrario",
    "COBRO_SIN_CONTRAPARTIDA": "Cobro sin contrapartida",
    "PAGO_SIN_CONTRAPARTIDA": "Pago sin contrapartida",
    "PARTIDA_PENDIENTE_555": "Partida de la 555",
    "ASIENTO_DUPLICADO": "Asiento repetido",
}


def _badge(nivel: str) -> str:
    color = {"ALTA": inf.NEGATIVO, "MEDIA": inf.AMBAR}.get(nivel, "#5b6b80")
    return (f'<span style="background:{color};color:#fff;padding:1px 6px;border-radius:3px;'
            f'font-size:10.5px;white-space:nowrap">{inf.esc(nivel)}</span>')


def _tabla_cuentas(cuentas: list[dict[str, Any]]) -> str:
    return inf.tabla(
        ["Cuenta", "Grupo", "Pendiente", "Sin puntear", "Partidas", "Más antigua", "Riesgo", "Nivel"],
        [[c["cuenta"], c["grupo"], inf.importe(c["pendiente"]), fmt_pct(c["pct_pendiente"]),
          str(c["n_pendientes"]), f'{c["fecha_antigua_es"]} ({c["anios"]} a.)',
          num(c["riesgo"]), _badge(c["nivel"])]
         for c in cuentas],
        anchos=["14%", "17%", "13%", "10%", "8%", "17%", "11%", "10%"],
    )


def _tabla_terceros(terceros: list[dict[str, Any]]) -> str:
    return inf.tabla(
        ["Tercero", "Grupo", "Cuentas", "Pendiente", "Partidas", "Más antigua", "Nivel"],
        [[t["tercero"], t["grupo"], t["cuentas_texto"], inf.importe(t["pendiente"]),
          str(t["n_pendientes"]), f'{t["fecha_antigua_es"]} ({t["anios"]} a.)', _badge(t["nivel"])]
         for t in terceros],
        anchos=["26%", "16%", "16%", "14%", "8%", "12%", "8%"],
    )


def _tabla_hallazgos(hallazgos: list[dict[str, Any]]) -> str:
    filas = []
    for h in hallazgos:
        referencia = h.get("cuenta") or h.get("documento") or "—"
        filas.append([
            ETIQUETA_TIPO.get(h["tipo"], h["tipo"]), referencia,
            fecha_es(h["fecha"]) if h.get("fecha") else "—",
            inf.importe(h["importe"]), _badge(h["nivel"]), h["descripcion"],
        ])
    return inf.tabla(["Anomalía", "Cuenta / documento", "Fecha", "Importe", "Nivel", "Qué supone"],
                     filas, anchos=["17%", "16%", "9%", "11%", "7%", "40%"])


def _tabla_recuento(recuento: dict[str, int]) -> str:
    orden = sorted(recuento.items(), key=lambda kv: -kv[1])
    return inf.tabla(["Tipo de anomalía", "Hallazgos"],
                     [[ETIQUETA_TIPO.get(k, k), str(v)] for k, v in orden],
                     totales=["Total", str(sum(recuento.values()))] if recuento else None,
                     anchos=["70%", "30%"])


def informe_html(datos: dict[str, Any], ctx: dict) -> str:
    """HTML del informe interno (empieza por `<div`, CSS inline, sin JS)."""
    year = datos["year"]
    p = datos["punteo"]
    totales = datos["totales"]
    cuentas = datos["cuentas"]
    terceros = datos["terceros"]
    tramos = datos["tramos_antiguedad"]

    tarjetas = [
        ("Partidas sin puntear", f'{p["n_pendientes"]:,}'.replace(",", ".")),
        ("% del ejercicio", fmt_pct(p["pct_pendientes"])),
        ("Saldo pendiente", inf.importe(p["importe_pendiente"])),
        ("Pendiente sobre el total", fmt_pct(
            (p["importe_pendiente_abs"] / (p["importe_pendiente_abs"] + abs(p["importe_punteado"])) * 100)
            if (p["importe_pendiente_abs"] + abs(p["importe_punteado"])) else 0)),
        ("Cuentas con pendiente", str(datos["n_cuentas_pendientes"])),
        ("Partidas de más de un año", f'{p["n_antiguas"]:,}'.replace(",", ".")),
        ("Importe de más de un año", inf.importe(p["importe_antiguo"])),
        ("Anomalías", str(datos["n_hallazgos"])),
    ]

    grafico_cuentas = inf.barras_svg(
        [c["cuenta"] for c in cuentas[:top_limite(cuentas)]],
        [{"nombre": "Pendiente", "color": inf.AZUL,
          "valores": [c["pendiente"] for c in cuentas[:top_limite(cuentas)]]}],
        alto=180, titulo="Saldo pendiente por cuenta",
        formato=lambda v: inf.num(v),
    )
    grafico_tramos = inf.barras_svg(
        [t["tramo"] for t in tramos],
        [
            {"nombre": "Pendiente", "color": inf.AZUL, "valores": [t["importe"] for t in tramos]},
            {"nombre": "Partidas", "color": inf.AMBAR, "valores": [t["n"] for t in tramos]},
        ],
        alto=170, titulo="Antigüedad del pendiente",
        formato=lambda v: num(v),
    )

    filas_resumen = [
        ["Partidas del ejercicio", str(p["n_total"])],
        ["Partidas punteadas", f'{p["n_punteadas"]} ({fmt_pct(100 - p["pct_pendientes"]) if p["n_total"] else "—"})'],
        ["Partidas sin puntear", str(p["n_pendientes"])],
        ["Con marca en punteo de cuenta", str(p["n_marca_cuenta"])],
        ["Con marca en punteo bancario", str(p["n_marca_bancaria"])],
        ["Debe / Haber del ejercicio", f'{fmt(totales["debe"])} / {fmt(totales["haber"])}'],
        ["Diferencia del libro", fmt(totales["descuadre"])],
        ["Antigüedad medida al", datos["fecha_referencia_es"]],
    ]

    avisos_html = "".join(inf.aviso(a, tipo="alerta") for a in datos["avisos"])

    cuerpo = (
        inf.kpis(tarjetas, columnas=4)
        + inf.aviso("Informe de circulación interna de ABGA: refleja partidas pendientes de "
                    "puntear y anomalías contables del mayor. No incluye juicios de valor ni "
                    "se envía al cliente.", tipo="info")
        + avisos_html
        + inf.seccion("Estado del punteo",
                      inf.tabla(["Concepto", "Valor"], filas_resumen, anchos=["62%", "38%"])
                      + inf.barra_pct(p["pct_pendientes"],
                                      etiqueta="Partidas pendientes de conciliar sobre el total "
                                               f"({p['n_pendientes']} de {p['n_total']})",
                                      color=inf.NEGATIVO if p["pct_pendientes"] > 50 else inf.AZUL),
                      nota="Una partida está pendiente cuando ni PunteoCuenta ni PunteoBancario "
                           "traen marca (null, \"None\", \"\" y \"0\" cuentan como sin puntear).")
        + inf.seccion(f"Cuentas de mayor con saldo pendiente ({len(cuentas)})",
                      _tabla_cuentas(cuentas) + grafico_cuentas,
                      nota="Ordenadas por riesgo: importe pendiente absoluto ponderado por la "
                           "antigüedad de la partida más antigua sin puntear.")
        + inf.seccion(f"Pendiente por tercero ({len(terceros)})",
                      _tabla_terceros(terceros) if terceros else
                      inf.aviso("No hay partidas pendientes con tercero identificable.", tipo="ok"),
                      nota="El nombre del tercero se deduce de la descripción del asiento: el "
                           "campo Tercero de los apuntes del ERP llega vacío.")
        + inf.seccion("Antigüedad del pendiente", grafico_tramos)
        + inf.seccion(
            f"Anomalías detectadas ({datos['n_hallazgos']} por {fmt(datos['importe_anomalias'])})",
            (_tabla_recuento(datos["hallazgos_recuento"]) if datos["hallazgos_recuento"] else "")
            + (_tabla_hallazgos(datos["hallazgos"]) if datos["hallazgos"] else
               inf.aviso("Sin anomalías de este bloque en el ejercicio.", tipo="ok"))
            + (inf.aviso(f"Se listan {len(datos['hallazgos'])} de {datos['n_hallazgos']} "
                         f"hallazgos, los de mayor importe. El resto está en el dato del "
                         f"informe.", tipo="info")
               if datos["n_hallazgos"] > len(datos["hallazgos"]) else ""),
            nota="Bloques heredados del workflow original: saldos contrarios en 43x/44x y "
                 "40x/41x, entradas y salidas de tesorería sin contrapartida, partidas de la "
                 "555 y asientos repetidos (misma fecha e importe en documentos distintos).")
    )

    return inf.envoltura(
        titulo="Conciliación de mayores",
        subtitulo=f"Ejercicio {year} · partidas pendientes de puntear y anomalías del mayor",
        empresa=ctx.get("empresa") or "",
        ejercicio=year,
        interno=INTERNO,
        cuerpo=cuerpo,
        meta={"Partidas": str(totales["n_lineas"]), "Asientos": str(totales["n_asientos"]),
              "Cuentas": str(totales["n_cuentas"]), "Origen": "ERP apiCON (apuntes del ejercicio)"},
        extra_pie="Revisar las partidas marcadas antes de cerrar el ejercicio o emitir "
                  "cualquier informe al cliente.",
    )


def top_limite(cuentas: list[dict[str, Any]], maximo: int = 10) -> int:
    """Cuántas cuentas entran en la gráfica (las muy pequeñas ensucian las barras)."""
    return max(1, min(maximo, len(cuentas)))


__all__ = ["NOMBRE", "TITULO", "INTERNO", "DESPLAZAMIENTOS", "PARAMETROS", "calcular",
           "informe_html", "metricas_dashboard", "esta_pendiente", "esta_punteada",
           "marca_punteo", "detectar_anomalias", "resumen_cuentas", "resumen_terceros",
           "nombre_tercero", "nivel_riesgo", "ES_SIN_PUNTEO"]
