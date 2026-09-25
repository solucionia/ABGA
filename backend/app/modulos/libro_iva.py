"""Módulo `libro_iva` — Libro de IVA repercutido y soportado, por mes y por trimestre.

Lo que responde: cuánto IVA ha repercutido y cuánto ha soportado la sociedad en cada mes y en
cada trimestre del ejercicio, cuál es la diferencia (a ingresar o a compensar/devolver) y el
detalle de los movimientos que la componen, sin tener que llamar al asesor.

De dónde salen los números (nada inventado):

- **Cuotas de IVA.** De las cuentas de IVA del PGC, incluidas sus subcuentas por prefijo:
  repercutido = saldo acreedor de las 477x, soportado = saldo deudor de las 472x. Se calcula
  sobre las líneas del ejercicio agrupadas por mes y por trimestre con `por_mes`/`trimestre_de`
  del motor contable.
- **Base imponible.** El ERP **no** la trae en los apuntes, así que se *deriva de la contrapartida
  del mismo asiento*: la suma de las cuentas de ingreso (7xx) para el IVA repercutido y la de las
  cuentas de gasto (6xx) para el soportado. El método se declara en `datos["avisos"]` y en una
  sección del informe; los movimientos cuyo asiento no permite derivarla se quedan **con la base
  vacía** (no se estiman) y se cuentan.
- **Tipo (%).** Cuota ÷ base, sólo cuando la base se ha podido derivar. No se aplican tipos
  impositivos teóricos: si la base no está, el tipo tampoco.
- **Movimiento** = un asiento con líneas de IVA, no una línea suelta: el ERP desdobla una misma
  factura en varias subcuentas de IVA (una por tipo), y sumarlas por asiento es lo que ve el
  cliente en su libro de facturas emitidas / recibidas.

Cosas que el informe declara en vez de disimular:

1. Es el **IVA contabilizado**, no la declaración presentada (modelo 303): la imputación temporal,
   las operaciones no contabilizadas o las deducciones que no pasan por 472/477 pueden hacer que
   no coincida con el modelo.
2. Las **bases son derivadas**, no vienen del ERP.
3. Los asientos con 472 y 477 a la vez y misma cuota (IVA devengado y deducible en la misma
   operación: adquisiciones intracomunitarias, inversión del sujeto pasivo) suman importe en los
   dos lados y se anulan en la diferencia. Se cuentan y se cuantifican.
4. El **detalle** se limita a `MAX_MOV_DETALLE` movimientos por trimestre y libro (los de mayor
   cuota) para que el informe se pueda abrir; **los subtotales y el resumen suman todos** los
   movimientos y el informe lo dice.

El módulo no llama al ERP ni a la caché: recibe `por_anio` y `ctx` ya cargados (contrato de
módulos) y nunca escribe por pantalla; los avisos van en `datos["avisos"]`.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable

from .. import informes as inf
from ..ledger import (MESES, MESES_LARGOS, Linea, fecha_a_int, fmt, fmt_pct, mes_de,
                      nombre_tercero, trimestre_de)

NOMBRE = "libro_iva"
TITULO = "Libro de IVA"
INTERNO = False
DESPLAZAMIENTOS = [0]
# `trimestre`: None = los cuatro trimestres del ejercicio; 1..4 = sólo ese (admite "3", "Q3", "3T").
PARAMETROS: dict[str, Any] = {"trimestre": None}

# --- cuentas (prefijos PGC; se incluyen las subcuentas) ---
P_REPERCUTIDO = ["477"]          # Hacienda Pública, IVA repercutido
P_SOPORTADO = ["472"]            # Hacienda Pública, IVA soportado
P_INGRESO = ("7",)               # contrapartida del repercutido (cuentas de ingreso)
P_GASTO = ("6",)                 # contrapartida del soportado (cuentas de gasto)

TRIMESTRE_PERIODO = ["enero–marzo", "abril–junio", "julio–septiembre", "octubre–diciembre"]

MAX_MOV_DETALLE = 40             # movimientos listados por trimestre y libro (los de mayor cuota)
MAX_MOV_DETALLE_UNO = 150        # lo mismo cuando el informe se limita a un trimestre concreto
LARGO_DESC = 74                  # caracteres de la descripción en el detalle


# ---------- utilidades ----------

def _r(x: Any) -> float:
    """Redondeo a céntimos sin «-0,00»: el contrato pide números, no texto formateado."""
    try:
        v = round(float(x or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if v == 0 else v


def normalizar_trimestre(valor: Any) -> tuple[int | None, str]:
    """None → los cuatro trimestres; 1..4 (o «3», «Q3», «3T») → sólo ese.

    Un valor que no se entiende **no se adivina**: se devuelve None (los cuatro trimestres) y el
    motivo, para que el informe lo declare.
    """
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None, ""
    if isinstance(valor, bool):  # bool es subclase de int: fuera antes de mirar enteros
        return None, f"El trimestre «{valor}» no es válido; se muestran los cuatro trimestres."
    if isinstance(valor, int) and 1 <= valor <= 4:
        return valor, ""
    t = str(valor).strip().upper()
    if len(t) > 1 and t[0] == "Q" and t[1:].isdigit():
        t = t[1:]
    elif len(t) > 1 and t[-1] == "T" and t[:-1].isdigit():
        t = t[:-1]
    if t.isdigit() and 1 <= int(t) <= 4:
        return int(t), ""
    return None, (f"El trimestre «{valor}» no se reconoce (se espera 1-4, «Q1» o «1T»); "
                  "se muestran los cuatro trimestres.")


def _fecha_texto(f: int) -> str:
    if not f:
        return "—"
    return f"{f % 100:02d}/{(f // 100) % 100:02d}/{f // 10000}"


def _clave_asiento(l: Linea) -> tuple[int, str, str]:
    """Identifica el asiento: fecha + serie + documento (el ERP no da un id de asiento)."""
    return (fecha_a_int(l.fecha), str(l.serie or ""), str(l.documento or ""))


# ---------- movimientos ----------

def movimientos_de(lineas: Iterable[Linea]) -> list[dict[str, Any]]:
    """Un movimiento por asiento y signo del IVA, con su base derivada de la contrapartida.

    Devuelve dicts con: `tipo` ("R" repercutido / "S" soportado), fecha, documento, descripción,
    tercero, `base` (None si no se puede derivar), `cuota`, `tipo_pct` (None si no hay base),
    `cuentas` (subcuentas de IVA sumadas), `n_lineas_iva`, mes y trimestre.
    """
    asientos: "OrderedDict[tuple[int, str, str], list[Linea]]" = OrderedDict()
    for l in lineas:
        asientos.setdefault(_clave_asiento(l), []).append(l)

    movimientos: list[dict[str, Any]] = []
    for (fecha, serie, doc), ls in asientos.items():
        lineas_rep = [x for x in ls if any(x.cuenta.startswith(p) for p in P_REPERCUTIDO)]
        lineas_sop = [x for x in ls if any(x.cuenta.startswith(p) for p in P_SOPORTADO)]
        if not lineas_rep and not lineas_sop:
            continue

        ingresos = [x for x in ls if x.cuenta.startswith(P_INGRESO)]
        gastos = [x for x in ls if x.cuenta.startswith(P_GASTO)]
        base_rep = sum(x.haber - x.debe for x in ingresos)
        base_sop = sum(x.debe - x.haber for x in gastos)

        descripcion = next((x.descripcion for x in ls if x.descripcion), "")
        tercero = nombre_tercero(next((x.tercero for x in ls if x.tercero), ""), descripcion)

        for clase, propias, base, derivable in (("R", lineas_rep, base_rep, bool(ingresos)),
                                                ("S", lineas_sop, base_sop, bool(gastos))):
            if not propias:
                continue
            cuota = sum((x.haber - x.debe) if clase == "R" else (x.debe - x.haber) for x in propias)
            if abs(cuota) < 0.005:      # el asiento ya se anula a sí mismo: no es un movimiento
                continue
            base_mov = round(base, 2) if derivable else None
            if base_mov is not None and abs(base_mov) < 0.005:
                base_mov = 0.0
            movimientos.append({
                "tipo": clase,
                "fecha": fecha,
                "fecha_texto": _fecha_texto(fecha),
                "serie": serie,
                "documento": doc,
                "documento_texto": (f"{serie}/{doc}" if serie and doc else (doc or serie or "—")),
                "descripcion": descripcion,
                "tercero": tercero,
                "base": base_mov,
                "cuota": _r(cuota),
                "tipo_pct": _r(cuota / base_mov * 100) if base_mov else None,
                "cuentas": sorted({x.cuenta for x in propias}),
                "n_lineas_iva": len(propias),
                "mes": mes_de(fecha),
                "trimestre": trimestre_de(fecha),
            })
    return movimientos


def _bloque(movs: list[dict[str, Any]]) -> dict[str, Any]:
    """Agregado de un periodo (mes, trimestre o ejercicio): cuotas, bases y diferencia."""
    rep = [m for m in movs if m["tipo"] == "R"]
    sop = [m for m in movs if m["tipo"] == "S"]
    # se redondea cada cuota y la diferencia se calcula con los céntimos que se enseñan: así la
    # tabla cuadra a la vista (repercutido − soportado = diferencia) y la lectura no baila.
    suma_rep = _r(sum(m["cuota"] for m in rep))
    suma_sop = _r(sum(m["cuota"] for m in sop))
    diferencia = _r(suma_rep - suma_sop)
    con_base_rep = [m for m in rep if m["base"] is not None]
    con_base_sop = [m for m in sop if m["base"] is not None]
    base_rep = sum(m["base"] for m in con_base_rep)
    base_sop = sum(m["base"] for m in con_base_sop)
    sin_base = [m for m in movs if m["base"] is None]
    return {
        "repercutido": suma_rep,
        "soportado": suma_sop,
        "diferencia": diferencia,
        "a_ingresar": _r(max(0.0, diferencia)),
        "a_compensar": _r(abs(min(0.0, diferencia))),
        "resultado": ("A ingresar" if diferencia > 0 else
                      "A compensar o a devolver" if diferencia < 0 else "Cero"),
        "baseRepercutida": _r(base_rep),
        "baseSoportada": _r(base_sop),
        "cuotaConBaseRepercutido": _r(sum(m["cuota"] for m in con_base_rep)),
        "cuotaConBaseSoportado": _r(sum(m["cuota"] for m in con_base_sop)),
        "nMovimientos": len(movs),
        "nRepercutido": len(rep),
        "nSoportado": len(sop),
        "nSinBase": len(sin_base),
        "nSinBaseRepercutido": len(rep) - len(con_base_rep),
        "nSinBaseSoportado": len(sop) - len(con_base_sop),
        "cuotaSinBase": _r(sum(m["cuota"] for m in sin_base)),
    }


def _filas_trimestre(movs: list[dict[str, Any]], tipo: str, limite: int,
                     truncados: dict[tuple[int, str], tuple[int, int]] | None = None,
                     trimestre: int = 0) -> tuple[list[list[Any]], int]:
    """Filas del detalle de un libro y trimestre, y cuántos movimientos hay en total.

    Si hay más de `limite`, se listan los de mayor cuota (el informe lo declara) y se anota el
    recorte en `truncados`, para poder avisar de cuántos movimientos se han quedado fuera.
    """
    del_tipo = [m for m in movs if m["tipo"] == tipo]
    listados = sorted(del_tipo, key=lambda m: -abs(m["cuota"]))[:limite] if limite else del_tipo
    listados.sort(key=lambda m: (m["fecha"], m["serie"], m["documento"]))
    if truncados is not None and len(listados) < len(del_tipo):
        truncados[(trimestre, tipo)] = (len(del_tipo), len(listados))
    filas = [[m["fecha_texto"], m["documento_texto"], _celda_descripcion(m),
              _celda_base(m["base"]), _celda_base(m["cuota"]), _celda_tipo(m["tipo_pct"])]
             for m in listados]
    return filas, len(del_tipo)


# ---------- celdas con formato ----------

def _celda_base(valor: Any) -> str:
    return inf.importe(valor)      # None → «—» en gris, sin inventar la base


def _celda_tipo(t: Any) -> str:
    if not isinstance(t, (int, float)) or isinstance(t, bool):
        return '<span style="color:#666">—</span>'
    return f'<span style="color:#333;white-space:nowrap">{fmt_pct(t)}</span>'


def _celda_descripcion(m: dict[str, Any]) -> str:
    desc = (m.get("descripcion") or "").strip()
    if len(desc) > LARGO_DESC:
        desc = desc[:LARGO_DESC] + "…"
    html = f'<span>{inf.esc(desc)}</span>'
    tercero = (m.get("tercero") or "").strip()
    if tercero and tercero != "(sin identificar)" and tercero not in desc and desc != tercero:
        html += f'<div style="font-size:10.5px;color:#5b6b80">{inf.esc(tercero)}</div>'
    return html


def _celda_resultado(texto: str, signo: int) -> str:
    color = inf.NEGATIVO if signo > 0 else (inf.POSITIVO if signo < 0 else "#666")
    return f'<span style="color:{color};font-weight:bold;white-space:nowrap">{inf.esc(texto)}</span>'


# ---------- cálculo ----------

def calcular(por_anio: dict[int, list[Linea]] | list[Linea], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Libro de IVA del ejercicio: cuotas, bases derivadas, resumen por trimestre y detalle."""
    ctx = dict(ctx or {})
    avisos: list[str] = []

    por_anio = por_anio or {}
    if isinstance(por_anio, (list, tuple)):      # tolera que le pasen las líneas directamente
        lineas = list(por_anio)
        year = int(ctx.get("year") or 0)
    else:
        year = int(ctx.get("year") or 0) or (max(por_anio) if por_anio else 0)
        lineas = list(por_anio.get(year) or [])
        if not lineas and por_anio:
            year = max(por_anio)
            lineas = list(por_anio[year] or [])
            avisos.append(f"No llegaron apuntes del ejercicio pedido; se calcula con el {year} "
                          "disponible.")
    if not lineas:
        avisos.append(f"No hay apuntes cargados del ejercicio {year}: todas las cifras salen a cero.")

    trimestre, aviso_trimestre = normalizar_trimestre(ctx.get("trimestre"))
    if aviso_trimestre:
        avisos.append(aviso_trimestre)

    movimientos = movimientos_de(lineas)
    total = _bloque(movimientos)

    # ---------- reparto por trimestre y por mes ----------
    por_tr: dict[int, list[dict[str, Any]]] = {q: [] for q in (1, 2, 3, 4)}
    por_mes: dict[int, list[dict[str, Any]]] = {m: [] for m in range(1, 13)}
    sin_fecha: list[dict[str, Any]] = []
    for m in movimientos:
        if m["trimestre"] in por_tr:
            por_tr[m["trimestre"]].append(m)
            por_mes[m["mes"]].append(m)
        else:
            sin_fecha.append(m)

    bloques: list[dict[str, Any]] = []
    for q in (1, 2, 3, 4):
        bloques.append({"trimestre": q, "periodo": TRIMESTRE_PERIODO[q - 1],
                        **_bloque(por_tr[q])})

    meses: list[dict[str, Any]] = []
    for m in range(1, 13):
        meses.append({"mes": m, "nombre": MESES[m - 1], "nombre_largo": MESES_LARGOS[m - 1],
                      **_bloque(por_mes[m])})

    # ---------- avisos de método y de datos ----------
    avisos.append(
        "Base imponible derivada: los apuntes del ERP no traen la base, así que se calcula con la "
        "contrapartida del mismo asiento —cuentas de ingreso 7xx para el IVA repercutido (477) y "
        "cuentas de gasto 6xx para el soportado (472)—. El tipo (%) es cuota ÷ base: no se aplican "
        "tipos impositivos teóricos. Si un asiento no permite derivar la base, el apunte se queda "
        "sin base y sin tipo.")
    avisos.append(
        "Es el IVA contabilizado en las cuentas 472/477, no la declaración presentada (modelo 303): "
        "pueden existir diferencias por imputación temporal, por operaciones no contabilizadas y por "
        "deducciones que no se registran en esas cuentas.")
    if total["nSinBase"]:
        avisos.append(
            f"{total['nSinBase']} de {total['nMovimientos']} movimientos no tienen base derivable "
            f"(cuotas de {fmt(total['cuotaSinBase'])} en total): su asiento no tiene cuentas 6xx/7xx "
            "—suelen ser liquidaciones o regularizaciones de IVA, adquisiciones intracomunitarias o "
            "apuntes de nómina—. La base y el tipo aparecen vacíos en el detalle; no se han estimado.")
    if sin_fecha:
        avisos.append(
            f"{len(sin_fecha)} movimientos de IVA no traen fecha: entran en el total del ejercicio "
            "pero quedan fuera del reparto por mes y por trimestre.")
    for q in (1, 2, 3, 4):
        if not bloques[q - 1]["nMovimientos"]:
            avisos.append(f"El {q}T no tiene movimientos de IVA en los apuntes: sus cifras salen a cero.")
    if total["diferencia"] < 0:
        avisos.append(
            "El IVA soportado supera al repercutido en el ejercicio, así que la diferencia sale a "
            "compensar o a devolver (no a ingresar). Conviene comprobar si hay operaciones "
            "intracomunitarias, inversión del sujeto pasivo o si la sociedad está en devolución "
            "mensual.")
    cuadre_por_trimestre = sum(b["diferencia"] for b in bloques)
    if abs(_r(cuadre_por_trimestre - total["diferencia"])) > 0.05:
        avisos.append("La suma de las diferencias trimestrales no coincide con la del ejercicio: hay "
                      "movimientos de IVA fuera del desglose (sin fecha).")

    # asientos con las dos cuotas iguales (IVA devengado y deducible en la misma operación)
    r_por_asiento = {(m["fecha"], m["serie"], m["documento"]): m["cuota"]
                     for m in movimientos if m["tipo"] == "R"}
    pares: list[dict[str, Any]] = []
    for s in movimientos:
        if s["tipo"] != "S":
            continue
        clave = (s["fecha"], s["serie"], s["documento"])
        if clave in r_por_asiento and abs(r_por_asiento[clave] - s["cuota"]) < 0.05:
            pares.append(s)
    if pares:
        avisos.append(
            f"{len(pares)} asientos llevan la misma cuota en 472 y en 477 (IVA devengado y deducible "
            f"en la misma operación: adquisiciones intracomunitarias o inversión del sujeto pasivo; "
            f"{fmt(sum(p['cuota'] for p in pares))} en cada lado). Suman en repercutido y en "
            "soportado, y se anulan en la diferencia.")
    liquidaciones = [m for m in movimientos if "liquidac" in (m["descripcion"] or "").lower()]
    if liquidaciones:
        avisos.append(
            f"{len(liquidaciones)} movimientos son apuntes de liquidación o regularización de IVA "
            f"({fmt(sum(m['cuota'] for m in liquidaciones))}): no son operaciones con terceros y su "
            "base no se puede derivar; están incluidos en las cuotas porque están en el libro.")

    # ---------- detalle por trimestre ----------
    limite = MAX_MOV_DETALLE if trimestre is None else MAX_MOV_DETALLE_UNO
    truncados: dict[tuple[int, str], tuple[int, int]] = {}
    detalle: list[dict[str, Any]] = []
    for b in bloques:
        q = b["trimestre"]
        if trimestre is not None and q != trimestre:
            continue
        movs_q = por_tr[q]
        filas_r, n_r = _filas_trimestre(movs_q, "R", limite, truncados, q)
        filas_s, n_s = _filas_trimestre(movs_q, "S", limite, truncados, q)
        detalle.append({**b, "filasRepercutido": filas_r, "filasSoportado": filas_s,
                        "listadosRepercutido": len(filas_r), "listadosSoportado": len(filas_s),
                        "totalRepercutido": n_r, "totalSoportado": n_s, "limite": limite})
    if truncados:
        trozos = ", ".join(f'{q}T {"repercutido" if t == "R" else "soportado"} '
                           f'{listados} de {total_}' for (q, t), (total_, listados) in
                           sorted(truncados.items()))
        avisos.append(
            f"El detalle del libro se limita a {limite} movimientos por trimestre y libro "
            "—empezando por los de mayor cuota— para que el informe se pueda abrir: "
            f"{trozos}. Los subtotales, las tablas de mes y trimestre y el resumen del ejercicio "
            "suman todos los movimientos, no sólo los listados.")

    datos: dict[str, Any] = {
        "year": year,
        "trimestre": trimestre,
        "periodo": TRIMESTRE_PERIODO[trimestre - 1] if trimestre else "los cuatro trimestres",
        "trimestres_mostrados": [d["trimestre"] for d in detalle],
        # totales del ejercicio
        **{k: total[k] for k in ("repercutido", "soportado", "diferencia", "a_ingresar",
                                 "a_compensar", "resultado", "baseRepercutida", "baseSoportada",
                                 "nMovimientos", "nRepercutido", "nSoportado", "nSinBase",
                                 "nSinBaseRepercutido", "nSinBaseSoportado", "cuotaSinBase",
                                 "cuotaConBaseRepercutido", "cuotaConBaseSoportado")},
        "ivaRepercutido": total["repercutido"],
        "ivaSoportado": total["soportado"],
        "ivaDiferencia": total["diferencia"],
        "ivaAIngresar": total["a_ingresar"],
        "ivaACompensar": total["a_compensar"],
        "n_movimientos": total["nMovimientos"],
        # repartos
        "porTrimestre": bloques,
        "porMes": meses,
        "detalle": detalle,
        "nLineas": len(lineas),
        "nAsientos": len(asientos_de(lineas)),
        "nSinFecha": len(sin_fecha),
        "avisos": avisos,
    }
    datos["data"] = {k: v for k, v in datos.items() if isinstance(v, (int, float, str, bool))}
    return datos


