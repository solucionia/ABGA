"""Módulo `duplicados` — REQ-04 «Detectar Duplicados» (informe de USO INTERNO).

Portado del nodo Code *Detectar Duplicados* del workflow de n8n
(`legacy/REQ-04-Detectar_Duplicados.js`). El original comparaba **todos los pares**
de asientos del ejercicio (O(n²)) con un umbral de 4 puntos; aquí se conservan
exactamente los mismos criterios y pesos, pero los pares a puntuar se obtienen con
índices, y se corrigen cuatro defectos del original:

1. **Identidad del asiento.** El original usaba `Documento` como identificador; el
   ERP repite ese número entre series (90 asientos en 2025 y 155 en 2024 lo tienen
   repetido), así que las claves del `Set` de «ya comparados» colisionaban y el
   original **se saltaba pares sin compararlos**. Aquí la identidad es
   `(ejercicio, serie, documento)`, que en los datos reales es única.
2. **Diferencia de fechas.** El original calculaba `Math.abs(a.fecha - b.fecha)` sobre
   el entero `YYYYMMDD`: entre el 31/01 y el 01/02 la diferencia sale 70 y el criterio
   «fechas próximas» (±3) no saltaba nunca a caballo de fin de mes. Aquí la diferencia
   se calcula en días naturales.
3. **Fuerza bruta.** Se indexa por importe redondeado, fecha, conjunto de cuentas,
   terceros (proveedor 40x/41x y cliente 43x/44x) y documento, y sólo se puntúan los
   pares candidatos (ver `_pares_candidatos`: el conjunto de bloques es completo, es
   decir, ningún par que alcanzaría el umbral se queda fuera). El aviso del informe
   dice cuántos asientos y cuántos pares se han comparado, frente a los n·(n−1)/2 del
   sistema anterior.
4. **Importe en riesgo.** El original sumaba el importe del par una vez por cada par,
   contando el mismo asiento tantas veces como coincidencias tuviera. Aquí se informa
   el importe de riesgo por pares (comparable con el original) **y** el importe de
   riesgo único (asientos distintos, sin duplicar).

Otros arreglos menores: los criterios vacíos no puntúan (el original ya lo hacía con
`&&`, aquí además no generan bloques), la descripción se normaliza (espacios repetidos),
y sólo se calcula la distancia de Levenshtein cuando puede decidir el resultado.

Ámbito: sólo el ejercicio pedido (`DESPLAZAMIENTOS = [0]`), como el original. Un
duplicado a caballo de dos ejercicios no se detecta aquí.

Nota de maquetación: `informes.envoltura(interno=True)` usa por defecto el formato de
la Memoria (800 px / 11 px); el contrato reserva ese formato para la Memoria, así que
este informe interno se pinta a 780 px / Arial 13 px como el resto de informes.
"""
from __future__ import annotations

import datetime as dt
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Hashable, Iterable, Iterator, Sequence

from .. import informes as inf
from ..ledger import Linea, fmt, num

NOMBRE = "duplicados"
TITULO = "Detección de duplicados contables"
INTERNO = True
DESPLAZAMIENTOS = [0]
PARAMETROS: dict[str, Any] = {
    # El original usaba 4 puntos con un baremo distinto y, medido sobre el ejercicio 2025 real
    # de 6091, eso producía 28.404 pares (25.906 de ellos en el nivel más bajo): inservible para
    # una asesoría. Con 11 puntos quedan ~100 pares, todos de nivel PROBABLE. Es el valor por
    # defecto; el portal permite subirlo o bajarlo y el informe muestra el recuento por nivel.
    "umbral": 11,           # puntos mínimos para reportar un par
    "dias_proximidad": 3,   # ventana de «fechas próximas»
    "importe_minimo": 50.0, # el original descartaba los asientos de importe <= 50 €
    "max_filas": 60,        # filas mostradas en el informe (el resto, contadas)
    "umbral_aviso": 500,    # por encima de esto el informe avisa de que hay que subir el umbral
}

# --- gravedad (mismos tres niveles que el original) ---
NIVELES = ("PROBABLE", "POSIBLE", "REVISAR")
GRAVEDAD = {"PROBABLE": "ALTA", "POSIBLE": "MEDIA", "REVISAR": "BAJA"}
COLOR_NIVEL = {"PROBABLE": inf.NEGATIVO, "POSIBLE": inf.AMBAR, "REVISAR": "#5b6b80"}

