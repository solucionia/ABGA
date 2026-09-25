"""Módulo `sumas_saldos` — Sumas y saldos (informe contable de cliente).

El clásico «sumas y saldos» que la asesoría entrega al cliente: una fila por cuenta con el
**saldo inicial**, las **sumas del debe y del haber** del ejercicio y el **saldo final**, más la
fila de totales. Todo sale de los apuntes, nunca de una estimación.

Decisiones que conviene conocer antes de tocar el cálculo:

1. **Origen del saldo inicial** (se declara siempre en `datos["avisos"]` y en el informe):
   - si el ejercicio trae **asientos de apertura**, son ellos los que abren las cuentas y esos
     asientos **no** se cuentan en las sumas del ejercicio (si se contaran, el saldo de cada
     cuenta se duplicaría: la apertura ya está dentro del saldo inicial);
   - si no hay apertura, se usan los **saldos de cierre del ejercicio anterior** que llegan en
     `por_anio[year - 1]`, excluyendo el asiento de cierre si todavía está en las líneas;
   - si no hay ni una cosa ni la otra, se dice: el saldo inicial sale a cero y el informe enseña
     sólo los movimientos del ejercicio, sin inventar la apertura.

2. **Qué es un asiento de apertura.** El ERP no expone `TipoAsiento` en las líneas (sólo en la
   cabecera del asiento, que `lineas_de_asientos` no copia), así que se reconoce por lo que sí
   llega a la línea: el asiento entero fechado el **1 de enero** y con el texto «apertura» en
   alguna de sus descripciones. Quedan fuera los ajustes de apertura manuales («CUADRE ASIENTO
   APERTURA», «Descuadre 20xx»), que son movimientos, no la apertura, y las facturas fechadas a
   1 de enero (comprobadas en los datos reales: 1092/2025 tiene 7 asientos ese día y sólo uno es
   la apertura).

3. **Se conservan los signos.** El saldo final puede ser deudor o acreedor: lo que importa es que
   Σ(Saldo final) valga cero. Si no vale cero, el informe lo avisa en lugar de recortarlo a cero.
   Los importes van con `informes.importe()` y **sin «+» delante** (el color ya distingue positivo
   de negativo): así cada cifra es un importe es-ES aislado, reconocible como `>12.345,67 €<`, que
   es lo que buscan el validador del proyecto y la exportación a Excel.

4. **Comprobaciones de integridad propias**, siempre visibles en el informe: ΣDebe = ΣHaber del
   ejercicio y Σ(Saldo final) = 0. Cuando no cuadran, se dice cuánto y se apunta al ejercicio que
   los descuadra (lo habitual: el ejercicio anterior llegó incompleto).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .. import informes as inf
from ..ledger import Linea, detectar_cierre, fecha_a_int, fmt

NOMBRE = "sumas_saldos"
TITULO = "Sumas y saldos"
INTERNO = False
DESPLAZAMIENTOS = [0, -1]
# `nivel`: dígitos de cuenta que se muestran (3, 4 o 5). `top`: 0 = todas las cuentas; con un
# tope se listan las de mayor movimiento del ejercicio. `solo_con_saldo`: oculta las que quedan
# a cero (sin saldo inicial, sin debe y sin haber).
PARAMETROS: dict[str, Any] = {"nivel": 3, "top": 0, "solo_con_saldo": False}

NIVELES_VALIDOS = (3, 4, 5)
CUENTA_VACIA = "(sin cuenta)"

# Nombres de los grupos del PGC (etiquetas, no cifras: sirven para leer el informe en pantalla).
GRUPOS = {
    "1": "Financiación básica",
    "2": "Inmovilizado",
    "3": "Existencias",
    "4": "Acreedores y deudores por operaciones comerciales",
    "5": "Cuentas financieras",
    "6": "Compras y gastos",
    "7": "Ventas e ingresos",
    "8": "Gastos imputados al patrimonio neto",
    "9": "Ingresos imputados al patrimonio neto",
}

AVISO_ORIGEN = ("El saldo inicial puede proceder de los asientos de apertura del propio ejercicio "
                "o, si el ejercicio no trae apertura, de los saldos de cierre del ejercicio "
                "anterior; el informe dice en cada caso cuál de los dos se ha usado.")


# ---------- parámetros ----------

def _a_entero(valor: Any, defecto: int) -> int:
    if isinstance(valor, bool):
        return defecto
    if isinstance(valor, int):
        return valor
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return defecto


def normalizar_nivel(valor: Any) -> tuple[int, str]:
    """Nivel de agregación (3, 4 o 5 dígitos). Un valor raro cae al 3, nunca revienta."""
    n = _a_entero(valor, PARAMETROS["nivel"])
    if n in NIVELES_VALIDOS:
        return n, ""
    return int(PARAMETROS["nivel"]), (f"El nivel «{valor}» no es válido (se admite 3, 4 o 5 "
                                      f"dígitos); se usa el nivel {PARAMETROS['nivel']}.")


def normalizar_top(valor: Any) -> tuple[int, str]:
    """Número máximo de cuentas a listar; 0 (o negativo) = todas."""
    t = _a_entero(valor, 0)
    if t < 0:
        return 0, f"El tope «{valor}» no puede ser negativo; se listan todas las cuentas."
    return t, ""


def normalizar_bool(valor: Any) -> bool:
    if isinstance(valor, str):
        return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}
    return bool(valor)


# ---------- apertura del ejercicio ----------

def _sin_acentos(texto: str) -> str:
    tabla = str.maketrans("áéíóúàèìòùäëïöü", "aeiouaeiouaeiou")
    return (texto or "").lower().translate(tabla)


def detectar_apertura(lineas: Iterable[Linea]) -> tuple[set[tuple[str, str]], list[Linea]]:
    """Devuelve ({(serie, documento)}, líneas de apertura).

    Regla (deducida de los datos reales, ver docstring del módulo): el asiento entero está fechado
    el 1 de enero y alguna de sus descripciones dice «apertura». Se descartan los asientos de
    cuadre/descuadre manuales, que también hablan de apertura pero son movimientos del ejercicio.
    """
    grupos: dict[tuple[str, str], list[Linea]] = defaultdict(list)
    for l in lineas:
        grupos[(l.serie, l.documento)].append(l)

    claves: set[tuple[str, str]] = set()
    for clave, ls in grupos.items():
        if {fecha_a_int(l.fecha) % 10000 for l in ls} != {101}:
            continue
        texto = " ".join(_sin_acentos(l.descripcion) for l in ls)
        if "cuadre" in texto or "descuadre" in texto:
            continue
        if "apert" in texto:
            claves.add(clave)
    return claves, [l for l in lineas if (l.serie, l.documento) in claves]


# ---------- agregación ----------

def _clave(cuenta: str, nivel: int) -> str:
    c = str(cuenta or "")
    return c[:nivel] if len(c) >= nivel else c


def _agregar(lineas: Iterable[Linea], nivel: int) -> dict[str, list[float]]:
    """{cuenta(nivel): [debe, haber, n_lineas, n_cuentas_reales]} por prefijo."""
    mapa: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0, 0])
    vistas: dict[str, set[str]] = defaultdict(set)
    for l in lineas:
        k = _clave(l.cuenta, nivel)
        fila = mapa[k]
        fila[0] += l.debe
        fila[1] += l.haber
        fila[2] += 1
        vistas[k].add(l.cuenta)
    for k, cuentas in vistas.items():
        mapa[k][3] = len(cuentas)
    return dict(mapa)


def grupo_de(cuenta: str) -> str:
    c = str(cuenta or "")
    return c[:1] if c[:1].isdigit() else ""


def etiqueta_grupo(grupo: str) -> str:
    if not grupo:
        return CUENTA_VACIA
    return f"Grupo {grupo} · {GRUPOS.get(grupo, 'sin clasificar')}"


def _etiqueta_cuenta(cuenta: str) -> str:
    return CUENTA_VACIA if not cuenta else cuenta


# ---------- cálculo ----------

def calcular(por_anio: dict[int, list[Linea]] | list[Linea], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sumas y saldos del ejercicio, en números (contrato de módulos)."""
    ctx = dict(ctx or {})
    avisos: list[str] = [AVISO_ORIGEN]

    if isinstance(por_anio, (list, tuple)):        # tolera que pasen las líneas directamente
        lineas_ejercicio = list(por_anio)
        year = _a_entero(ctx.get("year"), 0)
        lineas_anterior: list[Linea] = []
    else:
        year = _a_entero(ctx.get("year"), 0) or (max(por_anio) if por_anio else 0)
        lineas_ejercicio = list(por_anio.get(year) or [])
        lineas_anterior = list(por_anio.get(year - 1) or [])

    nivel, aviso_nivel = normalizar_nivel(ctx.get("nivel", PARAMETROS["nivel"]))
    if aviso_nivel:
        avisos.append(aviso_nivel)
    top, aviso_top = normalizar_top(ctx.get("top", PARAMETROS["top"]))
    if aviso_top:
        avisos.append(aviso_top)
    solo_con_saldo = normalizar_bool(ctx.get("solo_con_saldo", PARAMETROS["solo_con_saldo"]))

    if not lineas_ejercicio:
        avisos.append(f"No hay apuntes cargados del ejercicio {year}: todas las cifras salen a cero.")

    # ---------- de dónde sale el saldo inicial ----------
    claves_apertura, lineas_apertura = detectar_apertura(lineas_ejercicio)
    lineas_movimiento = ([l for l in lineas_ejercicio if (l.serie, l.documento) not in claves_apertura]
                         if claves_apertura else list(lineas_ejercicio))

    cierre_anterior = detectar_cierre(lineas_anterior)
    claves_cierre = set(cierre_anterior["asientos_cierre"])
    lineas_inicial = [l for l in lineas_anterior if (l.serie, l.documento) not in claves_cierre]

    if lineas_apertura:
        origen = "apertura"
        asientos_ap = sorted({f"{l.serie}-{l.documento}" for l in lineas_apertura})
        uno = len(asientos_ap) == 1
        avisos.append(
            f"El saldo inicial es {'el asiento' if uno else f'los {len(asientos_ap)} asientos'} "
            f"de apertura del propio ejercicio {year} ({len(lineas_apertura)} líneas: "
            f"{', '.join(asientos_ap[:6])}" + (", …" if len(asientos_ap) > 6 else "") + "). "
            f"{'Ese asiento no se suma' if uno else 'Esos asientos no se suman'} en las columnas "
            "del debe y del haber del ejercicio porque su saldo ya está en la columna de saldo "
            "inicial.")
        origen_texto = (f"Apertura del ejercicio {year}: {len(lineas_apertura)} líneas de "
                        f"{'un asiento' if uno else f'{len(asientos_ap)} asientos'} de apertura.")
    elif lineas_inicial:
        origen = "cierre_anterior"
        avisos.append(
            f"El ejercicio {year} no trae asiento de apertura: el saldo inicial son los saldos de "
            f"cierre del ejercicio {year - 1} ({len(lineas_inicial)} líneas), es decir lo que la "
            f"contabilidad arrastra al 1 de enero.")
        origen_texto = (f"Saldos de cierre del ejercicio {year - 1}: el ejercicio {year} no trae "
                        f"asiento de apertura, así que se parte de los {len(lineas_inicial)} "
                        f"apuntes del ejercicio anterior.")
    else:
        origen = "ninguno"
        avisos.append(
            f"No hay asiento de apertura del ejercicio {year} ni apuntes del ejercicio {year - 1}: "
            "el saldo inicial sale a cero y el informe muestra sólo los movimientos del ejercicio. "
            "Si el cliente espera saldos de apertura, hay que cargar el ejercicio anterior.")
        origen_texto = ("No hay apertura ni ejercicio anterior cargado: los saldos iniciales salen "
                        "a cero.")

    # ---------- filas ----------
    agregado_inicial = _agregar(lineas_inicial, nivel)
    agregado_movimiento = _agregar(lineas_movimiento, nivel)

    filas: list[dict[str, Any]] = []
    for cuenta in sorted(set(agregado_inicial) | set(agregado_movimiento)):
        i = agregado_inicial.get(cuenta, [0.0, 0.0, 0, 0])
        m = agregado_movimiento.get(cuenta, [0.0, 0.0, 0, 0])
        saldo_inicial = round(i[0] - i[1], 2)
        debe, haber = round(m[0], 2), round(m[1], 2)
        filas.append({
            "cuenta": cuenta, "etiqueta": _etiqueta_cuenta(cuenta), "grupo": grupo_de(cuenta),
            "saldo_inicial": saldo_inicial, "debe": debe, "haber": haber,
            "saldo_final": round(saldo_inicial + debe - haber, 2),
            "n_lineas_inicial": int(i[2]), "n_lineas": int(m[2]),
        })

    def cero(f: dict[str, Any]) -> bool:
        return (abs(f["saldo_inicial"]) < 0.005 and abs(f["debe"]) < 0.005
                and abs(f["haber"]) < 0.005)

    n_cuentas_total = len(filas)
    if solo_con_saldo:
        filas = [f for f in filas if not cero(f)]

    # `top`: las cuentas de mayor movimiento del ejercicio, siempre devueltas por orden de código.
    n_ocultas_por_tope = 0
    if top and len(filas) > top:
        n_ocultas_por_tope = len(filas) - top
        mejores = sorted(filas, key=lambda f: (-(f["debe"] + f["haber"]),
                                               -abs(f["saldo_final"]), f["cuenta"]))[:top]
        filas = sorted(mejores, key=lambda f: f["cuenta"])

    totales = {
        "saldo_inicial": round(sum(f["saldo_inicial"] for f in filas), 2),
        "debe": round(sum(f["debe"] for f in filas), 2),
        "haber": round(sum(f["haber"] for f in filas), 2),
        "saldo_final": round(sum(f["saldo_final"] for f in filas), 2),
    }

    # ---------- subtotales por grupo (se pintan en el detalle cuando el nivel es 3) ----------
    subtotales: list[dict[str, Any]] = []
    for g in sorted({f["grupo"] for f in filas}, key=lambda g: (len(g) == 0, g)):
        del_grupo = [f for f in filas if f["grupo"] == g]
        subtotales.append({
            "grupo": g, "etiqueta": etiqueta_grupo(g), "n_cuentas": len(del_grupo),
            "saldo_inicial": round(sum(f["saldo_inicial"] for f in del_grupo), 2),
            "debe": round(sum(f["debe"] for f in del_grupo), 2),
            "haber": round(sum(f["haber"] for f in del_grupo), 2),
            "saldo_final": round(sum(f["saldo_final"] for f in del_grupo), 2),
        })

    # ---------- comprobaciones de integridad (sobre TODO el ejercicio, no sobre lo listado) ----------
    suma_debe = round(sum(l.debe for l in lineas_movimiento), 2)
    suma_haber = round(sum(l.haber for l in lineas_movimiento), 2)
    descuadre_anterior = round(sum(l.debe for l in lineas_anterior)
                               - sum(l.haber for l in lineas_anterior), 2)
    saldo_inicial_total = round(sum(v[0] - v[1] for v in agregado_inicial.values()), 2)
    s_inicial_completo = sum(v[0] - v[1] for v in agregado_inicial.values())
    s_mov_completo = sum(v[0] - v[1] for v in agregado_movimiento.values())
    suma_saldo_final = round(s_inicial_completo + s_mov_completo, 2)

    integridad = {
        "suma_debe": suma_debe, "suma_haber": suma_haber,
        "descuadre": round(suma_debe - suma_haber, 2),
        "suma_saldo_inicial": round(saldo_inicial_total, 2),
        "suma_saldo_final": suma_saldo_final,
        "descuadre_anterior": descuadre_anterior,
        "n_lineas_ejercicio": len(lineas_ejercicio),
        "n_lineas_movimiento": len(lineas_movimiento),
        "n_lineas_inicial": len(lineas_inicial),
        "n_asientos_apertura": len({f"{l.serie}-{l.documento}" for l in lineas_apertura}),
        "cuadra_debe_haber": abs(suma_debe - suma_haber) < 0.01,
        "cuadra_saldos": abs(suma_saldo_final) < 0.01,
    }

    if not integridad["cuadra_debe_haber"]:
        avisos.append(
            f"El libro no cuadra: ΣDebe − ΣHaber = {fmt(integridad['descuadre'])} "
            f"({integridad['n_lineas_movimiento']} líneas del ejercicio). Las columnas de este "
            "informe salen de los apuntes tal cual: comprobar el ejercicio que llegue incompleto.")
    if not integridad["cuadra_saldos"]:
        causa = ""
        if origen == "cierre_anterior" and abs(descuadre_anterior) >= 0.01 and \
                abs(descuadre_anterior - suma_saldo_final) < 0.01:
            causa = (f" El descuadre coincide con el del propio ejercicio {year - 1} "
                     f"(ΣDebe − ΣHaber = {fmt(descuadre_anterior)}): llega incompleto y arrastra "
                     f"el descuadre a los saldos iniciales.")
        avisos.append(
            f"Σ(Saldo final) = {fmt(suma_saldo_final)}, no cero. En un ejercicio cuadrado la suma "
            "de todos los saldos finales vale cero." + causa +
            " Otra causa habitual: cuentas de gasto e ingreso que el ejercicio anterior no cerró "
            "contra la 129 al no estar cerrado en el ERP.")

    # cuentas de gasto e ingreso que arrastran saldo: sólo tiene sentido avisarlo con el cierre previo
    if origen == "cierre_anterior":
        gastos_ini = round(sum(v[0] - v[1] for k, v in agregado_inicial.items() if k[:1] == "6"), 2)
        ingresos_ini = round(sum(v[0] - v[1] for k, v in agregado_inicial.items() if k[:1] == "7"), 2)
        if abs(gastos_ini) >= 0.01 or abs(ingresos_ini) >= 0.01:
            avisos.append(
                f"El ejercicio {year - 1} no está cerrado y arrastra saldo a las cuentas de gasto e "
                f"ingreso: {fmt(gastos_ini)} en el grupo 6 (gastos) y {fmt(ingresos_ini)} en el 7 "
                f"(ingresos), {fmt(gastos_ini + ingresos_ini)} de resultado. Si el ejercicio "
                "anterior estuviera cerrado, su resultado estaría en la 129 y estas cuentas "
                "arrancarían a cero.")
    sin_cuenta_mov = [l for l in lineas_movimiento if not l.cuenta]
    sin_cuenta_ini = [l for l in lineas_inicial if not l.cuenta]
    if sin_cuenta_mov or sin_cuenta_ini:
        detalle = []
        if sin_cuenta_mov:
            detalle.append(f"{len(sin_cuenta_mov)} líneas del ejercicio "
                           f"({fmt(sum(l.debe + l.haber for l in sin_cuenta_mov))} de movimiento)")
        if sin_cuenta_ini:
            detalle.append(f"{len(sin_cuenta_ini)} líneas del saldo inicial")
        avisos.append(
            f"Hay apuntes del ERP con el campo Cuenta vacío ({' y '.join(detalle)}): se muestran "
            f"en la fila «{CUENTA_VACIA}» del informe, no en la cuenta que les correspondería. "
            "Conviene corregirlos en el ERP.")
    if n_ocultas_por_tope:
        avisos.append(
            f"El parámetro top={top} deja fuera {n_ocultas_por_tope} de {n_cuentas_total} cuentas: "
            "se listan las de mayor movimiento del ejercicio y la fila de totales suma sólo las "
            "cuentas mostradas. Los totales del ejercicio completo van en las comprobaciones de "
            "integridad.")
    if solo_con_saldo:
        avisos.append(f"Se ocultan las cuentas que quedan a cero (solo_con_saldo): "
                      f"{n_cuentas_total - len(filas) - n_ocultas_por_tope} de {n_cuentas_total}.")

    avisos_pantalla = [a for a in avisos if a != AVISO_ORIGEN]

    datos: dict[str, Any] = {
        "year": year, "year_anterior": year - 1,
        "nivel": nivel, "top": top, "solo_con_saldo": bool(solo_con_saldo),
        "origen_inicial": origen, "origen_inicial_texto": origen_texto,
        "filas": filas, "subtotales_grupo": subtotales, "totales": totales,
        "n_cuentas": len(filas), "n_cuentas_total": n_cuentas_total,
        "n_ocultas_por_tope": n_ocultas_por_tope,
        "integridad": integridad,
        "avisos": avisos,
        # las claves que pide el contrato, aplanadas para el JSON del portal
        "nCuentas": len(filas),
        "totalDebe": totales["debe"], "totalHaber": totales["haber"],
        "saldoFinal": totales["saldo_final"], "saldoInicial": totales["saldo_inicial"],
        "descuadre": integridad["descuadre"],
    }
    datos["data"] = dict(datos)
    datos["avisos_pantalla"] = avisos_pantalla
    return datos


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    """KPIs del panel: número de cuentas, sumas del debe y del haber y descuadre."""
    integridad = datos.get("integridad") or {}
    totales = datos.get("totales") or {}
    return {
        "n_cuentas": datos.get("n_cuentas", len(datos.get("filas") or [])),
        "total_debe": totales.get("debe", integridad.get("suma_debe", 0.0)),
        "total_haber": totales.get("haber", integridad.get("suma_haber", 0.0)),
        "descuadre": integridad.get("descuadre", 0.0),
        # de más, para el panel: no sustituyen a los cuatro anteriores
        "n_cuentas_total": datos.get("n_cuentas_total", 0),
        "saldo_inicial": totales.get("saldo_inicial", 0.0),
        "saldo_final": integridad.get("suma_saldo_final", totales.get("saldo_final", 0.0)),
        "descuadre_saldos": integridad.get("suma_saldo_final", 0.0),
        "origen_inicial": datos.get("origen_inicial", ""),
        "nivel": datos.get("nivel"),
        "n_avisos": len(datos.get("avisos") or []),
    }