def asientos_de(lineas: Iterable[Linea]) -> set[tuple[int, str, str]]:
    return {_clave_asiento(l) for l in lineas}


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    """KPIs del panel: cuotas del ejercicio, diferencia y número de movimientos."""
    return {
        "ivaRepercutido": datos.get("ivaRepercutido", 0.0),
        "ivaSoportado": datos.get("ivaSoportado", 0.0),
        "ivaDiferencia": datos.get("ivaDiferencia", 0.0),
        "n_movimientos": datos.get("n_movimientos", datos.get("nMovimientos", 0)),
    }


# ---------- informe ----------

def _tabla_resumen(datos: dict[str, Any]) -> str:
    filas = []
    for b in datos["porTrimestre"]:
        filas.append([f'{b["trimestre"]}T',
                      f'<span>{inf.esc(b["periodo"])}<div style="font-size:10.5px;color:#8a95a6">'
                      f'{b["nMovimientos"]} movs.</div></span>',
                      inf.importe(b["repercutido"]), inf.importe(b["soportado"]),
                      inf.importe(b["diferencia"], con_signo=True),
                      _celda_resultado(b["resultado"], 1 if b["diferencia"] > 0 else
                                       (-1 if b["diferencia"] < 0 else 0))])
    filas.append(["TOTAL", f'<span>Ejercicio {inf.esc(datos["year"])}'
                           f'<div style="font-size:10.5px;color:#8a95a6">'
                           f'{datos["nMovimientos"]} movs.</div></span>',
                  inf.importe(datos["repercutido"]), inf.importe(datos["soportado"]),
                  inf.importe(datos["diferencia"], con_signo=True),
                  _celda_resultado(datos["resultado"], 1 if datos["diferencia"] > 0 else
                                   (-1 if datos["diferencia"] < 0 else 0))])
    return inf.tabla(["Trim.", "Periodo", "IVA repercutido (477)", "IVA soportado (472)",
                      "Diferencia", "Resultado"], filas,
                     anchos=["7%", "23%", "19%", "19%", "16%", "16%"])