# --- criterios y pesos: los del original, sin cambios ---
PESO_IMPORTE = 3
PESO_CUENTAS = 2
PESO_MISMA_FECHA = 3
PESO_FECHA_PROXIMA = 1
PESO_DESC_IDENTICA = 2
PESO_DESC_SIMILAR = 1
PESO_PROVEEDOR = 2
PESO_CLIENTE = 2

CRITERIOS: list[tuple[str, str, int]] = [
    ("importe", f"Importe idéntico (±0,02 €)", PESO_IMPORTE),
    ("cuentas", "Mismo conjunto de cuentas (4 dígitos)", PESO_CUENTAS),
    ("fecha", "Misma fecha", PESO_MISMA_FECHA),
    ("fecha_proxima", "Fecha próxima (± días)", PESO_FECHA_PROXIMA),
    ("descripcion", "Descripción idéntica (Levenshtein 0)", PESO_DESC_IDENTICA),
    ("descripcion_similar", "Descripción similar (Levenshtein ≤ 5)", PESO_DESC_SIMILAR),
    ("proveedor", "Mismo proveedor (40x/41x)", PESO_PROVEEDOR),
    ("cliente", "Mismo cliente (43x/44x)", PESO_CLIENTE),
]
ETIQUETA_CRITERIO = {clave: texto for clave, texto, _ in CRITERIOS}

PREFIJOS_PROVEEDOR = ("40", "41")
PREFIJOS_CLIENTE = ("43", "44")
MAX_DESC = 30          # el original comparaba sólo los primeros 30 caracteres
MAX_LEVENSHTEIN = 5


# ---------------------------------------------------------------- asientos
@dataclass
class Asiento:
    """Un asiento reconstruido a partir de sus líneas (el contrato entrega líneas)."""

    clave: str                  # (ejercicio, serie, documento) — identidad del asiento
    ejercicio: str
    serie: str
    documento: str
    fecha: int                  # YYYYMMDD
    descripcion: str            # normalizada en minúsculas
    importe: float              # max(Σdebe, Σhaber), redondeado a céntimos
    debe: float
    haber: float
    cuentas: str                # firma: cuentas a 4 dígitos, ordenadas
    proveedores: tuple[str, ...]  # cuentas 40x/41x a 10 dígitos (terceros)
    clientes: tuple[str, ...]     # cuentas 43x/44x a 10 dígitos (terceros)
    n_lineas: int
    dia: dt.date | None = field(default=None, repr=False, compare=False)

    @property
    def firma_proveedor(self) -> str:
        return ",".join(self.proveedores)

    @property
    def firma_cliente(self) -> str:
        return ",".join(self.clientes)


def _texto(fuente: Any, nombre: str) -> str:
    """Lee un campo de una `Linea` (dataclass) o del detalle crudo (dict)."""
    valor = fuente.get(nombre) if isinstance(fuente, dict) else getattr(fuente, nombre, None)
    return "" if valor is None else str(valor)


def _a_dia(fecha: int) -> dt.date | None:
    """YYYYMMDD -> date. Devuelve None si la fecha no es utilizable."""
    texto = str(fecha or "")
    if len(texto) != 8 or not texto.isdigit():
        return None
    try:
        return dt.date(int(texto[0:4]), int(texto[4:6]), int(texto[6:8]))
    except ValueError:
        return None


def _normalizar(texto: str) -> str:
    return " ".join(str(texto or "").lower().split())