# ---------- informe ----------

def _tabla_detalle(datos: dict[str, Any]) -> str:
    """Tabla del detalle. Con nivel 3 se cierra cada grupo (1..9) con su subtotal."""
    filas = datos.get("filas") or []
    nivel = int(datos.get("nivel") or 3)
    subtotales = {s["grupo"]: s for s in datos.get("subtotales_grupo") or {}}
    filas_html: list[list[Any]] = []

    def _subtotal(grupo: str) -> list[Any]:
        s = subtotales[grupo]
        n = s["n_cuentas"]
        return [
            f'<b style="color:{inf.AZUL}">{inf.esc(s["etiqueta"])} '
            f'<span style="color:#5b6b80;font-weight:normal">({n} cuenta{"s" if n != 1 else ""})'
            '</span></b>',
            f'<b>{inf.importe(s["saldo_inicial"])}</b>',
            f'<b>{inf.importe(s["debe"])}</b>',
            f'<b>{inf.importe(s["haber"])}</b>',
            f'<b>{inf.importe(s["saldo_final"])}</b>',
        ]

    for i, f in enumerate(filas):
        filas_html.append([
            f["etiqueta"], inf.importe(f["saldo_inicial"]), inf.importe(f["debe"]),
            inf.importe(f["haber"]), inf.importe(f["saldo_final"]),
        ])
        # subtotal del grupo al terminarlo, sólo si agrupa más de una cuenta (si no, es la misma fila)
        if nivel == 3 and subtotales.get(f["grupo"], {}).get("n_cuentas", 0) > 1:
            siguiente = filas[i + 1]["grupo"] if i + 1 < len(filas) else None
            if siguiente != f["grupo"]:
                filas_html.append(_subtotal(f["grupo"]))
    t = datos.get("totales") or {}
    return inf.tabla(
        ["Cuenta", "Saldo inicial", "Debe (ejercicio)", "Haber (ejercicio)", "Saldo final"],
        filas_html,
        totales=[f'TOTAL ({datos.get("n_cuentas", 0)} cuentas)', inf.importe(t.get("saldo_inicial", 0.0)),
                 inf.importe(t.get("debe", 0.0)), inf.importe(t.get("haber", 0.0)),
                 inf.importe(t.get("saldo_final", 0.0))],
        anchos=["16%", "21%", "21%", "21%", "21%"],
    )