def _tabla_meses(datos: dict[str, Any]) -> str:
    filas = []
    for m in datos["porMes"]:
        filas.append([m["nombre"], inf.importe(m["repercutido"]), inf.importe(m["baseRepercutida"]),
                      inf.importe(m["soportado"]), inf.importe(m["baseSoportada"]),
                      inf.importe(m["diferencia"], con_signo=True), str(m["nMovimientos"])])
    filas.append(["TOTAL", inf.importe(datos["repercutido"]), inf.importe(datos["baseRepercutida"]),
                  inf.importe(datos["soportado"]), inf.importe(datos["baseSoportada"]),
                  inf.importe(datos["diferencia"], con_signo=True), str(datos["nMovimientos"])])
    return inf.tabla(["Mes", "Cuota repercutida", "Base repercutida", "Cuota soportada",
                      "Base soportada", "Diferencia", "Movs."], filas,
                     anchos=["10%", "17%", "18%", "17%", "18%", "13%", "7%"])


def _bloque_trimestre(d: dict[str, Any], year: int) -> str:
    q = d["trimestre"]
    filas_r = d["filasRepercutido"]
    filas_s = d["filasSoportado"]
    tabla_r = inf.tabla(
        ["Fecha", "Documento", "Descripción", "Base", "Cuota IVA", "Tipo"],
        filas_r or [["—", "—", "Sin movimientos de IVA repercutido en el trimestre", "—", "—", "—"]],
        totales=[f"Subtotal {q}T", f'{d["nRepercutido"]} movs.',
                 _celda_base(d["baseRepercutida"]), _celda_base(d["repercutido"]),
                 _celda_tipo(d["repercutido"] / d["baseRepercutida"] * 100
                             if d["baseRepercutida"] else None)],
        anchos=["11%", "11%", "39%", "14%", "14%", "11%"])
    tabla_s = inf.tabla(
        ["Fecha", "Documento", "Descripción", "Base", "Cuota IVA", "Tipo"],
        filas_s or [["—", "—", "Sin movimientos de IVA soportado en el trimestre", "—", "—", "—"]],
        totales=[f"Subtotal {q}T", f'{d["nSoportado"]} movs.',
                 _celda_base(d["baseSoportada"]), _celda_base(d["soportado"]),
                 _celda_tipo(d["soportado"] / d["baseSoportada"] * 100
                             if d["baseSoportada"] else None)],
        anchos=["11%", "11%", "39%", "14%", "14%", "11%"])
    etiqueta_libro = ('<div style="font-size:12px;font-weight:bold;color:#1a4b8c;margin:10px 0 2px">'
                      'IVA repercutido (477)</div>')
    etiqueta_libro2 = ('<div style="font-size:12px;font-weight:bold;color:#1a4b8c;margin:12px 0 2px">'
                       'IVA soportado (472)</div>')
    recortes = []
    if d["listadosRepercutido"] < d["nRepercutido"]:
        recortes.append(f'{d["listadosRepercutido"]} de {d["nRepercutido"]} de IVA repercutido')
    if d["listadosSoportado"] < d["nSoportado"]:
        recortes.append(f'{d["listadosSoportado"]} de {d["nSoportado"]} de IVA soportado')
    nota_recorte = (f' · se listan {", ".join(recortes)} (los de mayor cuota)' if recortes else '')
    resumen = (f'<div style="font-size:12px;color:#5b6b80;margin:2px 0 4px">'
               f'{inf.esc(d["periodo"])} · {d["nMovimientos"]} movimientos · '
               f'{d["nSinBase"]} sin base derivable{inf.esc(nota_recorte)}</div>')
    linea_final = (
        f'<div style="font-size:12px;margin:6px 0 0;padding:7px 10px;background:#e8f0fb;'
        f'border-left:4px solid #1a4b8c">Diferencia del {q}T ({inf.esc(d["periodo"])}): '
        + inf.importe(d["diferencia"], con_signo=True)
        + ' · <b>' + inf.esc(d["resultado"]) + '</b>'
        + (f' — a compensar o devolver {inf.importe(d["a_compensar"])}' if d["diferencia"] < 0 else
           f' — a ingresar {inf.importe(d["a_ingresar"])}' if d["diferencia"] > 0 else "")
        + '</div>')
    return (inf.seccion(f'{q}T de {year} · {inf.esc(d["periodo"])}', resumen + etiqueta_libro
                        + tabla_r + etiqueta_libro2 + tabla_s + linea_final))


