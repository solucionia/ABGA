"""Módulo `memoria` — REQ-08 Memoria de cuentas anuales (PGC PYME).

Portado del nodo Code «Preparar Datos Memoria» del workflow REQ-08 de n8n. El original
preparaba los datos de las 10 notas del PGC de PYMES y los entregaba **ya formateados como
texto**; aquí se devuelven números y el HTML lo maqueta `app/informes.py`, con el ancho
(800 px) y el cuerpo de letra (11 px) que el cliente tiene fijados para la Memoria.

Correspondencia de las 10 notas con los datos del workflow original:

    Nota 1  Actividad de la empresa ................... empresa, localidad, administrador, fechaFormulacion
    Nota 2  Bases de presentación ..................... PyG + balance + comparativa con el año anterior
    Nota 3  Aplicación de resultados .................. resultado del ejercicio y cuentas de patrimonio
    Nota 4  Normas de registro y valoración ........... inmovilizadoDetalle (criterios) y amortizaciones
    Nota 5  Inmovilizado intangible y material ........ inmovilizadoDetalle (cifras)
    Nota 6  Activos financieros, clientes y deudores ... inversionesLP, clientes, otros deudores, tesorería
    Nota 7  Pasivos financieros y deudas .............. vencimientos, deudasLP, deudasCP, proveedores
    Nota 8  Situación fiscal .......................... ivaRepercutido, ivaSoportado, retenciones, cuota, RAI
    Nota 9  Operaciones con partes vinculadas ......... parámetro `nota9` (input manual del asesor)
    Nota 10 Otra información y medio ambiente ......... parámetros `nota10` y `nota10MedioAmbiente`

Las notas 1-8 salen de los apuntes; las 9-10 son texto del asesor, como en el original (que las
recibía ya calculadas en `tokens`). Si no llegan, el informe lo dice y queda el aviso en
`datos["avisos"]`: nunca se rellena el hueco con texto o cifras inventadas.

## Lo que se ha eliminado del original (no volver a introducirlo)

El JavaScript **inventaba cifras** cuando no las tenía, y eso no se puede portar tal cual:

1. ``is = sumaD(630) || (rai > 0 ? rai * 0.25 : 0)`` y, para el ejercicio anterior,
   ``resultadoAnt = raiAnt - (raiAnt > 0 ? raiAnt * 0.25 : 0)``. Es decir: si no había asiento
   de Impuesto sobre sociedades se **estimaba un 25 % sobre el RAI** y se presentaba como
   gasto por impuesto y como resultado del ejercicio (y del ejercicio anterior). Aquí el gasto
   por impuesto es el saldo real de la 630 y el resultado del ejercicio anterior sale de los
   **apuntes del ejercicio anterior**; si no hay asiento de impuesto, el informe lo dice.
2. ``inmovilizadoDetalle`` calculaba el saldo inicial con ``inmovInt * 1.2`` / ``inmovMat * 1.15``
   y la dotación con el 20 % / 15 % del saldo final, y ponía a cero las altas y las bajas.
   Aquí el cuadro se rellena con los movimientos reales del ejercicio y la amortización
   acumulada real (28x); las columnas que dependen del asiento de apertura van marcadas como
   pendientes y el cuadro requiere completarse a mano (está dicho en el informe y en
   `datos["avisos"]`).
3. ``vencimientos`` repartía ``deudasLP * 0.2`` en cada uno de los cinco tramos temporales.
   Aquí los tramos salen en blanco con su aviso («no consta en los apuntes, requiere
   completarse a mano») y el total por naturaleza es el saldo real.

## Diferencias deliberadas

- Los prefijos PGC son los mismos que los de `modulos/pyg.py` (copiados aquí, igual que hace
  `autodespro`), para que la Memoria y el informe «Balance y PyG» no den cifras distintas del
  mismo ejercicio. El REQ-08 original traía listas más antiguas (sin `607`/`609` en
  aprovisionamientos, sin `67` en otros gastos, sin `690`-`692` en amortizaciones, sin `763`).
- La Memoria clasifica la cuenta **476** (Organismos de la Seguridad Social, acreedores) como
  pasivo, según su naturaleza, igual que `pyg.py` tras su corrección. En el REQ-08 original esa
  cuenta estaba en los deudores y el balance cuadraba por casualidad (restaba lo mismo del activo
  y del pasivo).
- No se llama al ERP ni a la caché: el módulo recibe las líneas ya cargadas (contrato de módulos).
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from .. import informes as inf
from ..ledger import (MESES_LARGOS, Linea, comprobar_cuadre, fmt, fmt_pct, num,
                      saldos_por_cuenta, suma_acreedor, suma_deudor)

NOMBRE = "memoria"
TITULO = "Memoria de cuentas anuales (PGC PYME)"
INTERNO = False
DESPLAZAMIENTOS = [0, -1]
# Valores por defecto del workflow original: localidad «Madrid» y formulación el 31 de marzo
# del ejercicio (el año se resuelve en `calcular`, que es donde se conoce el ejercicio).
PARAMETROS: dict[str, Any] = {
    "nota9": "",
    "nota10": "",
    "nota10MedioAmbiente": "",
    "administrador": "",
    "localidad": "Madrid",
    "fechaFormulacion": None,
}

AZUL_FILA = "#eef4fd"

# ---------------------------------------------------------------- prefijos PGC (sin solapes)
# Mismos grupos que `modulos/pyg.py`: la Memoria y el informe de Balance y PyG comparten cifras.
P_VENTAS = ["700", "701", "702", "703", "704", "705"]
P_OTROS_INGRESOS = ["706", "708", "709", "740", "741", "746", "747", "748", "749", "75", "778"]
P_APROVISIONAMIENTOS = ["600", "601", "602", "606", "607", "608", "609", "610", "611", "612"]
P_PERSONAL = ["640", "641", "642", "643", "644", "649"]
P_OTROS_GASTOS = ["620", "621", "622", "623", "624", "625", "626", "627", "628", "629",
                  "631", "632", "633", "634", "636", "639", "650", "651", "659", "67"]
P_AMORTIZACIONES = ["680", "681", "682", "690", "691", "692"]
P_ING_FINANCIEROS = ["760", "761", "762", "763", "768", "769"]
P_GASTOS_FINANCIEROS = ["660", "661", "662", "663", "664", "665", "668", "669"]
P_IMPUESTO = ["630"]

P_INMOV_INTANGIBLE = ["200", "201", "202", "203", "204", "205", "206", "207", "280"]
P_INMOV_MATERIAL = ["210", "211", "212", "213", "214", "215", "216", "217", "218", "219",
                    "281", "282"]
P_INVERSIONES_LP = [str(n) for n in range(250, 270)]
P_EXISTENCIAS = [str(n) for n in range(300, 360)]
# 53x y 54x: inversiones financieras a corto plazo (faltaban; ver pyg.py)
P_INVERSIONES_CP = [str(n) for n in range(530, 550)]
P_CLIENTES = ["430", "431", "432", "433", "434", "435", "436", "437", "438", "439", "440", "441",
              "490"]  # 490: deterioro de créditos comerciales, correctora de clientes
P_OTROS_DEUDORES = ["460", "470", "471", "472", "473", "474", "480", "481", "567", "568"]
P_TESORERIA = ["570", "571", "572", "573", "574", "575", "576", "577"]
P_CAPITAL = ["100", "101", "102", "103", "104", "108", "109"]
P_RESERVAS = [str(n) for n in range(110, 122)]
P_SUBVENCIONES = ["130", "131", "132"]
P_DEUDAS_LP = [str(n) for n in range(150, 180)]
P_PROVEEDORES = [str(n) for n in range(400, 420)]
P_DEUDAS_CREDITO_CP = [str(n) for n in range(500, 530)] + [str(n) for n in range(550, 560)]
# cuentas que el balance de `pyg` mete en el pasivo corriente y aquí se detallan aparte
P_ADMINISTRACIONES = ["475", "476", "477"]
P_PERSONAL_PENDIENTE = ["465", "466"]

# detalle del personal y de la aplicación de resultados (notas 1, 3 y 4)
P_SUELDOS = ["640"]
P_SEGURIDAD_SOCIAL = ["642"]
P_INDEMNIZACIONES = ["641"]
P_RESULTADO_EJERCICIO = ["129"]
P_REMANENTE = ["120"]
P_RESULTADOS_NEGATIVOS = ["121"]
P_RESERVAS_DISPONIBLES = ["113", "114", "115", "116", "117"]
P_APORTACIONES_SOCIOS = ["118"]
P_CORRECCIONES_VALOR = ["290", "291", "292", "293", "294", "295", "296", "297", "298", "299",
                        "390", "391", "392", "393", "394", "395", "396", "397", "398", "399",
                        "490", "491", "492", "493", "494", "495", "496", "497", "498", "499",
                        "590", "591", "592", "593", "594", "595", "596", "597", "598", "599"]

# inmovilizado por naturaleza: (clave, etiqueta, bruto, amortización acumulada, dotación del año)
GRUPOS_INMOVILIZADO: list[tuple[str, str, list[str], list[str], list[str]]] = [
    ("intangible", "Inmovilizado intangible (200-207 · 280)", ["200", "201", "202", "203", "204",
                                                               "205", "206", "207"], ["280"],
     ["680", "690"]),
    ("material", "Inmovilizado material (210-219 · 281-282)", ["210", "211", "212", "213", "214",
                                                               "215", "216", "217", "218", "219"],
     ["281", "282"], ["681", "691"]),
    ("inversiones", "Inversiones financieras a largo plazo (25x-26x)", P_INVERSIONES_LP, [],
     ["696", "697", "698"]),
]

# grupos del balance para las comprobaciones de integridad: (etiqueta, prefijos, ¿es activo?)
# Los prefijos son los mismos que usa `pyg` para el balance, para que la comprobación detecte
# justo las incongruencias de ese reparto (no de otro).
GRUPOS_BALANCE: list[tuple[str, list[str], bool]] = [
    ("Inmovilizado intangible (20x)", ["20"], True),
    ("Inmovilizado material (21x)", ["21"], True),
    ("Inversiones financieras a largo plazo (25x-26x)", [str(n) for n in range(250, 270)], True),
    ("Existencias (30x-35x)", [str(n) for n in range(300, 360)], True),
    ("Clientes y deudores comerciales (43x-44x)", ["43", "44"], True),
    ("Otros deudores (460-474, 480-481, 567-568)", ["460", "470", "471", "472", "473", "474",
                                                    "480", "481", "567", "568"], True),
    ("Tesorería (57x)", ["570", "571", "572", "573", "574", "575", "576", "577"], True),
    ("Capital y reservas (10x-12x)", ["10", "11", "12"], False),
    ("Subvenciones (13x)", ["13"], False),
    ("Deudas a largo plazo (15x-17x)", [str(n) for n in range(150, 180)], False),
    ("Proveedores y acreedores comerciales (40x-41x)", ["40", "41"], False),
    ("Otras deudas y partidas a pagar (45x, 50x-55x)", ["450", "451", "452", "453", "454", "455",
                                                       "456", "457", "458", "459", "465", "466",
                                                       "50", "51", "52", "53", "54", "55"], False),
    ("Deudas con las Administraciones Públicas (475-477)", ["475", "476", "477"], False),
]


# ---------------------------------------------------------------- utilidades

def _r(x: Any) -> float:
    """Todos los números salen a dos decimales (contrato: números, no texto formateado)."""
    try:
        return round(float(x or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def fecha_larga(v: Any) -> str:
    """`20250108` → `8 de enero de 2025` (para el aviso de los apuntes cargados)."""
    f = int(v or 0)
    if f < 10_000_000:
        return "—"
    dia, mes, anio = f % 100, (f // 100) % 100, f // 10000
    if not 1 <= mes <= 12:
        return str(f)
    return f"{dia} de {MESES_LARGOS[mes - 1]} de {anio}"


def _es_apertura(l: Linea, year: int) -> bool:
    """Asiento de apertura: el que abre el ejercicio o el que se rotula como tal."""
    if "apertura" in (l.descripcion or "").lower():
        return True
    return bool(year) and l.fecha == int(f"{year}0101")


def movimientos_del_anio(lineas: Iterable[Linea], prefijos: Sequence[str],
                         year: int) -> dict[str, Any]:
    """ΣDebe, ΣHaber y nº de líneas de un grupo de cuentas, dejando fuera la apertura.

    Sin el asiento de apertura, ``debe`` son las altas del ejercicio y ``haber`` las bajas;
    si el ejercicio **sí** trae apertura, esas líneas se descuentan (y se cuentan aparte) para
    no presentarlas como altas.
    """
    tupla = tuple(prefijos)
    debe = haber = 0.0
    n = apertura = 0
    for l in lineas:
        if not l.cuenta.startswith(tupla):
            continue
        if _es_apertura(l, year):
            apertura += 1
            continue
        debe += l.debe
        haber += l.haber
        n += 1
    return {"debe": _r(debe), "haber": _r(haber), "n": n, "lineas_apertura": apertura}


def _etiqueta_cuenta(cuenta: str, descripciones: dict[str, str]) -> str:
    """`430000900184` + «OP/2025/00005-Avintia Proyectos…» → `430000900184 · Avintia Proyectos…`.

    El campo `Tercero` llega vacío en los apuntes del ERP, así que el nombre se toma del texto
    del asiento (lo último que va detrás del guion del documento).
    """
    texto = (descripciones.get(cuenta) or "").strip()
    if "-" in texto:
        texto = texto.split("-")[-1].strip()
    return f"{cuenta} · {texto}" if texto else cuenta


def top_cuentas(lineas: Iterable[Linea], prefijos: Sequence[str], *, deudor: bool = True,
                limite: int = 10) -> list[dict[str, Any]]:
    """Mayores saldos por subcuenta de un grupo (clientes, proveedores…), en valor absoluto."""
    lineas = list(lineas)
    s = saldos_por_cuenta(lineas)
    descripciones: dict[str, str] = {}
    for l in lineas:
        if l.descripcion and not descripciones.get(l.cuenta):
            descripciones[l.cuenta] = l.descripcion
    filas = []
    for cuenta, saldo in s.items():
        if not any(cuenta.startswith(p) for p in prefijos):
            continue
        valor = saldo.deudor if deudor else saldo.acreedor
        if abs(valor) < 0.01:
            continue
        filas.append({"cuenta": cuenta, "etiqueta": _etiqueta_cuenta(cuenta, descripciones),
                      "saldo": _r(valor), "n": saldo.n})
    filas.sort(key=lambda f: -abs(f["saldo"]))
    return filas[:limite]


def grupos_sin_movimiento(saldos: dict[str, Any]) -> list[str]:
    """Grupos del balance/de la cuenta de resultados que no tienen ninguna cuenta en los apuntes.

    Es la explicación de por qué el balance no cuadra: sin las cuentas de capital, de
    existencias o de amortización acumulada, la Memoria no puede cerrar esas notas.
    """
    faltan = []
    for etiqueta, prefijos, _es_activo in GRUPOS_BALANCE:
        if not any(c.startswith(tuple(prefijos)) for c in saldos):
            faltan.append(etiqueta)
    return faltan


def saldos_contrarios(saldos: dict[str, Any], *, limite: int = 10) -> list[dict[str, Any]]:
    """Cuentas con el saldo al revés de la naturaleza de su grupo (activo acreedor, pasivo deudor).

    El informe original las tapaba con `Math.max(0, …)`; aquí se enseñan, porque son la pista
    de por qué un epígrafe no cuadra.
    """
    filas = []
    for cuenta, saldo in saldos.items():
        for etiqueta, prefijos, es_activo in GRUPOS_BALANCE:
            if not cuenta.startswith(tuple(prefijos)):
                continue
            saldo_natural = saldo.deudor if es_activo else saldo.acreedor
            if saldo_natural < -0.01:
                filas.append({"cuenta": cuenta, "grupo": etiqueta,
                              "naturaleza": "activo" if es_activo else "pasivo",
                              "saldo": _r(saldo_natural), "n": saldo.n})
            break
    filas.sort(key=lambda f: -abs(f["saldo"]))
    return filas[:limite]


# ---------------------------------------------------------------- cálculo

def calcular(por_anio: dict[int, list[Linea]], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Las 10 notas, en números. Nunca estima: lo que no se puede sacar de los apuntes se avisa."""
    ctx = dict(ctx or {})
    avisos: list[str] = []

    if isinstance(por_anio, dict):
        mapa = {int(k): list(v or []) for k, v in por_anio.items()}
    else:  # tolera que le pasen las líneas del ejercicio directamente
        mapa = {int(ctx.get("year") or 0): list(por_anio or [])}

    year = int(ctx.get("year") or 0) or (max(mapa) if mapa else 0)
    lineas = mapa.get(year) or []
    if not lineas and mapa:
        year_alt = max((a for a in mapa if mapa[a]), default=0)
        if year_alt:
            avisos.append(f"No llegaron apuntes del ejercicio {year}; se calcula la Memoria con "
                          f"los del {year_alt}, que son los que hay cargados.")
            year, lineas = year_alt, mapa[year_alt]
    if not lineas:
        avisos.append(f"No hay apuntes cargados del ejercicio {year}: todas las cifras salen a "
                      "cero y la Memoria no se puede formular todavía.")
    lineas_ant = mapa.get(year - 1) or []
    if lineas and not lineas_ant:
        avisos.append(f"No hay apuntes del ejercicio {year - 1}: la comparativa con el ejercicio "
                      "anterior se queda en blanco (no se estima).")

    # ---------- parámetros del asesor (el original los recibía en `tokens`) ----------
    localidad = str(ctx.get("localidad") or "").strip() or "Madrid"
    administrador = str(ctx.get("administrador") or "").strip()
    fecha_formulacion = str(ctx.get("fechaFormulacion") or "").strip() or f"31 de marzo de {year}"
    nota9 = str(ctx.get("nota9") or "").strip()
    nota10 = str(ctx.get("nota10") or "").strip()
    nota10_medioambiente = str(ctx.get("nota10MedioAmbiente") or "").strip()
    if not administrador:
        avisos.append("No se ha indicado el administrador (`administrador`): la Nota 1 y la "
                      "formulación se firman a mano.")
    if not nota9:
        avisos.append("La Nota 9 (operaciones con partes vinculadas) es texto del asesor y no ha "
                      "llegado: queda pendiente de redactar a mano.")
    if not nota10 and not nota10_medioambiente:
        avisos.append("La Nota 10 (otra información y medio ambiente) es texto del asesor y no ha "
                      "llegado: queda pendiente de redactar a mano.")

    s = saldos_por_cuenta(lineas)
    sa = saldos_por_cuenta(lineas_ant)

    # ---------- PyG (mismos grupos que `pyg`) ----------
    ventas = suma_acreedor(s, P_VENTAS, recortar=False)
    otros_ingresos = suma_acreedor(s, P_OTROS_INGRESOS, recortar=False)
    total_ingresos = ventas + otros_ingresos
    aprovisionamientos = suma_deudor(s, P_APROVISIONAMIENTOS, recortar=False)
    gastos_personal = suma_deudor(s, P_PERSONAL, recortar=False)
    sueldos = suma_deudor(s, P_SUELDOS, recortar=False)
    seguridad_social = suma_deudor(s, P_SEGURIDAD_SOCIAL, recortar=False)
    indemnizaciones = suma_deudor(s, P_INDEMNIZACIONES, recortar=False)
    otros_gastos = suma_deudor(s, P_OTROS_GASTOS, recortar=False)
    amortizaciones = suma_deudor(s, P_AMORTIZACIONES, recortar=False)
    ebitda = total_ingresos - aprovisionamientos - gastos_personal - otros_gastos
    ebit = ebitda - amortizaciones
    ingresos_financieros = suma_acreedor(s, P_ING_FINANCIEROS, recortar=False)
    gastos_financieros = suma_deudor(s, P_GASTOS_FINANCIEROS, recortar=False)
    rai = ebit + ingresos_financieros - gastos_financieros
    # el impuesto es el SALDO REAL de la 630: el original estimaba un 25 % del RAI cuando no había
    # asiento, y esa estimación se ha eliminado a propósito (ver el docstring del módulo).
    cuota_impuesto = suma_deudor(s, P_IMPUESTO, recortar=False)
    resultado = rai - cuota_impuesto
    cash_flow = resultado + amortizaciones
    if abs(cuota_impuesto) < 0.01:
        avisos.append("Los apuntes del ejercicio no traen ningún asiento de Impuesto sobre "
                      "sociedades (630): la cuota no se estima con un 25 % del RAI como hacía el "
                      "workflow original — esa cifra era una estimación, no un dato del ERP — y "
                      "el gasto por impuesto de la liquidación tiene que aportarlo el asesor. "
                      "El resultado del ejercicio se muestra antes de impuesto.")
    if abs(amortizaciones) < 0.01:
        avisos.append("No hay ninguna línea de amortización del ejercicio (68x): sin la dotación "
                      "en los apuntes, la Nota 4 y el cuadro de inmovilizado de la Nota 5 "
                      "requieren completarse a mano.")

    # ---------- ejercicio anterior (datos reales, no el 25 % estimado del original) ----------
    def _pyg_de(saldos: dict[str, Any]) -> dict[str, float]:
        """Cuenta de resultados completa de un ejercicio, sobre sus propios apuntes."""
        ventas_ = suma_acreedor(saldos, P_VENTAS, recortar=False)
        otros_ = suma_acreedor(saldos, P_OTROS_INGRESOS, recortar=False)
        ing = ventas_ + otros_
        aprov_ = suma_deudor(saldos, P_APROVISIONAMIENTOS, recortar=False)
        personal_ = suma_deudor(saldos, P_PERSONAL, recortar=False)
        otros_gastos_ = suma_deudor(saldos, P_OTROS_GASTOS, recortar=False)
        amort_ = suma_deudor(saldos, P_AMORTIZACIONES, recortar=False)
        ebitda_ = ing - aprov_ - personal_ - otros_gastos_
        ing_fin_ = suma_acreedor(saldos, P_ING_FINANCIEROS, recortar=False)
        gas_fin_ = suma_deudor(saldos, P_GASTOS_FINANCIEROS, recortar=False)
        ebit_ = ebitda_ - amort_
        rai_ = ebit_ + ing_fin_ - gas_fin_
        impuesto_ = suma_deudor(saldos, P_IMPUESTO, recortar=False)
        return {"ventas": ventas_, "totalIngresos": ing, "ebitda": ebitda_, "ebit": ebit_,
                "rai": rai_, "impuesto": impuesto_, "resultado": rai_ - impuesto_}

    ant = _pyg_de(sa)
    ingresos_ant, rai_ant, resultado_ant = ant["totalIngresos"], ant["rai"], ant["resultado"]

    def pct(n: float, d: float) -> float:
        return (n / d * 100) if d else 0.0

    # ---------- balance ----------
    inmov_intangible = suma_deudor(s, P_INMOV_INTANGIBLE, recortar=False)
    inmov_material = suma_deudor(s, P_INMOV_MATERIAL, recortar=False)
    inversiones_lp = suma_deudor(s, P_INVERSIONES_LP, recortar=False)
    activo_no_corriente = inmov_intangible + inmov_material + inversiones_lp
    existencias = suma_deudor(s, P_EXISTENCIAS, recortar=False)
    existencias_ant = suma_deudor(sa, P_EXISTENCIAS, recortar=False)
    clientes = suma_deudor(s, P_CLIENTES, recortar=False)
    otros_deudores = suma_deudor(s, P_OTROS_DEUDORES, recortar=False)
    iva_soportado = suma_deudor(s, ["472"], recortar=False)
    tesoreria = suma_deudor(s, P_TESORERIA, recortar=False)
    inversiones_cp = suma_deudor(s, P_INVERSIONES_CP, recortar=False)
    activo_corriente = existencias + clientes + otros_deudores + tesoreria + inversiones_cp
    total_activo = activo_no_corriente + activo_corriente

    capital = suma_acreedor(s, P_CAPITAL, recortar=False)
    reservas = suma_acreedor(s, P_RESERVAS, recortar=False)
    subvenciones = suma_acreedor(s, P_SUBVENCIONES, recortar=False)
    patrimonio_neto = capital + reservas + resultado + subvenciones
    deudas_lp = suma_acreedor(s, P_DEUDAS_LP, recortar=False)
    proveedores = suma_acreedor(s, P_PROVEEDORES, recortar=False)
    deudas_credito_cp = suma_acreedor(s, P_DEUDAS_CREDITO_CP, recortar=False)
    administraciones = suma_acreedor(s, P_ADMINISTRACIONES, recortar=False)
    personal_pendiente = suma_acreedor(s, P_PERSONAL_PENDIENTE, recortar=False)
    pasivo_corriente = proveedores + deudas_credito_cp + administraciones + personal_pendiente
    total_pasivo = deudas_lp + pasivo_corriente + patrimonio_neto
    fondo_maniobra = activo_corriente - pasivo_corriente
    exigible = deudas_lp + pasivo_corriente

    activo_no_corriente_ant = (suma_deudor(sa, P_INMOV_INTANGIBLE, recortar=False)
                               + suma_deudor(sa, P_INMOV_MATERIAL, recortar=False)
                               + suma_deudor(sa, P_INVERSIONES_LP, recortar=False))
    activo_corriente_ant = (suma_deudor(sa, P_EXISTENCIAS, recortar=False)
                            + suma_deudor(sa, P_CLIENTES, recortar=False)
                            + suma_deudor(sa, P_OTROS_DEUDORES, recortar=False)
                            + suma_deudor(sa, P_TESORERIA, recortar=False))
    pasivo_corriente_ant = (suma_acreedor(sa, P_PROVEEDORES, recortar=False)
                            + suma_acreedor(sa, P_DEUDAS_CREDITO_CP, recortar=False)
                            + suma_acreedor(sa, P_ADMINISTRACIONES, recortar=False)
                            + suma_acreedor(sa, P_PERSONAL_PENDIENTE, recortar=False))
    patrimonio_neto_ant = (suma_acreedor(sa, P_CAPITAL, recortar=False)
                           + suma_acreedor(sa, P_RESERVAS, recortar=False)
                           + suma_acreedor(sa, P_SUBVENCIONES, recortar=False) + resultado_ant)
    fondo_maniobra_ant = activo_corriente_ant - pasivo_corriente_ant

    # ---------- Nota 5 · inmovilizado (cifras reales, columnas pendientes señaladas) ----------
    inmovilizado: list[dict[str, Any]] = []
    for clave, etiqueta, bruto_p, amort_p, dotacion_p in GRUPOS_INMOVILIZADO:
        bruto = suma_deudor(s, bruto_p, recortar=False)
        amort_acumulada = suma_acreedor(s, amort_p, recortar=False) if amort_p else 0.0
        dotacion = suma_deudor(s, dotacion_p, recortar=False) if dotacion_p else 0.0
        mov = movimientos_del_anio(lineas, bruto_p, year)
        inmovilizado.append({
            "clave": clave, "etiqueta": etiqueta,
            "bruto": _r(bruto), "amortizacionAcumulada": _r(amort_acumulada),
            "saldoApuntes": _r(bruto - amort_acumulada),
            "dotacionEjercicio": _r(dotacion),
            "altasEjercicio": mov["debe"], "bajasEjercicio": mov["haber"],
            "lineas": mov["n"], "lineasApertura": mov["lineas_apertura"],
            # columnas que dependen del asiento de apertura: NO se estiman
            "saldoInicial": None, "saldoFinal": None,
        })
    total_inmovilizado = _r(sum(f["saldoApuntes"] for f in inmovilizado))
    hay_apertura = any(f["lineasApertura"] for f in inmovilizado)
    if inmovilizado:
        primera = min((l.fecha for l in lineas if l.fecha), default=0)
        avisos.append(
            "El cuadro de inmovilizado del PGC (saldo inicial, altas, bajas, amortización del "
            "ejercicio y saldo final) no se puede cerrar con los apuntes cargados"
            + (f": el más antiguo es del {fecha_larga(primera)}" if primera else "")
            + (", y las líneas de apertura que trae el ejercicio se descuentan de las altas"
               if hay_apertura else " y no incluyen el asiento de apertura")
            + ". Faltan el saldo inicial y las cuentas de amortización acumulada (28x), así que "
            "ese cuadro requiere completarse a mano. En su lugar se muestran los movimientos "
            "reales del ejercicio y el saldo que resulta de los apuntes; el workflow original "
            "estimaba el saldo inicial con un ×1,2 y un ×1,15 sobre el saldo final, y eso no se "
            "hace aquí.")
    amortizacion_acumulada = _r(sum(f["amortizacionAcumulada"] for f in inmovilizado))
    if amortizacion_acumulada == 0:
        avisos.append("Los apuntes no traen ninguna cuenta de amortización acumulada (28x): el "
                      "inmovilizado se informa por su valor bruto de los apuntes y la "
                      "amortización acumulada tiene que completarla el asesor a mano.")

    # ---------- Nota 6 · activos financieros y deudores ----------
    clientes_detalle = top_cuentas(lineas, P_CLIENTES, deudor=True, limite=10)
    if clientes and iva_soportado and iva_soportado > clientes:
        avisos.append(f"La cuenta 472 (IVA soportado) acumula {fmt(iva_soportado)} dentro de los "
                      "otros deudores, más que los propios clientes: revisar con el asesor si el "
                      "extracto del ERP incluye todas las liquidaciones de IVA del ejercicio.")

    # ---------- Nota 7 · pasivos y vencimientos ----------
    pasivos = [
        ("Deudas a largo plazo (15x-17x)", deudas_lp,
         "Largo plazo (más de un ejercicio)"),
        ("Deudas con entidades de crédito u otras a corto (50x-52x, 55x)", deudas_credito_cp,
         "Corto plazo (ejercicio siguiente)"),
        ("Acreedores comerciales y proveedores (40x-41x)", proveedores,
         "Corto plazo (ejercicio siguiente)"),
        ("Otras deudas con las Administraciones Públicas (475-477)", administraciones,
         "Corto plazo (ejercicio siguiente)"),
        ("Remuneraciones pendientes de pago (465-466)", personal_pendiente,
         "Corto plazo (ejercicio siguiente)"),
    ]
    avisos.append(
        "El detalle de vencimientos por año de las deudas no consta en los apuntes del ERP (no hay "
        "cuadros de amortización de los préstamos ni fechas de vencimiento por línea): ese cuadro "
        "requiere completarse a mano. El workflow original repartía el saldo en cinco tramos "
        "iguales (20 % cada año), que era una estimación inventada; aquí sólo se muestran los "
        "totales reales por naturaleza.")
    proveedores_detalle = top_cuentas(lineas, P_PROVEEDORES, deudor=False, limite=8)
    if proveedores < 0:
        avisos.append(f"Los acreedores comerciales (40x-41x) salen con saldo deudor de "
                      f"{fmt(proveedores)}: hay anticipos a proveedores o pagos sin factura "
                      "registrada; conviene revisarlo antes de firmar la Memoria.")

    # ---------- Nota 8 · situación fiscal ----------
    iva_repercutido = suma_acreedor(s, ["477"], recortar=False)
    retenciones = suma_acreedor(s, ["4751"], recortar=False)
    # el IVA repercutido (477) ya se informa en su propia fila: aquí sólo el resto de la 475x y la 476
    otras_fiscales = _r(administraciones - iva_repercutido - retenciones)
    saldo_iva = iva_repercutido - iva_soportado
    cuota_diferencial = cuota_impuesto - retenciones

    # ---------- Nota 3 · aplicación de resultados ----------
    resultado_en_libros = suma_acreedor(s, P_RESULTADO_EJERCICIO, recortar=False)
    remanente = suma_acreedor(s, P_REMANENTE, recortar=False)
    resultados_negativos = suma_deudor(s, P_RESULTADOS_NEGATIVOS, recortar=False)
    reservas_disponibles = suma_acreedor(s, P_RESERVAS_DISPONIBLES, recortar=False)
    aportaciones_socios = suma_acreedor(s, P_APORTACIONES_SOCIOS, recortar=False)
    base_reparto = resultado
    if resultado >= 0:
        propuesta = (f"A reservas voluntarias (cuenta 113): {fmt(resultado)}. Propuesta por "
                     "defecto del informe; la aprueba la Junta y el asesor debe confirmarla.")
    else:
        propuesta = (f"Compensación del resultado negativo ({fmt(resultado)}) con reservas "
                     "disponibles o con resultados negativos de ejercicios anteriores. Propuesta "
                     "por defecto del informe: si no hay reservas disponibles, el resultado queda "
                     "pendiente de aplicación.")
    avisos.append("La propuesta de aplicación del resultado la aprueba la Junta General: el "
                  "módulo no la inventa, muestra la base de reparto real y una propuesta por "
                  "defecto que requiere completarse a mano (importe y cuenta de destino).")

    # ---------- Nota 4 · criterios de valoración: lo que sí consta en los apuntes ----------
    correcciones = suma_deudor(s, P_CORRECCIONES_VALOR, recortar=False)
    avisos.append("Las normas de registro y valoración concretas (vida útil y método de "
                  "amortización de cada elemento, valoración de existencias, criterios de "
                  "capitalización) no constan en el ERP: ese texto requiere completarse a mano "
                  "por el asesor, que es quien conoce los criterios aplicados.")

    # ---------- comprobaciones de integridad ----------
    cuadre = comprobar_cuadre(lineas)
    faltan_grupos = grupos_sin_movimiento(s)
    contrarios = saldos_contrarios(s)
    if lineas and abs(cuadre["descuadre"]) > 1:
        avisos.append(f"El libro del ejercicio no cuadra: ΣDebe − ΣHaber = "
                      f"{fmt(cuadre['descuadre'])} en {cuadre['n_lineas']} líneas.")
    if faltan_grupos:
        avisos.append("Los apuntes cargados no tienen ninguna cuenta de: "
                      + ", ".join(faltan_grupos)
                      + ". Las notas que dependen de esos grupos (patrimonio, existencias, "
                        "amortización acumulada…) no se pueden cerrar con el ERP y requieren "
                        "completarse a mano o volver a traer los apuntes.")
    if contrarios:
        primeras = ", ".join(f'{c["cuenta"]} ({fmt(c["saldo"])})' for c in contrarios[:4])
        avisos.append(f"Hay {len(contrarios)} cuentas con el saldo al revés de la naturaleza de "
                      f"su grupo (el informe original las recortaba a cero): {primeras}. Se "
                      "muestran con su signo real.")
    if any(str(c["cuenta"]).startswith("476") for c in contrarios):
        avisos.append("La cuenta 476 (Organismos de la Seguridad Social, acreedores) es un pasivo, "
                      "pero el grupo de deudores heredado del informe original la incluye en el "
                      "activo: aquí se clasifica como deuda en la Nota 7 y se declara la "
                      "diferencia con el informe de Balance y PyG.")
    if existencias == 0 and existencias_ant == 0:
        avisos.append("No hay cuentas de existencias (30x-35x) con movimientos: la Memoria no "
                      "informa de existencias, y las compras del ejercicio van directas a gasto.")

    # ---------- salida ----------
    datos: dict[str, Any] = {
        "year": year, "yearAnterior": year - 1,
        "empresa": ctx.get("empresa") or "",
        "codEmpresa": str(ctx.get("cod_empresa") or ""),
        "nLineas": len(lineas), "nLineasAnterior": len(lineas_ant),
        "primeraFecha": fecha_larga(min((l.fecha for l in lineas if l.fecha), default=0)) if lineas else "—",
        # datos generales (Nota 1)
        "localidad": localidad, "administrador": administrador,
        "fechaFormulacion": fecha_formulacion,
        "fechaCierre": f"31 de diciembre de {year}",
        # PyG (Notas 2 y 4)
        "ventas": _r(ventas), "otrosIngresos": _r(otros_ingresos),
        "totalIngresos": _r(total_ingresos), "aprovisionamientos": _r(aprovisionamientos),
        "gastosPersonal": _r(gastos_personal), "sueldos": _r(sueldos),
        "seguridadSocial": _r(seguridad_social), "indemnizaciones": _r(indemnizaciones),
        "otrosGastos": _r(otros_gastos), "amortizaciones": _r(amortizaciones),
        "ebitda": _r(ebitda), "ebit": _r(ebit),
        "ingresosFinancieros": _r(ingresos_financieros),
        "gastosFinancieros": _r(gastos_financieros),
        "rai": _r(rai), "impuesto": _r(cuota_impuesto), "resultadoNeto": _r(resultado),
        "cashFlow": _r(cash_flow),
        "totalIngresosAnt": _r(ingresos_ant), "raiAnt": _r(rai_ant),
        "ventasAnt": _r(ant["ventas"]), "ebitAnt": _r(ant["ebit"]),
        "ebitdaAnt": _r(ant["ebitda"]), "fondoManiobraAnt": _r(fondo_maniobra_ant),
        "resultadoNetoAnt": _r(resultado_ant),
        "varIngresos": _r(pct(total_ingresos - ingresos_ant, ingresos_ant)),
        "varResultado": _r(pct(resultado - resultado_ant, abs(resultado_ant))),
        # balance (Notas 2, 5, 6 y 7)
        "inmovIntangible": _r(inmov_intangible), "inmovMaterial": _r(inmov_material),
        "inversionesLP": _r(inversiones_lp), "activoNoCorriente": _r(activo_no_corriente),
        "existencias": _r(existencias), "clientes": _r(clientes),
        "otrosDeudores": _r(otros_deudores), "tesoreria": _r(tesoreria),
        "activoCorriente": _r(activo_corriente), "totalActivo": _r(total_activo),
        "capitalSocial": _r(capital), "reservas": _r(reservas), "subvenciones": _r(subvenciones),
        "patrimonioNeto": _r(patrimonio_neto), "deudasLP": _r(deudas_lp),
        "proveedores": _r(proveedores), "deudasCreditoCP": _r(deudas_credito_cp),
        "administracionesPublicas": _r(administraciones),
        "personalPendiente": _r(personal_pendiente),
        "pasivoCorriente": _r(pasivo_corriente), "totalPasivo": _r(total_pasivo),
        "exigible": _r(exigible), "fondoManiobra": _r(fondo_maniobra),
        "totalActivoAnt": _r(activo_no_corriente_ant + activo_corriente_ant),
        "patrimonioNetoAnt": _r(patrimonio_neto_ant),
        "pasivoCorrienteAnt": _r(pasivo_corriente_ant),
        "endeudamiento": _r(pct(exigible, total_activo)),
        # notas
        "inmovilizado": inmovilizado, "totalInmovilizado": total_inmovilizado,
        "amortizacionAcumulada": amortizacion_acumulada,
        "clientesDetalle": clientes_detalle,
        "pasivos": [{"concepto": c, "importe": _r(v), "vencimiento": venc} for c, v, venc in pasivos],
        "vencimientos": [],  # el reparto por años no se puede sacar de los apuntes: ver avisos
        "proveedoresDetalle": proveedores_detalle,
        "fiscal": {
            "ivaRepercutido": _r(iva_repercutido), "ivaSoportado": _r(iva_soportado),
            "saldoIVA": _r(saldo_iva), "retencionesIRPF": _r(retenciones),
            "otrasDeudasFiscales": _r(otras_fiscales), "baseImponible": _r(rai),
            "cuotaImpuestoSociedades": _r(cuota_impuesto),
            "cuotaDiferencial": _r(cuota_diferencial),
        },
        "aplicacionResultado": {
            "baseReparto": _r(base_reparto),
            "resultadoEnLibros": _r(resultado_en_libros), "remanente": _r(remanente),
            "resultadosNegativos": _r(resultados_negativos),
            "reservasDisponibles": _r(reservas_disponibles),
            "aportacionesSocios": _r(aportaciones_socios), "propuesta": propuesta,
        },
        "criterios": {
            "correccionesValor": _r(correcciones),
            "hayCorreccionesValor": abs(correcciones) >= 0.01,
            "hayExistencias": existencias != 0,
        },
        "nota9": nota9, "nota10": nota10, "nota10MedioAmbiente": nota10_medioambiente,
        "integridad": {
            "cuadre": cuadre, "gruposSinMovimiento": faltan_grupos,
            "saldosContrarios": contrarios,
        },
        "avisos": avisos,
    }
    datos["data"] = {k: v for k, v in datos.items() if isinstance(v, (int, float))}
    return datos


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    """KPIs de la Memoria para el panel: las cifras que firma el asesor y lo que falta por hacer."""
    pendientes = sum(1 for a in datos.get("avisos") or []
                     if "a mano" in a)
    return {
        "totalIngresos": datos.get("totalIngresos", 0.0),
        "resultadoNeto": datos.get("resultadoNeto", 0.0),
        "totalActivo": datos.get("totalActivo", 0.0),
        "patrimonioNeto": datos.get("patrimonioNeto", 0.0),
        "inmovilizado": datos.get("totalInmovilizado", 0.0),
        "exigible": datos.get("exigible", 0.0),
        "tesoreria": datos.get("tesoreria", 0.0),
        "impuesto": datos.get("impuesto", 0.0),
        "amortizaciones": datos.get("amortizaciones", 0.0),
        "notasPendientes": pendientes,
        "nAvisos": len(datos.get("avisos") or []),
    }