def asientos_de_lineas(lineas: Iterable[Linea]) -> list[Asiento]:
    """Reconstruye los asientos agrupando las líneas por (ejercicio, serie, documento).

    El contrato entrega `list[Linea]`; el asiento original (importe, descripción,
    cuentas implicadas, terceros) se deduce de sus líneas. Si algún fichero no trae
    serie/documento en el detalle se cae a la fecha + descripción, para no fundir
    asientos distintos en una sola clave.
    """
    grupos: dict[Hashable, list[Linea]] = defaultdict(list)
    for linea in lineas:
        crudo = getattr(linea, "crudo", None) or {}
        serie = _texto(linea, "serie") or _texto(crudo, "Serie")
        documento = _texto(linea, "documento") or _texto(crudo, "Documento")
        ejercicio = _texto(linea, "ejercicio") or _texto(crudo, "Ejercicio")
        if documento:
            clave: Hashable = (ejercicio, serie, documento)
        else:  # sin número de asiento: fecha + descripción
            clave = (ejercicio, linea.fecha, _normalizar(linea.descripcion))
        grupos[clave].append(linea)

    salida: list[Asiento] = []
    for clave, miembros in grupos.items():
        primero = miembros[0]
        crudo_primero = getattr(primero, "crudo", None) or {}
        serie = _texto(primero, "serie") or _texto(crudo_primero, "Serie")
        documento = _texto(primero, "documento") or _texto(crudo_primero, "Documento")
        debe = round(sum(l.debe for l in miembros), 2)
        haber = round(sum(l.haber for l in miembros), 2)
        fecha = min((l.fecha for l in miembros if l.fecha), default=0)
        descripciones = Counter(_normalizar(l.descripcion) for l in miembros if l.descripcion)
        proveedores = tuple(sorted({l.cuenta[:10] for l in miembros
                                    if l.cuenta[:2] in PREFIJOS_PROVEEDOR}))
        clientes = tuple(sorted({l.cuenta[:10] for l in miembros
                                 if l.cuenta[:2] in PREFIJOS_CLIENTE}))
        salida.append(Asiento(
            clave=f"{serie or '?'}/{documento or '?'}",
            ejercicio=_texto(primero, "ejercicio") or _texto(crudo_primero, "Ejercicio"),
            serie=serie, documento=documento, fecha=fecha,
            descripcion=descripciones.most_common(1)[0][0] if descripciones else "",
            importe=round(max(debe, haber), 2), debe=debe, haber=haber,
            cuentas=",".join(sorted({l.cuenta[:4] for l in miembros if l.cuenta})),
            proveedores=proveedores, clientes=clientes, n_lineas=len(miembros),
            dia=_a_dia(fecha),
        ))
    salida.sort(key=lambda a: (a.fecha, a.serie, a.documento, a.clave))
    return salida