def _tabla_metodo(datos: dict[str, Any]) -> str:
    con_base = datos["nMovimientos"] - datos["nSinBase"]
    pct = f'{con_base / datos["nMovimientos"] * 100:.1f} %'.replace(".", ",") if datos["nMovimientos"] else "—"
    base_total = datos["baseRepercutida"] + datos["baseSoportada"]
    cuota_con_base = datos["cuotaConBaseRepercutido"] + datos["cuotaConBaseSoportado"]
    tipo_medio = (cuota_con_base / base_total * 100) if base_total else None
    return inf.tabla(
        ["Concepto", "Cómo se obtiene", "Importe"],
        [["IVA repercutido (477)", "Σ(Haber−Debe) de las cuentas 477 y sus subcuentas del ejercicio",
          inf.importe(datos["repercutido"])],
         ["IVA soportado (472)", "Σ(Debe−Haber) de las cuentas 472 y sus subcuentas del ejercicio",
          inf.importe(datos["soportado"])],
         ["Base repercutida (derivada)",
          "Σ(Haber−Debe) de las cuentas de ingreso (7xx) del mismo asiento de cada apunte de IVA "
          "repercutido", inf.importe(datos["baseRepercutida"])],
         ["Base soportada (derivada)",
          "Σ(Debe−Haber) de las cuentas de gasto (6xx) del mismo asiento de cada apunte de IVA "
          "soportado", inf.importe(datos["baseSoportada"])],
         ["Movimientos con base derivada", f'{con_base} de {datos["nMovimientos"]} ({pct})', ""],
         ["Movimientos sin base derivable",
          "Apuntes de IVA cuyo asiento no tiene cuentas 6xx/7xx: la base y el tipo se dejan vacíos, "
          "no se estiman", str(datos["nSinBase"])],
         ["Tipos aplicados", "Cuota ÷ base de cada apunte. No se usan tipos impositivos teóricos",
          ""],
         ["Tipo medio de los movimientos con base",
          "Σ cuota ÷ Σ base, sólo de los movimientos cuya base se ha podido derivar (los que se "
          "quedan sin base no entran, por eso el tipo medio no se calcula sobre el total de cuotas)",
          _celda_tipo(tipo_medio)]],
        anchos=["24%", "56%", "20%"])


