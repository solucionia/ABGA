"""Módulo `libro_retenciones` — libro de retenciones del ejercicio, por trimestres.

Qué responde: *cuánto se retiene y cuándo*, sin llamar al asesor. Retenciones **practicadas**
(IRPF de la nómina y de las facturas de profesionales, cuenta 4751) y los demás movimientos de
las cuentas de Hacienda que se retienen o se ingresan (4752, 4750, 4759 y la 473, de activo),
agrupados por mes y por trimestre, con el detalle de cada apunte y el modelo con el que se
declaran.

Contrato (ver `backend/CONTRATO-MODULOS.md`): el módulo **no** llama al ERP ni a la caché;
recibe `por_anio = {ejercicio: [Linea]}` y `ctx`, y devuelve **números**, no texto formateado.

Reglas de negocio —decisión y porqué, para que nadie las «arregle» sin querer:

1. **Cuota = saldo de la cuenta de retención en el asiento.** En las cuentas acreedoras (4751,
   4752, 4750, 4759) la retención nace en el **haber**, así que la cuota del movimiento es
   `Σ(Haber − Debe)` de esas líneas dentro del asiento; en la 473 (activo) la retención
   soportada nace en el **debe** y se toma `Σ(Debe − Haber)`. Se trabaja **por asiento**, no por
   línea suelta, para que una rectificación dentro del mismo asiento se nete sola.
2. **Devengo frente a pago.** Un movimiento entra en el libro como retención sólo si tiene
   contrapartida de renta —**64x** para trabajo, **60x/62x** para actividades profesionales,
   **43x/7xx** para las retenciones soportadas de la 473— y, cuando **disminuye** la cuenta, además
   no puede traer ninguna cuenta de tesorería (57x) ni otra cuenta de Hacienda (470, 476…): eso es un
   pago o una liquidación del modelo, no una retención, y se informa aparte **sin netear**. Sin esa
   segunda condición, la domiciliación del modelo del trimestre anterior restaría dentro del
   trimestre y el libro diría una barbaridad (los apuntes reales mezclan devengo y pago en la misma
   cuenta, y hay asientos «de ajuste» que juntan el pago del modelo con gastos del mismo mes: con
   6091/2022, −37.093,77 € de profesionales). Una **rectificación** sí entra: una factura de abono
   que revierte la renta y la retención es un devengo en negativo, y dejarla fuera descuadra el libro
   contra el saldo de la cuenta (con 6091/2024, 6,40 € de más).
3. **La base no viene en los apuntes: se deriva y se declara.** El ERP no guarda la base de la
   retención, sólo la cuota. Se toma la contrapartida del mismo asiento:
   - trabajo → **640/641** (sueldos y salarios); si el asiento no trae ninguna, el resto de 64x;
   - profesionales/actividades → **60x y 62x** (las 60x entran porque hay facturas de
     profesionales contabilizadas en la 607; el 15 % derivado lo confirma);
   cuando no hay contrapartida que sirva, la base se deja **vacía** y el caso se cuenta: no se
   inventa. El tipo (%) es `cuota / base`, y sólo se enseña si hay base y cuota positiva.
4. **Apertura y cierre fuera.** Los asientos fechados el 1 de enero (apertura o ajuste de
   apertura) y los de regularización/cierre del ejercicio se excluyen: sus saldos son del año
   anterior o del cierre, no actividad del ejercicio. Se declara cuántos son.
5. **Bloques por cuenta y por tipo.** Trabajo y profesionales son siempre **4751** (es la cuenta
   de IRPF practicado); lo que cambia el bloque es la contrapartida. Las demás cuentas de
   Hacienda (4752 IS, 4750 IVA, 4759 otros, 473 activo) van a «otras» con su importe a la vista,
   sin mezclarlas con el IRPF: sumar la liquidación del IVA a las retenciones daría un total que
   no significa nada.
6. **Nada de importes de modelos.** Cada trimestre se relaciona con el modelo que le
   corresponde (111 de trabajo, 115/123 de actividades profesionales) pero el importe que se
   enseña es **el contabilizado**, nunca el declarado.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Sequence

from .. import informes as inf
from ..ledger import (MESES, Linea, comprobar_cuadre, detectar_cierre, fecha_a_int, fmt,
                      fmt_pct, mes_de, nombre_tercero, trimestre_de)

NOMBRE = "libro_retenciones"
TITULO = "Libro de retenciones"
INTERNO = False
DESPLAZAMIENTOS = [0]
# `trimestre`: None = los cuatro trimestres del ejercicio; 1-4 (o "1"-"4", "Q1"-"Q4", "1T"-"4T") = sólo ese.
PARAMETROS: dict[str, Any] = {"trimestre": None}

# ---------- cuentas ----------

P_IRPF = ("4751",)                 # Hacienda acreedora por retenciones practicadas (IRPF)
P_HACIENDA_ACREEDORA = ("475",)    # 4750 IVA · 4751 IRPF · 4752 IS · 4759 otros
P_HACIENDA_ACTIVO = ("473",)       # Hacienda, retenciones y pagos a cuenta (activo)
P_RETENCIONES = P_HACIENDA_ACREEDORA + P_HACIENDA_ACTIVO
# Cuentas que marcan un PAGO o liquidación del modelo y no una rectificación de la renta: tesorería
# y las demás cuentas de Hacienda (470 deudora, 476, fianzas). Ninguna empieza por 475/473, así que
# no hay solape con las cuentas de retención.
P_PAGO = ("57", "470", "476", "554", "555")

# Qué es cada cuenta y qué modelo la recibe: se pinta tal cual en el informe.
CUENTAS_INFO: list[tuple[str, str, str]] = [
    ("4751", "Hacienda acreedora por retenciones practicadas (IRPF)", "modelos 111 y 115"),
    ("4752", "Hacienda acreedora por Impuesto sobre Sociedades", "modelos 200 y 222"),
    ("4750", "Hacienda acreedora por IVA", "modelo 303"),
    ("4759", "Hacienda acreedora por otros conceptos", "concepto a identificar"),
    ("473", "Hacienda, retenciones y pagos a cuenta (activo)",
     "retenciones soportadas y pagos a cuenta (202/222)"),
]

FAMILIA_TRABAJO = ("64",)
FAMILIA_PROFESIONAL = ("60", "62")
FAMILIA_SOPORTADA = ("43", "7")

BLOQUES = {
    "trabajo": "Retenciones de trabajo (nóminas) · cuenta 4751 con contrapartida 64x · modelo 111",
    "profesionales": ("Retenciones de actividades profesionales · cuenta 4751 con contrapartida "
                      "60x/62x · modelo 115"),
    "otras": ("Otras retenciones y cuentas de Hacienda · 4752, 4750, 4759 y 473 · según concepto"),
}

PERIODOS = ["enero–marzo", "abril–junio", "julio–septiembre", "octubre–diciembre"]
MODELOS_TRIMESTRE = {
    "trabajo": "111 (retenciones sobre rendimientos del trabajo)",
    "profesionales": "115 (retenciones sobre rendimientos de actividades profesionales) · "
                     "123 (capital mobiliario) si el concepto lo es",
}
MODELO_OTRAS = "según concepto (200/222, 303 o el que corresponda)"

RECORDATORIO = ("Este libro son las retenciones **contabilizadas** en los apuntes del ejercicio, "
                "no las declaraciones presentadas ni las cuotas ingresadas: el importe de un "
                "trimestre puede no coincidir con el modelo 111/115 finalmente presentado (por "
                "ejemplo, el 4T suele declararse en enero del año siguiente).")

METODO = {
    "cuota": ("Saldo de la cuenta de retención en el asiento: Σ(Haber − Debe) en las cuentas "
              "acreedoras (4751, 4752, 4750, 4759) y Σ(Debe − Haber) en la 473, que es de activo. "
              "Los movimientos que disminuyen la cuenta van aparte (pagos, liquidaciones y "
              "rectificaciones) y no se netean contra los devengos."),
    "base": ("El ERP no da la base en los apuntes: se deriva de la contrapartida del mismo "
             "asiento. Trabajo → 640/641 (si no hay, el resto de 64x). Actividades profesionales "
             "→ 60x y 62x. Retenciones soportadas (473) → ingresos 7xx. Sin contrapartida válida "
             "la base queda vacía y el caso se cuenta."),
    "tipo": "Tipo (%) = cuota ÷ base derivada; sólo se muestra con base y cuota positivas.",
    "devengo": ("Entra en el libro el movimiento con contrapartida de renta (64x, 60x/62x o 43x/7xx). "
                "Si la disminuye y trae cuenta de tesorería u otra cuenta de Hacienda, es un pago o "
                "liquidación: se informa aparte y no entra en el total. Una factura de abono que "
                "revierte la renta sí entra, en negativo, porque es un devengo y no un pago."),
    "exclusiones": ("Fuera del libro los asientos del 1 de enero (apertura o ajuste de apertura) "
                    "y los de regularización y cierre del ejercicio."),
    "modelos": ("Cada trimestre se relaciona con el modelo que le corresponde, pero el importe "
                "que se enseña es el contabilizado, no el declarado."),
    "total": ("El total de retenciones es trabajo + profesionales, todo de la cuenta 4751 (es lo "
              "que alimenta los modelos 111 y 115). Las cuentas 4752, 4750, 4759 y 473 se informan "
              "en su propio bloque y no se suman al total, porque no son IRPF."),
}

LIMITE_DETALLE = 250  # movimientos que se pintan por trimestre (el JSON lleva todos)
LIMITE_OTROS = 120    # pagos y liquidaciones que se pintan en el informe (el JSON lleva todos)


# ---------- utilidades ----------

def _r(x: Any) -> float:
    try:
        return round(float(x or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _es_retencion(cuenta: str) -> bool:
    return cuenta.startswith(P_RETENCIONES)


def _grupo_cuenta(cuenta: str) -> str:
    """`activo` para la 473 (saldo deudor = retención soportada/pago a cuenta), `acreedora` para 475x."""
    return "activo" if cuenta.startswith(P_HACIENDA_ACTIVO) else "acreedora"


def _raiz(cuenta: str) -> str:
    """Cuenta raíz del libro: 4751, 4752, 4750, 4759 o 473."""
    return "473" if cuenta.startswith(P_HACIENDA_ACTIVO) else cuenta[:4]


def _fecha_txt(fecha: int) -> str:
    f = fecha_a_int(fecha)
    if not f:
        return "—"
    return f"{f % 100:02d}/{(f // 100) % 100:02d}/{f // 10000:04d}"


def _mes_txt(mes: int) -> str:
    return MESES[mes - 1] if 1 <= mes <= 12 else "—"


def normalizar_trimestre(valor: Any) -> tuple[int | None, str]:
    """None o valor inválido → todos los trimestres; 1-4 (o «1», «Q1», «1T») → ese trimestre."""
    if valor is None:
        return None, ""
    if isinstance(valor, bool):
        return None, f"El trimestre «{valor}» no es válido (se espera 1-4 o «Q1»); se usa el ejercicio completo."
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
                  "se muestra el ejercicio completo.")


def _es_apertura(ls: Sequence[Linea]) -> bool:
    """Asientos del 1 de enero: apertura del ejercicio o ajustes de apertura."""
    return bool(ls) and fecha_a_int(ls[0].fecha) % 10000 == 101


# ---------- cálculo ----------

def _clasificar(ls: Sequence[Linea], cuentas: Sequence[Linea]) -> dict[str, Any]:
    """Clasifica un grupo de líneas de Hacienda de un mismo asiento.

    Devuelve `tipo` (trabajo | profesionales | otras), `categoria` (devengo | movimiento), la
    `base` derivada (o None) y los motivos, todo a partir de las contrapartidas del asiento.
    Es retención (categoría `devengo`) sólo lo que **aumenta** la cuenta de retención y tiene
    contrapartida de renta; lo demás es movimiento de la cuenta (pago, liquidación o rectificación).
    """
    b64 = sum(l.debe - l.haber for l in ls if l.cuenta.startswith(FAMILIA_TRABAJO))
    b640 = sum(l.debe - l.haber for l in ls if l.cuenta.startswith(("640", "641")))
    b62 = sum(l.debe - l.haber for l in ls if l.cuenta.startswith(FAMILIA_PROFESIONAL))
    b7 = sum(l.haber - l.debe for l in ls if l.cuenta.startswith(FAMILIA_SOPORTADA[1]))
    hay43 = any(l.cuenta.startswith(FAMILIA_SOPORTADA[0]) for l in ls)
    activo = _grupo_cuenta(cuentas[0].cuenta) == "activo"

    saldo = sum(l.haber - l.debe for l in cuentas)
    cuota = -saldo if activo else saldo

    if cuota <= 0:
        # Una retención nace aumentando la cuenta (haber en las acreedoras, debe en la 473). Lo que
        # la disminuye son dos cosas muy distintas, y confundirlas rompe el libro:
        #   · un PAGO o liquidación (contrapartida de tesorería 57x o de otra cuenta de Hacienda): no
        #     es retención. Va aparte y NO se netea, porque en los apuntes reales el asiento «de
        #     ajuste» junta el pago del modelo con los gastos del mismo mes y el trimestre saldría en
        #     negativo (con 6091/2022, −37.093,77 € de profesionales).
        #   · una RECTIFICACIÓN de la renta (factura de abono que revierte la retención practicada:
        #     trae contrapartida de gasto/ingreso y ninguna cuenta de tesorería): sí es retención, en
        #     negativo. Dejarla fuera descuadraba 6091/2024, con el total 6,40 € por encima del saldo
        #     real de la 4751 (la rectificativa FCR/2024/00026 de un profesional).
        hay_renta = bool(b64 or b62 or b7) or hay43
        hay_pago = any(l.cuenta.startswith(P_PAGO) for l in ls)
        if cuota < 0 and hay_renta and not hay_pago:
            if _raiz(cuentas[0].cuenta) in P_IRPF:
                familia = "trabajo" if (b64 and abs(b64) >= abs(b62)) else ("profesionales" if b62 else "otras")
                return {"tipo": familia, "categoria": "devengo", "cuota": _r(cuota), "base": None,
                        "motivo": "rectificación de la renta (factura de abono): minora la retención"}
            # 4750/4752/4759: aunque sea rectificación, no es IRPF y sigue fuera del total.
            return {"tipo": "otras", "categoria": "devengo", "cuota": _r(cuota), "base": None,
                    "motivo": f"rectificación en la cuenta {_raiz(cuentas[0].cuenta)}, que no es IRPF"}
        return {"tipo": "otras", "categoria": "movimiento", "cuota": _r(cuota), "base": None,
                "motivo": "disminuye la cuenta de retención (pago o liquidación del modelo)"}

    if activo:  # 473 de activo: la retención soportada nace en el debe, contra cliente o ingreso
        if b7 > 0 or hay43:
            return {"tipo": "otras", "categoria": "devengo", "cuota": _r(cuota),
                    "base": _r(b7) if b7 > 0 else None, "motivo": "473 con contrapartida de ingreso/cliente"}
        return {"tipo": "otras", "categoria": "movimiento", "cuota": _r(cuota), "base": None,
                "motivo": "473 sin contrapartida de renta (pago a cuenta o liquidación)"}

    candidatos: list[tuple[str, float, str]] = []
    if b64 > 0:
        candidatos.append(("trabajo", b640 if b640 > 0 else b64, "contrapartida 64x"))
    if b62 > 0:
        candidatos.append(("profesionales", b62, "contrapartida 60x/62x"))
    raiz = _raiz(cuentas[0].cuenta)
    if raiz not in P_IRPF:
        # 4752 (IS), 4750 (IVA) o 4759 (otros): no es IRPF, va a «otras» aunque la contrapartida
        # sea de nómina o de servicios, y no se le deriva base: la cuota no responde a esa renta.
        if candidatos:
            return {"tipo": "otras", "categoria": "devengo", "cuota": _r(cuota), "base": None,
                    "motivo": f"cuenta {raiz} con contrapartida de renta ({candidatos[0][2]})"}
        return {"tipo": "otras", "categoria": "movimiento", "cuota": _r(cuota), "base": None,
                "motivo": f"cuenta {raiz} sin contrapartida de renta (pago o liquidación)"}

    if not candidatos:
        return {"tipo": "otras", "categoria": "movimiento", "cuota": _r(cuota), "base": None,
                "motivo": "sin contrapartida de renta (pago o liquidación)"}

    candidatos.sort(key=lambda c: -abs(c[1]))
    tipo, base, motivo = candidatos[0]
    if len(candidatos) > 1:
        motivo += f" (asiento mixto: se atribuye al de mayor base, {fmt(base)})"
    return {"tipo": tipo, "categoria": "devengo", "cuota": _r(cuota), "base": _r(base), "motivo": motivo}


def calcular(por_anio: dict[int, list[Linea]] | list[Linea], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Libro de retenciones del ejercicio (y del trimestre pedido si se pide uno)."""
    ctx = dict(ctx or {})
    avisos: list[str] = []

    if isinstance(por_anio, (list, tuple)):  # tolera que le pasen las líneas directamente
        lineas = list(por_anio)
        year = int(ctx.get("year") or 0)
    else:
        year = int(ctx.get("year") or 0) or (max(por_anio) if por_anio else 0)
        lineas = list(por_anio.get(year) or [])
    if not lineas and not isinstance(por_anio, (list, tuple)) and por_anio:
        year = max(por_anio)
        lineas = list(por_anio[year] or [])
        avisos.append(f"No llegaron apuntes del ejercicio pedido; se calcula con el {year} disponible.")
    if not lineas:
        avisos.append(f"No hay apuntes cargados del ejercicio {year}: el libro sale vacío.")

    trimestre, aviso_t = normalizar_trimestre(ctx.get("trimestre"))
    if aviso_t:
        avisos.append(aviso_t)
    trimestres = [trimestre] if trimestre else [1, 2, 3, 4]

    # ---------- asientos: agrupar, quitar apertura y cierre ----------
    cierre = detectar_cierre(lineas)
    fuera_cierre = set(cierre["asientos_regularizacion"]) | set(cierre["asientos_cierre"])
    grupos: dict[tuple[str, str], list[Linea]] = defaultdict(list)
    for l in lineas:
        grupos[(l.serie, l.documento)].append(l)

    movimientos: list[dict[str, Any]] = []
    otros: list[dict[str, Any]] = []
    n_apertura = n_cierre = n_mixtos = 0

    for clave, ls in sorted(grupos.items(), key=lambda kv: (fecha_a_int(kv[1][0].fecha), kv[0])):
        if not any(_es_retencion(l.cuenta) and (l.debe or l.haber) for l in ls):
            continue
        if clave in fuera_cierre:
            n_cierre += 1
            continue
        if _es_apertura(ls):
            n_apertura += 1
            continue

        por_cuenta_asiento: dict[str, list[Linea]] = defaultdict(list)
        for l in ls:
            if _es_retencion(l.cuenta) and (l.debe or l.haber):
                por_cuenta_asiento[_raiz(l.cuenta)].append(l)

        for _, cuentas in sorted(por_cuenta_asiento.items()):
            info = _clasificar(ls, cuentas)
            if "asiento mixto" in info.get("motivo", ""):
                n_mixtos += 1
            fecha = fecha_a_int(cuentas[0].fecha) or fecha_a_int(ls[0].fecha)
            mes = mes_de(fecha)
            doc = "/".join(x for x in (cuentas[0].serie, cuentas[0].documento) if x)
            fila = {
                "fecha": fecha, "fecha_txt": _fecha_txt(fecha), "mes": mes, "mes_txt": _mes_txt(mes),
                "trimestre": trimestre_de(fecha), "documento": doc,
                "serie": cuentas[0].serie, "num_documento": cuentas[0].documento,
                "descripcion": cuentas[0].descripcion or ls[0].descripcion,
                "tercero": nombre_tercero(cuentas[0].tercero, cuentas[0].descripcion),
                "cuentas": sorted({c.cuenta for c in cuentas}),
                "cuenta": _raiz(cuentas[0].cuenta),
                "tipo": info["tipo"], "categoria": info["categoria"],
                "base": info["base"], "cuota": info["cuota"], "motivo": info["motivo"],
            }
            fila["tipo_pct"] = (_r(info["cuota"] / info["base"] * 100)
                                if info["base"] and info["base"] > 0 and info["cuota"] > 0 else None)
            (movimientos if info["categoria"] == "devengo" else otros).append(fila)

    # ---------- agregados ----------
    def _suma(filas: Iterable[dict[str, Any]], tipo: str) -> float:
        return _r(sum(f["cuota"] for f in filas if f["tipo"] == tipo))

    def _base(filas: Iterable[dict[str, Any]], tipo: str) -> float:
        return _r(sum(f["base"] or 0.0 for f in filas if f["tipo"] == tipo))

    trabajo = _suma(movimientos, "trabajo")
    profesionales = _suma(movimientos, "profesionales")
    otras = _suma(movimientos, "otras")
    total = _r(trabajo + profesionales)
    base_trabajo, base_prof = _base(movimientos, "trabajo"), _base(movimientos, "profesionales")

    por_q: list[dict[str, Any]] = []
    for q in (1, 2, 3, 4):
        filas_q = [f for f in movimientos if f["trimestre"] == q]
        t_q, p_q, o_q = _suma(filas_q, "trabajo"), _suma(filas_q, "profesionales"), _suma(filas_q, "otras")
        bt_q, bp_q = _base(filas_q, "trabajo"), _base(filas_q, "profesionales")
        por_q.append({
            "trimestre": q, "periodo": PERIODOS[q - 1],
            "trabajo": t_q, "profesionales": p_q, "otras": o_q, "total": _r(t_q + p_q),
            "baseTrabajo": bt_q, "baseProfesionales": bp_q,
            "tipoTrabajo": _r(t_q / bt_q * 100) if bt_q > 0 and t_q > 0 else None,
            "tipoProfesionales": _r(p_q / bp_q * 100) if bp_q > 0 and p_q > 0 else None,
            "nMovimientos": len(filas_q),
            "nAsientos": len({(f["documento"], f["fecha"]) for f in filas_q}),
            "modelos": {"trabajo": MODELOS_TRIMESTRE["trabajo"],
                        "profesionales": MODELOS_TRIMESTRE["profesionales"],
                        "otras": MODELO_OTRAS},
        })

    por_cuenta: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"cuota": 0.0, "base": 0.0, "n": 0})
    for f in movimientos:
        k = (f["cuenta"], f["tipo"])
        por_cuenta[k]["cuota"] += f["cuota"]
        por_cuenta[k]["base"] += f["base"] or 0.0
        por_cuenta[k]["n"] += 1
    cuentas_filas = [{"cuenta": c, "tipo": t, "cuota": _r(v["cuota"]), "base": _r(v["base"]), "n": v["n"]}
                     for (c, t), v in sorted(por_cuenta.items())]

    por_m: list[dict[str, Any]] = []
    for mes in range(1, 13):
        filas_m = [f for f in movimientos if f["mes"] == mes]
        t_m, p_m, o_m = _suma(filas_m, "trabajo"), _suma(filas_m, "profesionales"), _suma(filas_m, "otras")
        por_m.append({"mes": mes, "mes_txt": _mes_txt(mes),
                      "trabajo": t_m, "profesionales": p_m, "otras": o_m, "total": _r(t_m + p_m),
                      "nMovimientos": len(filas_m),
                      "trimestre": (mes - 1) // 3 + 1})

    movimientos.sort(key=lambda f: (f["trimestre"], f["fecha"], f["documento"]))
    otros.sort(key=lambda f: (f["trimestre"], f["fecha"], f["documento"]))

    n_sin_base = sum(1 for f in movimientos if not f["base"])
    movimientos_vista = [f for f in movimientos if f["trimestre"] in trimestres]

    # ---------- avisos ----------
    avisos.insert(0, RECORDATORIO.replace("**", ""))
    cuadre = comprobar_cuadre(lineas)
    if lineas and abs(cuadre["descuadre"]) > 1:
        avisos.append(f"El libro no cuadra: ΣDebe − ΣHaber = {fmt(cuadre['descuadre'])} "
                      f"({cuadre['n_lineas']} líneas). Revisar asientos de regularización.")
    avisos.append(f"Cuota: {METODO['cuota']}")
    avisos.append(f"Base (derivada, no viene en los apuntes): {METODO['base']}")
    avisos.append(f"Criterio de devengo: {METODO['devengo']}")
    if n_apertura or n_cierre:
        avisos.append(f"Quedan fuera del libro {n_apertura} asiento(s) fechados el 1 de enero "
                      f"(apertura o ajuste de apertura) y {n_cierre} de regularización o cierre "
                      f"del ejercicio, aunque toquen cuentas de Hacienda.")
    if otros:
        avisos.append(f"Hay {len(otros)} movimiento(s) de las cuentas de Hacienda que no son "
                      f"retensiones (pagos, liquidaciones de modelos y rectificaciones): se listan "
                      f"aparte y no se netean contra los devengos del trimestre.")
    if n_mixtos:
        avisos.append(f"{n_mixtos} asiento(s) mezclan contrapartidas de trabajo y de actividades "
                      f"profesionales: se atribuyen al bloque de mayor importe (regla declarada).")
    if n_sin_base:
        avisos.append(f"{n_sin_base} movimiento(s) no tienen base derivable del asiento: se "
                      f"muestran sin base ni tipo, sin inventarla.")
    if not any(f["cuenta"] == "473" for f in movimientos):
        avisos.append("No hay retenciones soportadas en la cuenta 473 (activo): en este ejercicio "
                      "esa cuenta no recibe apuntes con contrapartida de clientes o ingresos.")
    if otras:
        cuentas_otras = ", ".join(sorted({f["cuenta"] for f in movimientos if f["tipo"] == "otras"}))
        avisos.append(f"El bloque «otras» ({fmt(otras)}) recoge cuentas distintas de la 4751 "
                      f"({cuentas_otras}): no es IRPF y por eso no se suma al total de retenciones.")
    if any(len([f for f in movimientos_vista if f["trimestre"] == q]) > LIMITE_DETALLE for q in trimestres):
        avisos.append(f"El detalle por trimestre se limita a {LIMITE_DETALLE} movimientos: el "
                      f"resto sigue en los datos del informe y en la descarga.")
    if not movimientos_vista:
        avisos.append("No hay retenciones contabilizadas en el periodo pedido: todas las cifras salen a cero.")

    numeros: dict[str, Any] = {
        "year": year, "trimestre": trimestre, "trimestres": trimestres,
        "retencionesTrabajo": trabajo, "retencionesProfesionales": profesionales,
        "retencionesOtras": otras, "retencionesTotal": total,
        "baseTrabajo": base_trabajo, "baseProfesionales": base_prof,
        "tipoMedioTrabajo": _r(trabajo / base_trabajo * 100) if base_trabajo > 0 and trabajo > 0 else None,
        "tipoMedioProfesionales": (_r(profesionales / base_prof * 100)
                                   if base_prof > 0 and profesionales > 0 else None),
        "porTrimestre": por_q, "porMes": por_m,
        "trimestreActual": next((f for f in por_q if f["trimestre"] == trimestre), None),
        "movimientos": movimientos, "otrosMovimientos": otros, "porCuenta": cuentas_filas,
        "bloques": [{"tipo": t, "etiqueta": e, "cuota": {"trabajo": trabajo, "profesionales": profesionales,
                                                         "otras": otras}[t],
                     "base": {"trabajo": base_trabajo, "profesionales": base_prof, "otras": 0.0}[t],
                     "n": sum(1 for f in movimientos if f["tipo"] == t)} for t, e in BLOQUES.items()],
        "cuentasInfo": [{"cuenta": c, "que": q, "modelo": m} for c, q, m in CUENTAS_INFO],
        "n_movimientos": len(movimientos), "n_otros": len(otros), "n_sin_base": n_sin_base,
        "n_asientos": len(grupos), "n_excluidos_apertura": n_apertura, "n_excluidos_cierre": n_cierre,
        "n_mixtos": n_mixtos, "metodo": dict(METODO), "cuadre": cuadre,
    }
    datos = dict(numeros)
    datos["data"] = dict(numeros)  # convención del portal: lee data.<clave>
    datos["avisos"] = avisos
    return datos


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    """KPIs del panel: lo retenido en el ejercicio y cuántos movimientos lo componen."""
    return {
        "retencionesTrabajo": datos.get("retencionesTrabajo", 0.0),
        "retencionesProfesionales": datos.get("retencionesProfesionales", 0.0),
        "retencionesTotal": datos.get("retencionesTotal", 0.0),
        "n_movimientos": datos.get("n_movimientos", 0),
    }


# ---------- informe ----------

def _pct(v: Any) -> str:
    return fmt_pct(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else "—"


def _descripcion(f: dict[str, Any]) -> str:
    desc = (f.get("descripcion") or "").strip()
    tercero = (f.get("tercero") or "").strip()
    extra = ""
    if tercero and tercero != "(sin identificar)" and tercero.lower() not in desc.lower():
        extra = f'<div style="font-size:10.5px;color:#8a95a6">Tercero: {inf.esc(tercero)}</div>'
    return f"{inf.esc(desc[:70])}{extra}" or "—"


def _fila_detalle(f: dict[str, Any]) -> list[str]:
    return [
        f'{inf.esc(f["fecha_txt"])}<div style="font-size:10.5px;color:#8a95a6">'
        f'{f["trimestre"]}T · {inf.esc(f["mes_txt"])}</div>',
        inf.esc(f["documento"]),
        _descripcion(f),
        f'<span style="color:#5b6b80">{inf.esc(", ".join(f["cuentas"]))}</span>',
        inf.importe(f["base"]) if f["base"] else '<span style="color:#8a95a6">sin base</span>',
        inf.importe(f["cuota"]),
        _pct(f["tipo_pct"]),
    ]


CABECERAS_DETALLE = ["Fecha", "Documento", "Descripción y tercero", "Cuenta", "Base derivada", "Cuota", "Tipo"]
ANCHOS_DETALLE = ["12%", "10%", "38%", "10%", "13%", "12%", "5%"]


def _td(contenido: str) -> str:
    return (f'<td style="padding:4px 8px;border-bottom:1px solid #eef2f8;text-align:left;'
            f'vertical-align:top">{contenido}</td>')


def _td_bold(contenido: str) -> str:
    return (f'<td style="padding:6px 8px;border-top:2px solid {inf.AZUL};background:{inf.AZUL_CLARO};'
            f'font-weight:bold;text-align:left">{contenido}</td>')


def _tabla_detalle(filas: Sequence[Sequence[str]], d: dict[str, Any], n_total: int) -> str:
    """Detalle de un trimestre con su fila de subtotal (la tabla del módulo, no la genérica:
    necesita el subtotal dentro del cuerpo)."""
    cab = "".join(
        f'<th style="padding:6px 8px;border-bottom:2px solid {inf.AZUL};color:{inf.AZUL};font-size:12px;'
        f'text-align:left;background:#fff;width:{ANCHOS_DETALLE[i]}">{inf.esc(c)}</th>'
        for i, c in enumerate(CABECERAS_DETALLE))
    cuerpo = "".join("<tr>" + "".join(_td(c) for c in fila) + "</tr>" for fila in filas)
    base = (d.get("baseTrabajo", 0) or 0) + (d.get("baseProfesionales", 0) or 0)
    cuota = (d.get("trabajo", 0) or 0) + (d.get("profesionales", 0) or 0)
    subtotal = "".join(_td_bold(c) for c in
                       ["Subtotal", "—", f"{n_total} movimientos", "—", inf.importe(base),
                        inf.importe(cuota), "—"])
    return (f'<table style="width:100%;border-collapse:collapse;font-size:12px">'
            f'<thead><tr>{cab}</tr></thead><tbody>{cuerpo}<tr>{subtotal}</tr></tbody></table>')



def informe_html(datos: dict[str, Any], ctx: dict[str, Any] | None = None, *,
                 empresa: str | None = None, year: int | None = None) -> str:
    """Informe HTML (empieza por `<div`), Arial 13 px, CSS inline y ancho 780 px."""
    ctx = dict(ctx or {})
    if empresa:
        ctx.setdefault("empresa", empresa)
    if year:
        ctx.setdefault("year", year)
    year = int(datos.get("year") or ctx.get("year") or 0)
    trimestre = datos.get("trimestre")
    trimestres = datos.get("trimestres") or [1, 2, 3, 4]
    nombre_empresa = ctx.get("empresa") or ""
    trabajo, profesionales = datos.get("retencionesTrabajo", 0.0), datos.get("retencionesProfesionales", 0.0)
    otras, total = datos.get("retencionesOtras", 0.0), datos.get("retencionesTotal", 0.0)
    por_q = datos.get("porTrimestre") or []
    qa = datos.get("trimestreActual") or {}
    # Con un trimestre pedido, los KPIs y el titular son los de ese trimestre (el resumen sigue
    # enseñando los cuatro, con el pedido marcado, para que el cliente tenga el contexto del año).
    alcance = f"{trimestre}T" if trimestre else "el ejercicio"
    k_trabajo = qa.get("trabajo", trabajo) if trimestre else trabajo
    k_prof = qa.get("profesionales", profesionales) if trimestre else profesionales
    k_total = qa.get("total", total) if trimestre else total
    k_movs = qa.get("nMovimientos", datos.get("n_movimientos", 0)) if trimestre else datos.get("n_movimientos", 0)

    # 1 · qué es esta cifra
    extra_trim = (f" En el {trimestre}T ({PERIODOS[trimestre - 1]}) van {fmt(k_total)}. "
                  f"El total del ejercicio es {fmt(total)}." if trimestre else "")
    intro = inf.aviso(
        f"Retenciones contabilizadas en {'el ' + alcance if trimestre else 'el ejercicio'}: "
        f"{fmt(k_total)} ({fmt(k_trabajo)} de trabajo y {fmt(k_prof)} de actividades "
        f"profesionales).{extra_trim} "
        "Son las retenciones apuntadas en la contabilidad, no las declaraciones presentadas: "
        "los modelos 111/115 del año pueden diferir (el 4T se declara en enero del año siguiente).",
        tipo="info", titulo="Retenciones contabilizadas, no declaradas")

    kpis = inf.kpis([
        (f"Retenciones de trabajo ({alcance} · 4751 · 64x)", inf.importe(k_trabajo)),
        (f"Retenciones de profesionales ({alcance} · 4751 · 60x/62x)", inf.importe(k_prof)),
        (f"Total retenciones de IRPF ({alcance})", inf.importe(k_total)),
        ("Movimientos contabilizados", str(k_movs)),
    ])

    # 2 · resumen por trimestres y modelo que se declara
    filas_res = []
    for d in por_q:
        marca = (f' <span style="font-size:10.5px;color:#5b6b80">(trimestre pedido)</span>'
                 if trimestre and d["trimestre"] == trimestre else "")
        filas_res.append([
            f'{d["trimestre"]}T <span style="color:#8a95a6">({inf.esc(d["periodo"])})</span>{marca}',
            str(d["nMovimientos"]), inf.importe(d["trabajo"]), _pct(d["tipoTrabajo"]),
            inf.importe(d["profesionales"]), _pct(d["tipoProfesionales"]),
            inf.importe(d["otras"]), inf.importe(d["total"]),
        ])
    filas_res.append([
        "TOTAL EJERCICIO", str(datos.get("n_movimientos", 0)), inf.importe(trabajo),
        _pct(datos.get("tipoMedioTrabajo")), inf.importe(profesionales),
        _pct(datos.get("tipoMedioProfesionales")), inf.importe(otras), inf.importe(total),
    ])
    tabla_res = inf.tabla(
        ["Trimestre", "Mov.", "Retención trabajo", "Tipo", "Retención profesionales", "Tipo",
         "Otras cuentas", "Total IRPF"],
        filas_res, anchos=["20%", "6%", "14%", "6%", "14%", "6%", "11%", "11%"])
    nota_res = ("Un importe por celda: la retención de trabajo es lo retenido a la plantilla "
                "(cuenta 4751, contrapartida 64x) y la de profesionales lo retenido en facturas de "
                "actividades profesionales (4751, contrapartida 60x/62x). «Otras cuentas» recoge "
                "los movimientos de retención de cuentas distintas de la 4751 y no se suma al total de IRPF.")
    tabla_modelos = inf.tabla(
        ["Trimestre", "Modelo de las retenciones de trabajo", "Modelo de las de profesionales",
         "Importe que se declara"],
        [[f'{d["trimestre"]}T', inf.esc(d["modelos"]["trabajo"]), inf.esc(d["modelos"]["profesionales"]),
          f'{inf.importe(d["trabajo"])} + {inf.importe(d["profesionales"])} '
          f'<span style="color:#5b6b80">(contabilizado)</span>']
         for d in por_q],
        anchos=["10%", "30%", "32%", "28%"])
    nota_modelos = ("Se indica qué modelo se declara con cada bloque; el importe que se enseña es "
                    "el contabilizado en los apuntes, nunca el finalmente declarado.")

    # 2b · reparto mensual (el «cuándo» del libro) y gráfica de trimestres
    filas_mes = [[d["mes_txt"], f'{d["trimestre"]}T', str(d["nMovimientos"]),
                  inf.importe(d["trabajo"]), inf.importe(d["profesionales"]),
                  inf.importe(d["otras"]), inf.importe(d["total"])]
                 for d in (datos.get("porMes") or [])]
    filas_mes.append(["TOTAL", "", str(datos.get("n_movimientos", 0)), inf.importe(trabajo),
                      inf.importe(profesionales), inf.importe(otras), inf.importe(total)])
    tabla_mes = inf.tabla(["Mes", "Trim.", "Mov.", "Trabajo", "Profesionales", "Otras cuentas",
                           "Total IRPF"], filas_mes,
                          anchos=["12%", "8%", "8%", "18%", "18%", "18%", "18%"])
    grafico = inf.barras_svg(
        [f'{d["trimestre"]}T' for d in por_q],
        [{"nombre": "Trabajo (111)", "color": inf.AZUL, "valores": [d["trabajo"] for d in por_q]},
         {"nombre": "Profesionales (115)", "color": "#c98a2b",
          "valores": [d["profesionales"] for d in por_q]}],
        titulo="Retenciones contabilizadas por trimestre")

    # 3 · qué cuenta alimenta cada bloque
    sufijo = " (ejercicio completo)" if trimestre else ""
    filas_bloques = [[inf.esc(b["etiqueta"]), str(b["n"]),
                      inf.importe(b["base"]) if b["base"] else "—", inf.importe(b["cuota"])]
                     for b in datos.get("bloques") or []]
    filas_bloques.append(["TOTAL RETENCIONES DE IRPF (trabajo + profesionales)",
                          str(datos.get("n_movimientos", 0)),
                          inf.importe((datos.get("baseTrabajo", 0.0) or 0.0)
                                      + (datos.get("baseProfesionales", 0.0) or 0.0)),
                          inf.importe(total)])
    tabla_bloques = inf.tabla(["Bloque y cuenta que lo alimenta", "Mov.", "Base derivada", "Cuota"],
                              filas_bloques, anchos=["56%", "8%", "18%", "18%"])
    filas_cuentas = [[inf.esc(c["cuenta"]), inf.esc(c["tipo"]), str(c["n"]),
                      inf.importe(c["base"]) if c["base"] else "—", inf.importe(c["cuota"])]
                     for c in datos.get("porCuenta") or []]
    tabla_cuentas = inf.tabla(["Cuenta", "Bloque", "Mov.", "Base derivada", "Cuota contabilizada"],
                              filas_cuentas or [["—", "—", "0", "—", inf.importe(0.0)]],
                              anchos=["12%", "38%", "8%", "18%", "24%"])
    filas_mapa = [[inf.esc(c["cuenta"]), inf.esc(c["que"]), inf.esc(c["modelo"])]
                  for c in datos.get("cuentasInfo") or []]
    tabla_mapa = inf.tabla(["Cuenta", "Qué recoge", "Modelo al que va"], filas_mapa,
                           anchos=["12%", "58%", "30%"])

    # 4 · detalle por trimestre (con subtotal)
    bloques_detalle: list[str] = []
    for q in trimestres:
        filas = [f for f in (datos.get("movimientos") or []) if f["trimestre"] == q]
        if not filas:
            bloques_detalle.append(inf.seccion(
                f"Detalle del {q}T ({PERIODOS[q - 1]})",
                inf.aviso(f"El {q}T no tiene retenciones contabilizadas en los apuntes cargados.",
                          tipo="info"),
                nota="Sin movimientos: no se inventa ninguna cifra para el trimestre."))
            continue
        vista = filas[:LIMITE_DETALLE]
        d = next((x for x in por_q if x["trimestre"] == q), {})
        tabla_q = _tabla_detalle([_fila_detalle(f) for f in vista], d, len(filas))
        nota = (f'Trabajo {fmt(d.get("trabajo", 0.0))} ({_pct(d.get("tipoTrabajo"))} de tipo medio) · '
                f'profesionales {fmt(d.get("profesionales", 0.0))} '
                f'({_pct(d.get("tipoProfesionales"))}) · otras cuentas {fmt(d.get("otras", 0.0))}.')
        if len(filas) > LIMITE_DETALLE:
            nota += f' Se muestran los primeros {LIMITE_DETALLE}; el detalle completo va en los datos.'
        bloques_detalle.append(inf.seccion(f"Detalle del {q}T ({PERIODOS[q - 1]})", tabla_q, nota=nota))

    # 5 · pagos y liquidaciones (no son retenciones)
    todos_otros = datos.get("otrosMovimientos") or []
    filas_otros = [[f'{inf.esc(f["fecha_txt"])}', inf.esc(f["documento"]), _descripcion(f),
                    inf.esc(f["cuenta"]), inf.importe(f["cuota"])]
                   for f in todos_otros[:LIMITE_OTROS]]
    bloque_otros = ""
    if filas_otros:
        nota_otros = ("Domiciliaciones del 111/115, liquidaciones del IVA o del Impuesto de "
                      "Sociedades, regularizaciones y rectificaciones: mueven las mismas cuentas "
                      "pero no son retenciones del ejercicio, así que no entran en el total ni se "
                      "netean contra los trimestres. El importe es el movimiento de la cuenta de "
                      "Hacienda: positivo cuando la aumenta (devengo de la liquidación), negativo "
                      "cuando la disminuye (pago o rectificación).")
        if len(todos_otros) > LIMITE_OTROS:
            nota_otros += (f" Se listan los primeros {LIMITE_OTROS} de {len(todos_otros)}; el "
                           f"resto va en los datos del informe.")
        bloque_otros = inf.seccion(
            "Pagos y liquidaciones de las cuentas de Hacienda (no son retenciones)",
            inf.tabla(["Fecha", "Documento", "Descripción y tercero", "Cuenta", "Importe"],
                      filas_otros, anchos=["12%", "12%", "48%", "10%", "18%"]),
            nota=nota_otros)

    # 6 · método declarado y avisos
    metodo = datos.get("metodo") or METODO
    tabla_metodo = inf.tabla(["Qué", "Cómo se calcula (declarado)"],
                             [[inf.esc(k), inf.esc(v)] for k, v in metodo.items()],
                             anchos=["18%", "82%"])
    avisos = datos.get("avisos") or []
    bloque_avisos = "".join(inf.aviso(a, tipo="alerta") for a in avisos)

    cuerpo = (
        intro + kpis
        + inf.seccion("Resumen por trimestres", tabla_res + f'<div style="margin-top:10px">{grafico}</div>',
                      nota=nota_res)
        + inf.seccion("Reparto mensual", tabla_mes,
                      nota="El «cuándo» de las retenciones: cada mes con lo retenido y el trimestre al "
                           "que pertenece. Alimenta el modelo 111/115 del trimestre (el 4T se presenta "
                           "en enero del año siguiente).")
        + inf.seccion("Modelo con el que se declara cada trimestre", tabla_modelos, nota=nota_modelos)
        + inf.seccion("Cuentas que alimentan cada bloque" + sufijo, tabla_bloques)
        + inf.seccion("Cuota por cuenta" + sufijo, tabla_cuentas,
                      nota="Sólo movimientos de retención (devengo). La cuota es el saldo de la cuenta "
                           "de retención en el asiento: haber−debe en las acreedoras, debe−haber en la 473.")
        + inf.seccion("Mapa de cuentas del libro", tabla_mapa,
                      nota="Cuentas que mira el libro (4751, 4752, 4750, 4759 y 473) y qué recoge cada una.")
        + "".join(bloques_detalle)
        + bloque_otros
        + inf.seccion("Método de cálculo", tabla_metodo)
        + (inf.seccion("Avisos del cálculo", bloque_avisos,
                       nota="Comprobaciones de integridad y límites del cálculo hechas por el módulo.")
           if avisos else "")
    )
    subtitulo = (f"Ejercicio {year} · {trimestre}T ({PERIODOS[trimestre - 1]})"
                 if trimestre else f"Ejercicio {year} · los cuatro trimestres")
    return inf.envoltura(
        titulo=TITULO, subtitulo=subtitulo, empresa=nombre_empresa, ejercicio=year, cuerpo=cuerpo,
        meta={"Retenciones contabilizadas": fmt(k_total), "Ámbito": alcance,
              "Movimientos": str(k_movs),
              "Datos": "ERP apiCON (ejercicio completo)"},
    )


__all__ = ["NOMBRE", "TITULO", "INTERNO", "DESPLAZAMIENTOS", "PARAMETROS", "CUENTAS_INFO",
           "calcular", "informe_html", "metricas_dashboard", "normalizar_trimestre"]