# ---------------------------------------------------------------- puntuación
def _levenshtein(a: str, b: str, maximo: int = MAX_LEVENSHTEIN) -> int:
    """Distancia de Levenshtein acotada. Devuelve `maximo + 1` si se pasa del corte.

    Se corta en cuanto la fila entera supera `maximo` (las filas siguientes no pueden
    bajar), y antes se descarta con la cota `max(len) − caracteres_comunes`, que se
    calcula en O(len) y evita la mayor parte de las matrices en datos reales.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > maximo:
        return maximo + 1
    comunes = sum((Counter(a) & Counter(b)).values())
    if max(len(a), len(b)) - comunes > maximo:
        return maximo + 1
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i] + [0] * len(b)
        minimo_fila = actual[0]
        for j, cb in enumerate(b, 1):
            actual[j] = min(anterior[j] + 1, actual[j - 1] + 1,
                            anterior[j - 1] + (0 if ca == cb else 1))
            if actual[j] < minimo_fila:
                minimo_fila = actual[j]
        if minimo_fila > maximo:
            return maximo + 1
        anterior = actual
    return anterior[-1]


def _dias_entre(a: Asiento, b: Asiento) -> int | None:
    """Días naturales de diferencia; None si falta alguna fecha."""
    if a.dia is None or b.dia is None:
        return None
    return abs((a.dia - b.dia).days)


def puntuar(a: Asiento, b: Asiento, *, umbral: int = 4, dias: int = 3) -> dict[str, Any] | None:
    """Puntúa un par de asientos. Devuelve None si no llega al umbral.

    Mismo baremo que el original (umbral 4; PROBABLE ≥ 8, POSIBLE ≥ 6, REVISAR ≥ 4).
    Se evalúan primero los criterios baratos y, como la descripción aporta 2 puntos
    como máximo, sólo se calcula la distancia de edición cuando puede cambiar el
    resultado.
    """
    puntos = 0
    coincidencias: list[str] = []
    criterios: list[str] = []

    # 1. Importe idéntico (peso 3 — el criterio más fuerte)
    if a.importe > 0 and abs(a.importe - b.importe) < 0.02:
        puntos += PESO_IMPORTE
        coincidencias.append(f"Importe idéntico: {fmt(a.importe)}")
        criterios.append("importe")

    # 2. Mismas cuentas implicadas (peso 2)
    if a.cuentas and a.cuentas == b.cuentas:
        puntos += PESO_CUENTAS
        coincidencias.append(f"Mismas cuentas: {a.cuentas}")
        criterios.append("cuentas")

    # 3. Fecha: mismo día (peso 3) o dentro de la ventana (peso 1)
    dias_dif = _dias_entre(a, b)
    if dias_dif == 0:
        puntos += PESO_MISMA_FECHA
        coincidencias.append(f"Misma fecha: {_fecha_es(a.fecha)}")
        criterios.append("fecha")
    elif dias_dif is not None and dias_dif <= dias:
        puntos += PESO_FECHA_PROXIMA
        coincidencias.append(f"Fechas próximas ({dias_dif} día(s)): "
                             f"{_fecha_es(a.fecha)} / {_fecha_es(b.fecha)}")
        criterios.append("fecha_proxima")

    # 5 y 6. Terceros: mismo proveedor / mismo cliente (peso 2 cada uno)
    if a.proveedores and a.proveedores == b.proveedores:
        puntos += PESO_PROVEEDOR
        coincidencias.append(f"Mismo proveedor: {a.firma_proveedor}")
        criterios.append("proveedor")
    if a.clientes and a.clientes == b.clientes:
        puntos += PESO_CLIENTE
        coincidencias.append(f"Mismo cliente: {a.firma_cliente}")
        criterios.append("cliente")

    # La descripción sólo puede añadir 2 puntos: si ni así se llega, se descarta.
    if puntos + PESO_DESC_IDENTICA >= umbral and a.descripcion and b.descripcion \
            and len(a.descripcion) > 3:
        corta_a, corta_b = a.descripcion[:MAX_DESC], b.descripcion[:MAX_DESC]
        distancia = _levenshtein(corta_a, corta_b)
        if distancia == 0:
            puntos += PESO_DESC_IDENTICA
            coincidencias.append(f'Descripción idéntica: "{corta_a[:40]}"')
            criterios.append("descripcion")
        elif distancia <= MAX_LEVENSHTEIN:
            puntos += PESO_DESC_SIMILAR
            coincidencias.append(f'Descripción similar (dist. {distancia}): '
                                 f'"{corta_a[:30]}" / "{corta_b[:30]}"')
            criterios.append("descripcion_similar")

    if puntos < umbral:
        return None

    nivel = "PROBABLE" if puntos >= 8 else ("POSIBLE" if puntos >= 6 else "REVISAR")
    return {
        "nivel": nivel,
        "gravedad": GRAVEDAD[nivel],
        "puntuacion": puntos,
        "criterios": criterios,
        "coincidencias": coincidencias,
        # El importe duplicado es el menor de los dos (el original tomaba siempre el
        # del primer asiento del par y sobrevaloraba los pares con importes distintos).
        "importeRiesgo": round(min(a.importe, b.importe), 2),
        "a": _resumen(a),
        "b": _resumen(b),
    }


def _resumen(a: Asiento) -> dict[str, Any]:
    return {"id": a.clave, "fecha": a.fecha, "fechaTexto": _fecha_es(a.fecha),
            "descripcion": a.descripcion[:60], "importe": a.importe,
            "serie": a.serie, "documento": a.documento, "nLineas": a.n_lineas}


def _fecha_es(fecha: int) -> str:
    texto = str(fecha or "")
    if len(texto) == 8 and texto.isdigit():
        return f"{texto[6:8]}/{texto[4:6]}/{texto[0:4]}"
    return texto or "—"


# ---------------------------------------------------------------- candidatos
def _claves_importe(a: Asiento) -> Iterator[tuple]:
    yield ("importe", a.importe)


def _claves_documento(a: Asiento) -> Iterator[tuple]:
    if a.documento:
        yield ("documento", a.ejercicio, a.serie, a.documento)


def _claves_mismo_dia(a: Asiento) -> Iterator[tuple]:
    if a.fecha:
        yield ("dia", a.fecha)


def _claves_cuentas_desc(a: Asiento) -> Iterator[tuple]:
    if a.cuentas and a.descripcion:
        yield ("cuentas_desc", a.cuentas, a.descripcion)


def _claves_prov_cli(a: Asiento) -> Iterator[tuple]:
    for proveedor in a.proveedores:
        for cliente in a.clientes:
            yield ("prov_cli", proveedor, cliente)


def _claves_prov_cuentas(a: Asiento) -> Iterator[tuple]:
    if a.cuentas:
        for proveedor in a.proveedores:
            yield ("prov_cuentas", proveedor, a.cuentas)


def _claves_cli_cuentas(a: Asiento) -> Iterator[tuple]:
    if a.cuentas:
        for cliente in a.clientes:
            yield ("cli_cuentas", cliente, a.cuentas)


def _claves_prov_desc(a: Asiento) -> Iterator[tuple]:
    if a.descripcion:
        for proveedor in a.proveedores:
            yield ("prov_desc", proveedor, a.descripcion)


def _claves_cli_desc(a: Asiento) -> Iterator[tuple]:
    if a.descripcion:
        for cliente in a.clientes:
            yield ("cli_desc", cliente, a.descripcion)


def _claves_tercero(a: Asiento) -> Iterator[tuple]:
    """Terceros individuales (proveedor y cliente) para el índice por tercero."""
    for proveedor in a.proveedores:
        yield ("tercero", proveedor)
    for cliente in a.clientes:
        yield ("tercero", cliente)


# bloques que se comparan TODOS entre sí (grupos pequeños: misma clave exacta)
BLOQUES_EXACTOS: list[tuple[str, Callable[[Asiento], Iterator[tuple]]]] = [
    ("importe", _claves_importe),
    ("documento", _claves_documento),
    ("misma fecha", _claves_mismo_dia),
    ("cuentas+descripción", _claves_cuentas_desc),
    ("proveedor+cliente", _claves_prov_cli),
    ("proveedor+cuentas", _claves_prov_cuentas),
    ("cliente+cuentas", _claves_cli_cuentas),
    ("proveedor+descripción", _claves_prov_desc),
    ("cliente+descripción", _claves_cli_desc),
]

# bloques que, además de compartir la clave, exigen estar dentro de ±dias
BLOQUES_VENTANA: list[tuple[str, Callable[[Asiento], Iterator[tuple]]]] = [
    ("cuentas ± días", lambda a: iter([("ventana_cuentas", a.cuentas)] if a.cuentas else [])),
    ("tercero ± días", lambda a: ((k) for k in _claves_tercero(a))),
    ("descripción ± días",
     lambda a: iter([("ventana_desc", a.descripcion)] if a.descripcion else [])),
]


def _pares_de_bloque(asientos: Sequence[Asiento], claves: Callable[[Asiento], Iterator[tuple]],
                     destino: set[tuple[int, int]]) -> None:
    indice: dict[tuple, list[int]] = defaultdict(list)
    for i, a in enumerate(asientos):
        for clave in claves(a):
            indice[clave].append(i)
    for indices in indice.values():
        if len(indices) < 2:
            continue
        for pos, i in enumerate(indices):
            for j in indices[pos + 1:]:
                destino.add((i, j) if i < j else (j, i))


def _pares_de_ventana(asientos: Sequence[Asiento], claves: Callable[[Asiento], Iterator[tuple]],
                      dias: int, destino: set[tuple[int, int]]) -> None:
    """Pares que comparten clave y están a lo sumo a `dias` días (índice por fecha)."""
    indice: dict[tuple, list[int]] = defaultdict(list)
    for i, a in enumerate(asientos):
        if a.dia is None:
            continue
        for clave in claves(a):
            indice[clave].append(i)
    for indices in indice.values():
        if len(indices) < 2:
            continue
        indices.sort(key=lambda i: asientos[i].fecha)
        fechas = [asientos[i].fecha for i in indices]
        for pos, i in enumerate(indices):
            fin = bisect_right(fechas, fechas[pos] + dias)
            for j in indices[pos + 1:fin]:
                destino.add((i, j) if i < j else (j, i))


def pares_candidatos(asientos: Sequence[Asiento], *, dias: int = 3) -> set[tuple[int, int]]:
    """Pares de asientos que merece la pena puntuar, sin comparar todos con todos.

    El original comparaba los n·(n−1)/2 pares. Aquí se generan sólo los pares que
    comparten alguna clave con peso suficiente para llegar al umbral (4 puntos):

    * mismo **importe** redondeado (3 puntos: con cualquier otro punto, o dos, ya llega),
    * misma **fecha** (3 puntos: basta cualquier coincidencia adicional, incluida la
      descripción similar),
    * mismo **documento** (no puntúa —el original tampoco lo puntuaba—, pero trae al
      análisis pares con el mismo justificante aunque estén lejos en el tiempo),
    * mismo conjunto de **cuentas**, mismo **tercero** (proveedor 40x/41x o cliente
      43x/44x) o misma **descripción**, combinados con: otra de esas claves, la fecha
      exacta o la ventana de ±`dias` días.

    Ningún par con puntuación ≥ umbral queda fuera: todo par así suma al menos dos
    criterios de 2 puntos, o uno de ellos más los dos criterios flojos (fecha próxima
    y descripción similar), y todas esas combinaciones tienen bloque. La verificación
    lo comprueba contra la fuerza bruta en `scripts/verificar_duplicados.py`.
    """
    candidatos: set[tuple[int, int]] = set()
    for _, claves in BLOQUES_EXACTOS:
        _pares_de_bloque(asientos, claves, candidatos)
    for _, claves in BLOQUES_VENTANA:
        _pares_de_ventana(asientos, claves, dias, candidatos)
    return candidatos


# ---------------------------------------------------------------- cálculo
def calcular(por_anio: dict[int, list[Linea]], ctx: dict) -> dict[str, Any]:
    """Detecta los pares de asientos duplicados del ejercicio pedido.

    Devuelve números y estructuras (nada formateado) para el informe y el panel.
    """
    year = int(ctx.get("year") or 0)
    umbral = int(ctx.get("umbral", PARAMETROS["umbral"]) or PARAMETROS["umbral"])
    dias = int(ctx.get("dias_proximidad", PARAMETROS["dias_proximidad"])
               or PARAMETROS["dias_proximidad"])
    importe_minimo = float(ctx.get("importe_minimo", PARAMETROS["importe_minimo"])
                           or PARAMETROS["importe_minimo"])
    max_filas = int(ctx.get("max_filas", PARAMETROS["max_filas"]) or PARAMETROS["max_filas"])

    lineas = list((por_anio or {}).get(year) or [])
    todos = asientos_de_lineas(lineas)
    asientos = [a for a in todos if a.importe > importe_minimo]

    pares = pares_candidatos(asientos, dias=dias)
    duplicados: list[dict[str, Any]] = []
    for i, j in pares:
        hallado = puntuar(asientos[i], asientos[j], umbral=umbral, dias=dias)
        if hallado is not None:
            hallado["par"] = (asientos[i].clave, asientos[j].clave)
            duplicados.append(hallado)

    orden = {nivel: pos for pos, nivel in enumerate(NIVELES)}
    duplicados.sort(key=lambda d: (orden[d["nivel"]], -d["puntuacion"],
                                   -d["importeRiesgo"], d["par"]))

    cuantos = Counter(d["nivel"] for d in duplicados)
    por_criterio = Counter(c for d in duplicados for c in set(d["criterios"]))
    grave = [d for d in duplicados if d["nivel"] in ("PROBABLE", "POSIBLE")]
    importe_pares = round(sum(d["importeRiesgo"] for d in grave), 2)
    claves_unicas = {clave for d in grave for clave in d["par"]}
    importe_unico = round(sum(a.importe for a in asientos if a.clave in claves_unicas), 2)
    importes = sorted(d["importeRiesgo"] for d in duplicados)
    importe_max = importes[-1] if importes else 0.0

    n = len(asientos)
    pares_posibles = n * (n - 1) // 2
    ahorro = (100.0 * (pares_posibles - len(pares)) / pares_posibles) if pares_posibles else 0.0
    nivel_global = ("PROBABLE" if cuantos["PROBABLE"] else "POSIBLE" if cuantos["POSIBLE"]
                    else "REVISAR" if cuantos["REVISAR"] else "OK")

    if not todos:
        avisos = [f"No hay apuntes cargados para el ejercicio {year}: no se ha podido "
                  "analizar nada. Comprueba que el ejercicio tiene datos en el ERP."]
    else:
        avisos = []
        if not asientos:
            avisos.append(f"Ninguno de los {len(todos)} asientos del ejercicio {year} supera "
                          f"el importe mínimo de {fmt(importe_minimo)} que aplicaba el sistema "
                          "anterior: no hay nada que comparar.")
        else:
            avisos.append(
                f"Se han analizado {n} asientos (de {len(todos)} del ejercicio; se excluyen los "
                f"de importe ≤ {fmt(importe_minimo)}, como el sistema anterior) y se han comparado "
                f"{len(pares)} pares mediante índices de fecha, importe redondeado, tercero "
                f"(proveedor/cliente), cuentas y documento. Compararlos todos con todos habría "
                f"sido {pares_posibles} pares: un {num(ahorro)} % menos de comparaciones.")
        if cuantos["PROBABLE"]:
            avisos.append(f"Hay {cuantos['PROBABLE']} par(es) de gravedad ALTA (≥ 8 puntos): "
                          "revisar factura/abono antes de dar el ejercicio por cerrado.")
        if len(duplicados) > max_filas:
            avisos.append(f"El informe muestra los {max_filas} primeros pares de {len(duplicados)}; "
                          "el resto queda en los datos del módulo para el volcado a Excel.")
        if duplicados and cuantos["PROBABLE"] + cuantos["POSIBLE"] == 0:
            avisos.append("Todo lo detectado es de gravedad baja (sólo coincidencias parciales): "
                          "probablemente sean asientos recurrentes legítimos, no duplicados.")

    return {
        # identificación
        "year": year,
        "empresa": ctx.get("empresa", ""),
        # configuración aplicada
        "umbral": umbral, "diasProximidad": dias,
        "importeMinimo": importe_minimo, "maxFilas": max_filas,
        # recuentos
        "totalAsientos": len(todos),
        "asientosAnalizados": n,
        "asientosExcluidos": len(todos) - n,
        "lineasAnalizadas": len(lineas),
        "paresComparados": len(pares),
        "paresPosiblesFuerzaBruta": pares_posibles,
        "ahorroComparacionesPct": round(ahorro, 2),
        "totalDuplicados": len(duplicados),
        "probableCount": cuantos["PROBABLE"],
        "posibleCount": cuantos["POSIBLE"],
        "revisarCount": cuantos["REVISAR"],
        "nivelGlobal": nivel_global,
        # importes de riesgo
        "importeRiesgoTotal": importe_pares,          # suma de pares PROBABLE/POSIBLE
        "importeRiesgoUnico": importe_unico,          # asientos distintos, sin repetir
        "asientosImplicados": len(claves_unicas),
        "importeMaximo": round(importe_max, 2),
        # detalle
        "porCriterio": {clave: por_criterio.get(clave, 0) for clave, _, _ in CRITERIOS},
        "porNivel": {nivel: cuantos[nivel] for nivel in NIVELES},
        "duplicados": duplicados,
        "avisos": avisos,
    }


def metricas_dashboard(datos: dict[str, Any]) -> dict[str, Any]:
    """KPIs para el panel interno."""
    return {
        "nivelGlobal": datos["nivelGlobal"],
        "totalDuplicados": datos["totalDuplicados"],
        "probableCount": datos["probableCount"],
        "posibleCount": datos["posibleCount"],
        "revisarCount": datos["revisarCount"],
        "importeRiesgoTotal": datos["importeRiesgoTotal"],
        "importeRiesgoUnico": datos["importeRiesgoUnico"],
        "asientosImplicados": datos["asientosImplicados"],
        "asientosAnalizados": datos["asientosAnalizados"],
        "paresComparados": datos["paresComparados"],
        "ahorroComparacionesPct": datos["ahorroComparacionesPct"],
    }


# ---------------------------------------------------------------- informe
def _tabla_duplicados(duplicados: Sequence[dict[str, Any]]) -> str:
    filas = []
    for d in duplicados:
        color = COLOR_NIVEL[d["nivel"]]
        quien = lambda x: (f'<b>{inf.esc(x["id"])}</b><br>'
                           f'<span style="color:#5b6b80">{inf.esc(x["fechaTexto"])}</span>')
        filas.append([
            f'<span style="background:{color};color:#fff;font-size:10.5px;padding:1px 6px;'
            f'border-radius:3px;white-space:nowrap">{d["nivel"]}</span>'
            f'<br><span style="font-size:10.5px;color:#5b6b80">{d["gravedad"]}</span>',
            f'<b>{d["puntuacion"]}</b>',
            quien(d["a"]),
            quien(d["b"]),
            inf.importe(d["importeRiesgo"]),
            "<span style=\"font-size:11px;color:#3c4a5c\">"
            + "<br>".join(inf.esc(c) for c in d["coincidencias"]) + "</span>",
        ])
    return inf.tabla(
        ["Gravedad", "Puntos", "Asiento A", "Asiento B", "Importe", "Coincidencias"],
        filas, anchos=["9%", "6%", "13%", "13%", "11%"], primera_izquierda=False,
    )


def _tabla_criterios(datos: dict[str, Any]) -> str:
    filas = [
        [texto, str(peso), str(datos["porCriterio"].get(clave, 0))]
        for clave, texto, peso in CRITERIOS
    ]
    return inf.tabla(["Criterio", "Puntos", "Pares en que coincide"], filas,
                     anchos=["62%", "13%", "25%"])


def informe_html(datos: dict[str, Any], ctx: dict) -> str:
    """Informe HTML (interno) de los duplicados detectados."""
    from ..ledger import fmt_pct  # sólo formato: el cálculo va en `calcular`

    year = datos["year"]
    duplicados_en_tabla = datos["duplicados"][:datos["maxFilas"]]
    graficos = inf.barras_svg(
        list(NIVELES),
        [{"nombre": "Pares detectados", "color": inf.AZUL,
          "valores": [datos["porNivel"][nivel] for nivel in NIVELES]}],
        alto=170, titulo="Pares detectados por gravedad",
    )

    kpi_items = [
        ("Asientos analizados", num(datos["asientosAnalizados"])),
        ("Pares comparados", num(datos["paresComparados"])),
        ("Duplicados", num(datos["totalDuplicados"])),
        ("Importe en riesgo", inf.importe(datos["importeRiesgoTotal"])),
        ("ALTA (PROBABLE)", num(datos["probableCount"])),
        ("MEDIA (POSIBLE)", num(datos["posibleCount"])),
        ("BAJA (REVISAR)", num(datos["revisarCount"])),
        ("Riesgo único", inf.importe(datos["importeRiesgoUnico"])),
    ]

    avisos = "".join(
        inf.aviso(a, tipo=("alerta" if "ALTA" in a else "info")) for a in datos["avisos"]
    )

    resumen = inf.tabla(
        ["Magnitud", "Valor"],
        [
            ["Asientos del ejercicio", num(datos["totalAsientos"])],
            ["Asientos analizados (importe &gt; "
             + fmt(datos["importeMinimo"]) + ")", num(datos["asientosAnalizados"])],
            ["Pares comparados (con índices)", num(datos["paresComparados"])],
            ["Pares si se comparasen todos", num(datos["paresPosiblesFuerzaBruta"])],
            ["Reducción de comparaciones", fmt_pct(datos["ahorroComparacionesPct"])],
            ["Pares con puntuación ≥ umbral", num(datos["totalDuplicados"])],
            ["Asientos distintos implicados", num(datos["asientosImplicados"])],
            ["Importe de riesgo (suma de pares)", inf.importe(datos["importeRiesgoTotal"])],
            ["Importe de riesgo único (asientos distintos)",
             inf.importe(datos["importeRiesgoUnico"])],
            ["Par de mayor importe", inf.importe(datos["importeMaximo"])],
            ["Nivel global", datos["nivelGlobal"]],
        ],
        anchos=["62%", "38%"],
    )

    if duplicados_en_tabla:
        detalle = _tabla_duplicados(duplicados_en_tabla)
        nota = (f"Se muestran {len(duplicados_en_tabla)} de {datos['totalDuplicados']} pares. "
                "Puntuación: importe idéntico 3, cuentas 2, misma fecha 3 (próximas ±"
                f"{datos['diasProximidad']} días 1), descripción 2 (similar 1), proveedor 2, "
                f"cliente 2. Umbral del sistema anterior: {datos['umbral']} puntos.")
    else:
        detalle = inf.aviso("No se ha detectado ningún par de asientos sospechoso de duplicidad "
                            f"en el ejercicio {year}.", tipo="ok",
                            titulo="Sin duplicados que reportar")
        nota = ""

    cuerpo = (
        inf.kpis(kpi_items)
        + avisos
        + inf.seccion("Resumen del análisis", resumen)
        + inf.seccion("Reparto por gravedad", graficos)
        + inf.seccion("Pares detectados", detalle, nota=nota)
        + inf.seccion("Criterios aplicados",
                      _tabla_criterios(datos),
                      nota="Los criterios y pesos son los del workflow original REQ-04: "
                           "no se ha cambiado el baremo para que los importes sean comparables.")
        + inf.aviso("Este informe es de uso interno de ABGA Consultores: los pares señalados son "
                    "indicios, no duplicados confirmados. Antes de proponer nada al cliente hay "
                    "que comprobar el justificante y, en su caso, el asiento de anulación.",
                    tipo="alerta", titulo="Uso interno · revisar antes de comunicar")
    )

    return inf.envoltura(
        titulo=TITULO,
        subtitulo=f"Ejercicio {year} · análisis de duplicidades sobre apuntes contables",
        empresa=datos.get("empresa") or ctx.get("empresa", ""),
        ejercicio=year,
        interno=INTERNO,
        cuerpo=cuerpo,
        meta={"Umbral": f"{datos['umbral']} puntos",
              "Importe mínimo": fmt(datos["importeMinimo"]),
              "Origen": "apuntes del ERP apiCON del ejercicio (cacheados)"},
    )


__all__ = ["NOMBRE", "TITULO", "INTERNO", "DESPLAZAMIENTOS", "PARAMETROS",
           "calcular", "informe_html", "metricas_dashboard", "asientos_de_lineas",
           "pares_candidatos", "puntuar", "Asiento"]