def informe_html(datos: dict[str, Any], ctx: dict[str, Any] | None = None, *,
                 empresa: str | None = None, year: int | None = None) -> str:
    """HTML del libro de IVA (empieza por `<div`, Arial 13 px, CSS inline, importes es-ES)."""
    ctx = dict(ctx or {})
    if empresa:
        ctx.setdefault("empresa", empresa)
    year = int(year or datos.get("year") or ctx.get("year") or 0)
    nombre_empresa = ctx.get("empresa") or ""
    trimestre = datos.get("trimestre")
    diferencia = float(datos.get("ivaDiferencia") or 0.0)
    signo = 1 if diferencia > 0 else (-1 if diferencia < 0 else 0)

    kpis_items = [
        ("Repercutido (477) del ejercicio", inf.importe(datos.get("repercutido", 0.0))),
        ("Soportado (472) del ejercicio", inf.importe(datos.get("soportado", 0.0))),
        ("Base repercutida (derivada)", inf.importe(datos.get("baseRepercutida", 0.0))),
        ("Base soportada (derivada)", inf.importe(datos.get("baseSoportada", 0.0))),
        ("A ingresar en el ejercicio" if signo > 0 else
         "A compensar o devolver en el ejercicio" if signo < 0 else "Diferencia del ejercicio",
         inf.importe(abs(diferencia), con_signo=False)),
        ("Movimientos de IVA", str(datos.get("nMovimientos", 0))),
    ]
    if trimestre:
        # cuando el informe se limita a un trimestre, su diferencia va también en las tarjetas
        bloque_q = next((b for b in datos.get("porTrimestre") or [] if b["trimestre"] == trimestre), None)
        if bloque_q:
            kpis_items.append((f"Diferencia del {trimestre}T",
                               inf.importe(bloque_q["diferencia"], con_signo=True)))
    kpis = inf.kpis(kpis_items, columnas=4)

    titular = (f'IVA del ejercicio {year}: '
               + ("a ingresar " if signo > 0 else "a compensar o devolver " if signo < 0 else "cuadrado ")
               + fmt(abs(diferencia))
               + f' (repercutido {fmt(datos.get("repercutido", 0.0))} − soportado '
                 f'{fmt(datos.get("soportado", 0.0))}).')

    avisos_metodo = datos.get("avisos") or []
    avisos_html = "".join(
        inf.aviso(a, tipo="info" if ("Base imponible derivada" in a or "contabilizado" in a) else "alerta")
        for a in avisos_metodo)

    categorias_mes = [m["nombre"] for m in datos["porMes"]]
    grafico_mes = inf.barras_svg(
        categorias_mes,
        [{"nombre": "Repercutido (477)", "color": inf.AZUL,
          "valores": [m["repercutido"] for m in datos["porMes"]]},
         {"nombre": "Soportado (472)", "color": "#c98a2b",
          "valores": [m["soportado"] for m in datos["porMes"]]}],
        alto=200, formato=lambda v: fmt(v), titulo="IVA por mes")
    categorias_trim = [f'{b["trimestre"]}T' for b in datos["porTrimestre"]]
    grafico_trim = inf.barras_svg(
        categorias_trim,
        [{"nombre": "Diferencia (repercutido − soportado)", "color": inf.AZUL,
          "valores": [b["diferencia"] for b in datos["porTrimestre"]]}],
        alto=180, formato=lambda v: fmt(v), titulo="Diferencia de IVA por trimestre")

    subtitulo = (f'Ejercicio {year} · detalle del {trimestre}T ({datos.get("periodo")})' if trimestre else
                 f'Ejercicio {year} · los cuatro trimestres')
    if trimestre:
        nota_filtro = (f'El informe está limitado al {trimestre}T por parámetro: el resumen y la '
                       'evolución mensual siguen mostrando el ejercicio completo.')
    else:
        nota_filtro = ""

    detalle = datos.get("detalle") or []
    cuerpo = (
        inf.aviso(titular, tipo="info" if signo <= 0 else "alerta",
                  titulo="Diferencia de IVA del ejercicio")
        + kpis
        + (f'<div style="font-size:12px;color:#5b6b80;padding:2px 4px 4px">{inf.esc(nota_filtro)}</div>'
           if nota_filtro else "")
        + avisos_html
        + inf.seccion("Resumen del ejercicio por trimestre", _tabla_resumen(datos),
                      nota="La diferencia es cuota repercutida menos cuota soportada del periodo. "
                           "Positiva, sale a ingresar; negativa, a compensar en periodos siguientes "
                           "(o a devolver, si la sociedad está en devolución mensual).")
        + inf.seccion("IVA por mes", _tabla_meses(datos) + f'<div style="margin-top:10px">{grafico_mes}</div>',
                      nota="Cuotas contabilizadas en cada mes del ejercicio. La base de cada mes es "
                           "la suma de las bases derivadas de la contrapartida: los movimientos sin "
                           "base derivable suman en la cuota pero no en la base.")
        + inf.seccion("Diferencia por trimestre", grafico_trim)
        + "".join(_bloque_trimestre(d, year) for d in detalle)
        + inf.seccion("Cómo se han calculado las cifras", _tabla_metodo(datos),
                      nota="Método declarado a propósito: el ERP no da la base imponible en los "
                           "apuntes, así que se deriva de la contrapartida del mismo asiento. Es una "
                           "estimación contable, no un dato de la factura.")
    )
    return inf.envoltura(
        titulo=TITULO, subtitulo=subtitulo, empresa=nombre_empresa, ejercicio=year, cuerpo=cuerpo,
        meta={"Trimestre": f"{trimestre}T" if trimestre else "1T-4T",
              "Movimientos": str(datos.get("nMovimientos", 0)),
              "Bases": "derivadas de la contrapartida (declarado)",
              "Datos": "ERP apiCON (IVA contabilizado)"},
    )


__all__ = ["NOMBRE", "TITULO", "INTERNO", "DESPLAZAMIENTOS", "PARAMETROS", "calcular",
           "informe_html", "metricas_dashboard", "movimientos_de", "normalizar_trimestre"]