# ---------------------------------------------------------------- informe

def _seccion_integridad(datos: dict[str, Any]) -> str:
    integridad = datos.get("integridad") or {}
    cuadre = integridad.get("cuadre") or {}
    filas = [
        ["Líneas contables del ejercicio", str(datos.get("nLineas", 0))],
        ["Suma del Debe / del Haber",
         f'{num(cuadre.get("debe", 0))} € / {num(cuadre.get("haber", 0))} €'],
        ["Descuadre del libro", inf.importe(cuadre.get("descuadre", 0), con_signo=True)],
        ["Grupos del balance sin ninguna cuenta",
         ", ".join(integridad.get("gruposSinMovimiento") or []) or "Ninguno"],
    ]
    tabla = inf.tabla(["Comprobación", "Resultado"], filas, anchos=["55%", "45%"])
    contrarios = integridad.get("saldosContrarios") or []
    if contrarios:
        tabla += inf.tabla(
            ["Cuenta con saldo contrario", "Grupo del balance", "Naturaleza del grupo", "Saldo"],
            [[c["cuenta"], c["grupo"], c["naturaleza"], inf.importe(c["saldo"], con_signo=True)]
             for c in contrarios],
            anchos=["28%", "40%", "14%", "18%"])
    return tabla


def informe_html(datos: dict[str, Any], ctx: dict[str, Any] | None = None) -> str:
    """HTML de la Memoria (empieza por `<div`, Arial 11 px, 800 px de ancho)."""
    ctx = dict(ctx or {})
    year = int(ctx.get("year") or datos.get("year") or 0)
    year_ant = year - 1
    empresa = ctx.get("empresa") or datos.get("empresa") or ""
    fiscal = datos.get("fiscal") or {}
    aplicacion = datos.get("aplicacionResultado") or {}
    criterios = datos.get("criterios") or {}
    inmovilizado = datos.get("inmovilizado") or []
    pasivos = datos.get("pasivos") or []

    # ---------- cabecera ----------
    kpis = inf.kpis([
        ("Ingresos de explotación", inf.importe(datos.get("totalIngresos", 0.0))),
        ("Resultado del ejercicio", inf.importe(datos.get("resultadoNeto", 0.0), con_signo=True)),
        ("Total activo", inf.importe(datos.get("totalActivo", 0.0))),
        ("Patrimonio neto", inf.importe(datos.get("patrimonioNeto", 0.0))),
    ])
    cabecera = (
        f'<div style="font-size:11px;color:#5b6b80;padding:2px 4px 6px">'
        f'Cuentas anuales abreviadas del ejercicio <b>{year}</b> (cierre '
        f'{inf.esc(datos.get("fechaCierre", ""))}) · formuladas el '
        f'<b>{inf.esc(datos.get("fechaFormulacion", ""))}</b> en '
        f'<b>{inf.esc(datos.get("localidad", ""))}</b> · apuntes del ERP de los ejercicios {year} y '
        f'{year_ant} ({datos.get("nLineas", 0)} líneas del ejercicio)</div>'
    )

    # ---------- Nota 1 ----------
    filas_actividad = [
        ["Denominación social", empresa or "—"],
        ["Código de empresa en el ERP", datos.get("codEmpresa") or "—"],
        ["Localidad (domicilio social)", datos.get("localidad") or "—"],
        ["Administrador", datos.get("administrador") or "Pendiente de indicar"],
        ["Ejercicio", f"Del 1 de enero al 31 de diciembre de {year}"],
        ["Formulación de las cuentas anuales", datos.get("fechaFormulacion") or "—"],
        ["Importe neto de la cifra de negocios", inf.importe(datos.get("ventas", 0.0))],
        ["Total ingresos de explotación", inf.importe(datos.get("totalIngresos", 0.0))],
        ["Resultado del ejercicio", inf.importe(datos.get("resultadoNeto", 0.0), con_signo=True)],
    ]
    nota1 = (
        inf.tabla(["Datos de la sociedad", f"Ejercicio {year}"], filas_actividad,
                  anchos=["46%", "54%"])
        + f'<div style="font-size:11px;color:#5b6b80;padding:4px 2px">'
        f'La sociedad desarrolla su actividad mercantil con el detalle de ventas, compras y gastos '
        f'que consta en los apuntes del ERP. El objeto social, el CIF y el domicilio completo no '
        f'viajan en los apuntes: los confirma el asesor al firmar la Memoria. Actividad del '
        f'ejercicio según el libro: {datos.get("nLineas", 0)} líneas contables, la primera de '
        f'{inf.esc(datos.get("primeraFecha", "—"))}.</div>'
    )

    # ---------- Nota 2 ----------
    def _comp(actual: float, anterior: float) -> str:
        if not anterior:
            return "—"
        return fmt_pct((actual - anterior) / abs(anterior) * 100)

    filas_comp = [
        ["Importe neto de la cifra de negocios", inf.importe(datos.get("ventasAnt", 0.0)),
         inf.importe(datos.get("ventas", 0.0)),
         _comp(datos.get("ventas", 0.0), datos.get("ventasAnt", 0.0))],
        ["Total ingresos de explotación", inf.importe(datos.get("totalIngresosAnt", 0.0)),
         inf.importe(datos.get("totalIngresos", 0.0)),
         _comp(datos.get("totalIngresos", 0.0), datos.get("totalIngresosAnt", 0.0))],
        ["Resultado de explotación (EBIT)", inf.importe(datos.get("ebitAnt", 0.0), con_signo=True),
         inf.importe(datos.get("ebit", 0.0), con_signo=True),
         _comp(datos.get("ebit", 0.0), datos.get("ebitAnt", 0.0))],
        ["Resultado antes de impuestos", inf.importe(datos.get("raiAnt", 0.0), con_signo=True),
         inf.importe(datos.get("rai", 0.0), con_signo=True),
         _comp(datos.get("rai", 0.0), datos.get("raiAnt", 0.0))],
        ["Resultado del ejercicio", inf.importe(datos.get("resultadoNetoAnt", 0.0), con_signo=True),
         inf.importe(datos.get("resultadoNeto", 0.0), con_signo=True),
         _comp(datos.get("resultadoNeto", 0.0), datos.get("resultadoNetoAnt", 0.0))],
        ["Total activo", inf.importe(datos.get("totalActivoAnt", 0.0)),
         inf.importe(datos.get("totalActivo", 0.0)),
         _comp(datos.get("totalActivo", 0.0), datos.get("totalActivoAnt", 0.0))],
        ["Patrimonio neto", inf.importe(datos.get("patrimonioNetoAnt", 0.0)),
         inf.importe(datos.get("patrimonioNeto", 0.0)),
         _comp(datos.get("patrimonioNeto", 0.0), datos.get("patrimonioNetoAnt", 0.0))],
        ["Pasivo corriente", inf.importe(datos.get("pasivoCorrienteAnt", 0.0)),
         inf.importe(datos.get("pasivoCorriente", 0.0)),
         _comp(datos.get("pasivoCorriente", 0.0), datos.get("pasivoCorrienteAnt", 0.0))],
        ["Fondo de maniobra", inf.importe(datos.get("fondoManiobraAnt", 0.0), con_signo=True),
         inf.importe(datos.get("fondoManiobra", 0.0), con_signo=True),
         _comp(datos.get("fondoManiobra", 0.0), datos.get("fondoManiobraAnt", 0.0))],
    ]
    nota2 = (
        inf.tabla(["Magnitud (euros)", f"Ejercicio {year_ant}", f"Ejercicio {year}", "Variación"],
                  filas_comp, anchos=["40%", "21%", "21%", "18%"])
        + '<div style="font-size:11px;color:#5b6b80;padding:5px 2px">'
        'Las cuentas anuales se formulan aplicando los principios contables y las normas de '
        'valoración del Plan General de Contabilidad de PYMES (RD 1514/2007), con el objetivo de '
        'que muestren la imagen fiel del patrimonio, de la situación financiera y de los '
        'resultados de la sociedad. Se expresan en euros y se presentan con las cifras del '
        f'ejercicio {year} y las del ejercicio anterior ({year_ant}) tomadas de los apuntes de ese '
        'mismo ejercicio, para que las dos columnas sean comparables. No se han cambiado criterios '
        'contables ni corregido errores de ejercicios anteriores según los apuntes cargados.</div>'
        + _seccion_integridad(datos)
    )

    # ---------- Nota 3 ----------
    filas_aplicacion = [
        ["Base de reparto: resultado del ejercicio", inf.importe(aplicacion.get("baseReparto", 0.0), con_signo=True)],
        ["Saldo de la cuenta 129 en los apuntes", inf.importe(aplicacion.get("resultadoEnLibros", 0.0))],
        ["Remanente (120)", inf.importe(aplicacion.get("remanente", 0.0))],
        ["Resultados negativos de ejercicios anteriores (121)",
         inf.importe(aplicacion.get("resultadosNegativos", 0.0))],
        ["Reservas de libre disposición (113-117)", inf.importe(aplicacion.get("reservasDisponibles", 0.0))],
        ["Aportaciones de socios (118)", inf.importe(aplicacion.get("aportacionesSocios", 0.0))],
    ]
    nota3 = (
        inf.tabla(["Aplicación del resultado", f"Ejercicio {year}"], filas_aplicacion,
                  anchos=["62%", "38%"])
        + inf.aviso(str(aplicacion.get("propuesta", "")), tipo="info", titulo="Propuesta por defecto")
        + inf.aviso(
            "La propuesta de distribución del resultado la aprueba la Junta General de socios y no "
            "se puede deducir del ERP: este cuadro requiere completarse a mano (importe, cuenta de "
            "destino y, en su caso, dotación a reserva legal).",
            tipo="alerta", titulo="Pendiente de completar a mano")
    )

    # ---------- Nota 4 ----------
    criterio_existencias = ("Valoradas según las cuentas del grupo 3 del ejercicio."
                            if criterios.get("hayExistencias")
                            else "Sin cuentas de existencias (30x-35x) con movimientos: las compras "
                                 "del ejercicio se registran como gasto.")
    criterio_deterioro = ("Sin asientos de correcciones por deterioro en el ejercicio."
                          if not criterios.get("hayCorreccionesValor")
                          else f'{fmt(criterios.get("correccionesValor", 0.0))} de correcciones por '
                               "deterioro (grupos 29x, 39x, 49x, 59x).")
    criterio_impuesto = ("Sin asiento de Impuesto sobre sociedades (630) en el ejercicio: la cuota "
                         "del IS la aporta el asesor."
                         if abs(fiscal.get("cuotaImpuestoSociedades", 0.0)) < 0.01
                         else f'Cuota registrada en la 630: {fmt(fiscal.get("cuotaImpuestoSociedades", 0.0))}.')
    filas_criterios = [
        ["Inmovilizado intangible", "Valorado por su precio de adquisición (cuentas 20x); "
         "amortización acumulada en la 280."],
        ["Inmovilizado material", "Valorado por su precio de adquisición (cuentas 21x); "
         "amortización acumulada en las 281-282."],
        ["Amortizaciones del ejercicio", inf.importe(datos.get("amortizaciones", 0.0))],
        ["Existencias", criterio_existencias],
        ["Créditos por operaciones comerciales", "Clientes y deudores por su valor nominal "
         f"({fmt(datos.get('clientes', 0.0))} de clientes)."],
        ["Correcciones por deterioro", criterio_deterioro],
        ["Impuesto sobre sociedades", criterio_impuesto],
        ["Deudas", "Por su valor nominal, clasificadas según su vencimiento; las deudas a largo "
         "plazo se traspasan al corto plazo por la parte que vence en el ejercicio."],
    ]
    nota4 = (
        inf.tabla(["Elemento", "Criterio aplicado según los apuntes"], filas_criterios,
                  anchos=["30%", "70%"], alinear="left")
        + inf.aviso(
            "Vida útil, método de amortización de cada elemento, valoración de existencias, "
            "capitalización de gastos y resto de criterios de valoración: son declaraciones del "
            "asesor y no constan en el ERP. Este apartado requiere completarse a mano.",
            tipo="alerta", titulo="Criterios pendientes de completar a mano")
    )

    # ---------- Nota 5 ----------
    filas_inmovilizado = [
        [f["etiqueta"], '<span style="color:#8a95a6">—</span>',
         inf.importe(f["altasEjercicio"]), inf.importe(f["bajasEjercicio"]),
         inf.importe(f["dotacionEjercicio"]),
         inf.importe(-f["amortizacionAcumulada"] or 0.0),
         inf.importe(f["saldoApuntes"])]
        for f in inmovilizado
    ]
    nota5 = (
        inf.tabla(["Tipo de inmovilizado", "Saldo inicial", "Altas del ejercicio",
                   "Bajas del ejercicio", "Dotación del ejercicio", "Amortización acumulada",
                   "Saldo según los apuntes"],
                  filas_inmovilizado,
                  totales=["TOTAL", "", "", "", "", "",
                           inf.importe(datos.get("totalInmovilizado", 0.0))],
                  anchos=["24%", "11%", "13%", "13%", "13%", "13%", "13%"])
        + '<div style="font-size:11px;color:#5b6b80;padding:5px 2px">'
        'Las columnas de altas, bajas y dotación son movimientos reales del ejercicio; la '
        'amortización acumulada es el saldo real de las cuentas 28x y el «saldo según los apuntes» '
        'es el que resulta de esos apuntes. El «Saldo inicial» y el «Saldo final» del cuadro de '
        'inmovilizado del PGC no aparecen porque exigen el asiento de apertura, que no está entre '
        'las líneas cargadas: por eso ese cuadro se completa a mano.</div>'
        + inf.aviso(
            "El cuadro oficial de inmovilizado (saldo inicial y saldo final, valor de las altas y "
            "de las bajas) no se puede obtener de los apuntes cargados: faltan los asientos de "
            "apertura y, en su caso, el desglose del inmovilizado por elementos. Requiere "
            "completarse a mano. El workflow original rellenaba ese cuadro estimando el saldo "
            "inicial con un ×1,2 y una dotación del 20 % sobre el saldo: eran cifras inventadas y "
            "aquí no se reproducen.",
            tipo="alerta", titulo="Cuadro de inmovilizado pendiente (a mano)")
    )

    # ---------- Nota 6 ----------
    filas_deudores = [
        ["Inversiones financieras a largo plazo (25x-26x)", inf.importe(datos.get("inversionesLP", 0.0))],
        ["Clientes y deudores comerciales (43x-44x)", inf.importe(datos.get("clientes", 0.0))],
        ["Otros deudores (46x, 47x, 48x, 567-568)", inf.importe(datos.get("otrosDeudores", 0.0))],
        ["Tesorería (57x)", inf.importe(datos.get("tesoreria", 0.0))],
    ]
    detalle_clientes = datos.get("clientesDetalle") or []
    tabla_clientes = ""
    if detalle_clientes:
        tabla_clientes = '<div style="margin-top:7px">' + inf.tabla(
            ["Subcuenta de cliente con mayor saldo", "Importe", "Líneas"],
            [[c["etiqueta"], inf.importe(c["saldo"]), str(c["n"])] for c in detalle_clientes],
            anchos=["66%", "20%", "14%"]) + "</div>"
    nota6 = (
        inf.tabla(["Activos financieros y deudores", f"Ejercicio {year}"], filas_deudores,
                  totales=["TOTAL", inf.importe(datos.get("activoCorriente", 0.0)
                                                + datos.get("inversionesLP", 0.0))],
                  anchos=["62%", "38%"])
        + tabla_clientes
        + '<div style="font-size:11px;color:#5b6b80;padding:5px 2px">'
        f'Los «otros deudores» incluyen la cuenta 472 (IVA soportado) con '
        f'{fmt(fiscal.get("ivaSoportado", 0.0))}. El detalle de clientes toma el nombre del texto '
        'del asiento, porque el campo «Tercero» llega vacío en los apuntes del ERP. El vencimiento '
        'de cada saldo y la corrección por insolvencias (49x) no constan en los apuntes: esa '
        f'parte de la Nota 6 requiere completarse a mano.</div>'
    )

    # ---------- Nota 7 ----------
    filas_pasivos = [[p["concepto"], inf.importe(p["importe"]), p["vencimiento"]] for p in pasivos]
    def _celda_pendiente() -> str:
        return '<span style="color:#8a95a6">—</span>'

    filas_vencimientos = [
        ["Deudas a largo plazo (15x-17x)", _celda_pendiente(), _celda_pendiente(),
         _celda_pendiente(), _celda_pendiente(), _celda_pendiente(),
         inf.importe(datos.get("deudasLP", 0.0))],
        ["Deudas con entidades de crédito a corto plazo (50x-52x, 55x)",
         inf.importe(datos.get("deudasCreditoCP", 0.0)), _celda_pendiente(), _celda_pendiente(),
         _celda_pendiente(), _celda_pendiente(),
         inf.importe(datos.get("deudasCreditoCP", 0.0))],
        ["Acreedores comerciales y proveedores (40x-41x)",
         inf.importe(datos.get("proveedores", 0.0)), _celda_pendiente(), _celda_pendiente(),
         _celda_pendiente(), _celda_pendiente(), inf.importe(datos.get("proveedores", 0.0))],
    ]
    detalle_proveedores = datos.get("proveedoresDetalle") or []
    tabla_proveedores = ""
    if detalle_proveedores:
        tabla_proveedores = '<div style="margin-top:7px">' + inf.tabla(
            ["Subcuenta de acreedor con mayor saldo", "Importe", "Líneas"],
            [[c["etiqueta"], inf.importe(c["saldo"]), str(c["n"])] for c in detalle_proveedores],
            anchos=["66%", "20%", "14%"]) + "</div>"
    # las cuentas 5xx pueden salir con signo deudor: se dice en la nota, no se recorta a cero
    for p in pasivos:
        if p["concepto"].startswith("Deudas con entidades") and p["importe"] < 0:
            avisos_pasivo = inf.aviso(
                f'Las deudas con entidades de crédito y otras a corto plazo presentan un saldo '
                f'deudor de {fmt(abs(p["importe"]))} (cuentas 50x-52x, 55x): entre las líneas '
                'cargadas los cargos superan a los abonos, así que o el alta del préstamo no está '
                'en el extracto o hay pagos de más. El informe muestra el signo real y no lo '
                'recorta a cero; revisar con el asesor antes de firmar la Nota 7.', tipo="alerta",
                titulo="Saldo deudor en deudas a corto plazo")
            break
    else:
        avisos_pasivo = ""
    nota7 = (
        inf.tabla(["Deudas por naturaleza", f"Importe", "Vencimiento"],
                  filas_pasivos,
                  totales=["TOTAL PASIVO EXIGIBLE", inf.importe(datos.get("exigible", 0.0)), ""],
                  anchos=["56%", "22%", "22%"])
        + avisos_pasivo
        + '<div style="margin-top:9px">' + inf.tabla(
            ["Vencimientos por año", "Año 1", "Año 2", "Año 3", "Año 4", "Año 5 y siguientes", "Total"],
            filas_vencimientos,
            anchos=["30%", "12%", "11%", "11%", "11%", "14%", "11%"]) + "</div>"
        + tabla_proveedores
        + inf.aviso(
            "El reparto de las deudas por año de vencimiento no consta en los apuntes del ERP: no "
            "hay fechas de vencimiento ni cuadros de amortización de los préstamos en el extracto "
            "contable, así que ese cuadro requiere completarse a mano. El workflow original "
            "repartía el saldo de las deudas a largo plazo en cinco tramos idénticos (20 % cada "
            "año): era una estimación inventada y no se reproduce. Sólo se dan los totales reales "
            "por naturaleza y el carácter a corto o largo plazo que sí se deduce del PGC.",
            tipo="alerta", titulo="Cuadro de vencimientos pendiente (a mano)")
    )

    # ---------- Nota 8 ----------
    filas_fiscal = [
        ["IVA repercutido (477)", inf.importe(fiscal.get("ivaRepercutido", 0.0))],
        ["IVA soportado (472)", inf.importe(fiscal.get("ivaSoportado", 0.0))],
        ["Saldo de IVA del ejercicio", inf.importe(fiscal.get("saldoIVA", 0.0), con_signo=True)],
        ["Retenciones e ingresos a cuenta (4751)", inf.importe(fiscal.get("retencionesIRPF", 0.0))],
        ["Otras deudas fiscales (475x sin 4751, 476)", inf.importe(fiscal.get("otrasDeudasFiscales", 0.0))],
        ["Base imponible (resultado antes de impuestos)", inf.importe(fiscal.get("baseImponible", 0.0), con_signo=True)],
        ["Cuota del Impuesto sobre sociedades registrada (630)",
         inf.importe(fiscal.get("cuotaImpuestoSociedades", 0.0))],
        ["Cuota diferencial (cuota registrada − retenciones)",
         inf.importe(fiscal.get("cuotaDiferencial", 0.0), con_signo=True)],
    ]
    nota8 = (
        inf.tabla(["Situación fiscal", f"Ejercicio {year}"], filas_fiscal, anchos=["58%", "42%"])
        + inf.aviso(
            "No hay ningún asiento de Impuesto sobre sociedades (630) en los apuntes del "
            "ejercicio, así que el gasto por impuesto y la cuota diferencial se muestran a cero: "
            "la liquidación real del IS, los pagos fraccionados y las deducciones las aporta el "
            "asesor. El workflow original estimaba la cuota como un 25 % del RAI cuando no "
            "encontraba el asiento; esa estimación se ha eliminado y en su lugar queda este aviso.",
            tipo="alerta", titulo="Impuesto sobre sociedades sin asiento en los apuntes")
        + f'<div style="font-size:11px;color:#5b6b80;padding:5px 2px">'
        f'El saldo de IVA es la diferencia entre el IVA repercutido y el soportado del ejercicio: '
        f'{"a compensar o devolver" if fiscal.get("saldoIVA", 0) < 0 else "a ingresar"}.</div>'
    )

    # ---------- Notas 9 y 10 (texto del asesor) ----------
    def _bloque_manual(texto: str, titulo: str, explicacion: str) -> str:
        if texto:
            return inf.aviso(texto, tipo="info", titulo=titulo)
        return inf.aviso(explicacion, tipo="alerta", titulo=f"{titulo} pendiente (a mano)")

    nota9 = _bloque_manual(
        datos.get("nota9", ""), "Texto aportado por el asesor",
        "La Nota 9 (operaciones con partes vinculadas: operaciones con socios y administradores, "
        "saldos y condiciones) no se puede deducir del ERP: requiere completarse a mano.")
    nota10 = (
        _bloque_manual(
            datos.get("nota10", ""), "Otra información aportada por el asesor",
            "La Nota 10 (otra información: situación de la sociedad, plantilla media, avales y "
            "garantías, hechos posteriores al cierre) no consta en el ERP: requiere completarse a "
            "mano.")
        + _bloque_manual(
            datos.get("nota10MedioAmbiente", ""), "Información medioambiental",
            "La información medioambiental (inversiones, gastos y provisiones de naturaleza "
            "medioambiental, si no hay ninguna, hay que declararlo expresamente) requiere "
            "completarse a mano: los apuntes no traen ninguna cuenta específica.")
    )

    # ---------- avisos ----------
    avisos = datos.get("avisos") or []
    bloque_avisos = "".join(inf.aviso(a, tipo="alerta") for a in avisos)

    cuerpo = (
        kpis + cabecera
        + inf.seccion("Nota 1 · Actividad de la empresa", nota1)
        + inf.seccion("Nota 2 · Bases de presentación de las cuentas anuales", nota2)
        + inf.seccion("Nota 3 · Aplicación de resultados", nota3)
        + inf.seccion("Nota 4 · Normas de registro y valoración", nota4)
        + inf.seccion("Nota 5 · Inmovilizado intangible y material", nota5)
        + inf.seccion("Nota 6 · Activos financieros, clientes y deudores", nota6)
        + inf.seccion("Nota 7 · Pasivos financieros y deudas", nota7)
        + inf.seccion("Nota 8 · Situación fiscal", nota8)
        + inf.seccion("Nota 9 · Operaciones con partes vinculadas", nota9)
        + inf.seccion("Nota 10 · Otra información y medio ambiente", nota10)
        + inf.seccion("Avisos y limitaciones del cálculo", bloque_avisos,
                      nota="Lo que no se puede sacar de los apuntes del ERP queda aquí declarado: "
                           "no se completa con estimaciones.")
    )
    return inf.envoltura(
        titulo=TITULO,
        subtitulo=f"Ejercicio {year} · 10 notas del PGC de PYMES (cuentas abreviadas)",
        empresa=empresa, ejercicio=year, cuerpo=cuerpo,
        ancho=inf.ANCHO_MEMORIA, fuente=inf.FUENTE_MEMORIA,
        meta={"Formulación": datos.get("fechaFormulacion", ""),
              "Localidad": datos.get("localidad", ""),
              "Datos": "ERP apiCON (apuntes del ejercicio y del anterior)"},
    )


__all__ = ["NOMBRE", "TITULO", "INTERNO", "DESPLAZAMIENTOS", "PARAMETROS", "calcular",
           "informe_html", "metricas_dashboard", "grupos_sin_movimiento", "saldos_contrarios",
           "top_cuentas", "movimientos_del_anio", "fecha_larga"]