def informe_html(datos: dict[str, Any], ctx: dict[str, Any] | None = None) -> str:
    """Informe para pantalla: empieza por `<div`, Arial 13 px, CSS inline, importes es-ES."""
    ctx = dict(ctx or {})
    year = int(datos.get("year") or ctx.get("year") or 0)
    nivel = int(datos.get("nivel") or 3)
    integridad = datos.get("integridad") or {}
    totales = datos.get("totales") or {}
    origen = datos.get("origen_inicial")
    empresa = ctx.get("empresa") or ""

    kpis = inf.kpis([
        ("Cuentas", f'{datos.get("n_cuentas", 0)}' + (
            f' / {datos.get("n_cuentas_total", 0)}' if datos.get("n_cuentas_total", 0)
            != datos.get("n_cuentas", 0) else "")),
        ("Suma del debe", inf.importe(integridad.get("suma_debe", 0.0))),
        ("Suma del haber", inf.importe(integridad.get("suma_haber", 0.0))),
        ("Σ saldo final", inf.importe(integridad.get("suma_saldo_final", 0.0))),
    ])

    # resumen por grupos (1..9), siempre, aunque el detalle vaya a otro nivel
    filas_grupos = []
    for s in datos.get("subtotales_grupo") or []:
        filas_grupos.append([s["etiqueta"], str(s["n_cuentas"]), inf.importe(s["saldo_inicial"]),
                             inf.importe(s["debe"]), inf.importe(s["haber"]),
                             inf.importe(s["saldo_final"])])
    tabla_grupos = inf.tabla(["Grupo", "Cuentas", "Saldo inicial", "Debe", "Haber", "Saldo final"],
                             filas_grupos,
                             totales=["TOTAL", str(datos.get("n_cuentas", 0)),
                                      inf.importe(totales.get("saldo_inicial", 0.0)),
                                      inf.importe(totales.get("debe", 0.0)),
                                      inf.importe(totales.get("haber", 0.0)),
                                      inf.importe(totales.get("saldo_final", 0.0))],
                             anchos=["40%", "8%", "13%", "13%", "13%", "13%"])

    nota_detalle = (f"Una fila por cuenta con {nivel} dígitos. El saldo inicial se repite en la "
                    f"columna del debe y del haber del ejercicio, que recoge sólo los movimientos "
                    f"de {year}"
                    + (" (los asientos de apertura no se suman aquí: su saldo está en la columna "
                       "de saldo inicial)." if origen == "apertura" else "."))
    if datos.get("n_ocultas_por_tope"):
        nota_detalle += (f" Se listan las {datos.get('n_cuentas', 0)} cuentas de mayor movimiento "
                         f"de {datos.get('n_cuentas_total', 0)}: la fila de TOTAL suma sólo las "
                         "mostradas.")
    if datos.get("solo_con_saldo"):
        nota_detalle += " Las cuentas que quedan a cero no se muestran."

    # comprobaciones de integridad, siempre visibles
    def lectura(ok: bool) -> str:
        color = inf.POSITIVO if ok else inf.NEGATIVO
        return (f'<span style="color:{color};font-weight:bold">'
                + ("Cuadra" if ok else "No cuadra — revisar") + "</span>")

    filas_integridad = [
        [f"ΣDebe del ejercicio ({year})", inf.importe(integridad.get("suma_debe", 0.0)),
         f'{integridad.get("n_lineas_movimiento", 0)} líneas',
         lectura(bool(integridad.get("cuadra_debe_haber")))],
        [f"ΣHaber del ejercicio ({year})", inf.importe(integridad.get("suma_haber", 0.0)),
         "Las dos columnas del libro",
         lectura(bool(integridad.get("cuadra_debe_haber")))],
        ["Diferencia ΣDebe − ΣHaber", inf.importe(integridad.get("descuadre", 0.0)),
         "Tiene que ser cero", lectura(abs(integridad.get("descuadre", 0.0)) < 0.01)],
        ["Σ(Saldo final)", inf.importe(integridad.get("suma_saldo_final", 0.0)),
         "Debe valer cero", lectura(bool(integridad.get("cuadra_saldos")))],
        ["Σ(Saldo inicial)", inf.importe(integridad.get("suma_saldo_inicial", 0.0)),
         f'{integridad.get("n_lineas_inicial", 0)} líneas del saldo inicial', ""],
    ]
    tabla_integridad = inf.tabla(["Comprobación", "Importe", "Detalle", "Resultado"],
                                 filas_integridad, anchos=["34%", "22%", "26%", "18%"])

    bloques_avisos = "".join(inf.aviso(a, tipo="alerta") for a in datos.get("avisos") or [])
    if not bloques_avisos:
        bloques_avisos = inf.aviso("Sin avisos: no falta ningún dato para calcular este informe.",
                                   tipo="ok", titulo="Sin incidencias")

    cuerpo = (
        inf.aviso(datos.get("origen_inicial_texto", ""), tipo="info",
                  titulo="Origen del saldo inicial")
        + kpis
        + inf.seccion("Resumen por grupos", tabla_grupos,
                      nota="Los nueve grupos del PGC. Sólo aparecen los que tienen movimiento o saldo.")
        + inf.seccion(f"Detalle de cuentas ({nivel} dígitos)", _tabla_detalle(datos),
                      nota=nota_detalle)
        + inf.seccion("Comprobaciones de integridad", tabla_integridad,
                      nota="Las hace el propio informe sobre los apuntes cargados, antes de "
                           "cualquier selección de cuentas.")
        + inf.seccion("Avisos", bloques_avisos,
                      nota="Todo lo que el informe no puede sacar de los apuntes se declara aquí.")
    )
    return inf.envoltura(
        titulo=TITULO,
        subtitulo=f"Ejercicio {year} · cuentas a {nivel} dígitos · "
                  + ("con apertura" if origen == "apertura" else
                     f"saldos de cierre de {year - 1}" if origen == "cierre_anterior" else "sin apertura"),
        empresa=empresa, ejercicio=year, cuerpo=cuerpo,
        meta={"Datos": "ERP apiCON (apuntes del ejercicio)",
              "Saldo inicial": {"apertura": "asientos de apertura del ejercicio",
                                "cierre_anterior": f"saldos de cierre de {year - 1}",
                                "ninguno": "sin apertura ni ejercicio anterior"}.get(origen, "—")},
    )


__all__ = ["NOMBRE", "TITULO", "INTERNO", "DESPLAZAMIENTOS", "PARAMETROS", "calcular",
           "informe_html", "metricas_dashboard", "detectar_apertura", "normalizar_nivel",
           "normalizar_top", "grupo_de", "etiqueta_grupo"]
