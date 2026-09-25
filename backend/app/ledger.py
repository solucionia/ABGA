"""Motor contable determinista: el sustituto en Python de los nodos Code de n8n.

Nada de LLM aquí: todos los números salen de sumas sobre los apuntes. El LLM sólo
se usa (opcionalmente) para redactar la narrativa del informe, nunca para calcular.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


# ---------- formato ----------

def fmt(n: Any) -> str:
    """Importe en formato español: 12.345,67 € (o — si no es número)."""
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        return "—"
    return f"{n:,.2f} €".replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".")


def num(n: Any) -> str:
    """Número sin símbolo de moneda."""
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        return "—"
    return f"{n:,.2f}".replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".")


def fmt_pct(n: Any) -> str:
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        return "—"
    return f"{n:.1f}%".replace(".", ",")


def fecha_a_int(v: Any) -> int:
    """El ERP usa Fecha como entero YYYYMMDD; se tolera ISO por si cambia."""
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    t = str(v or "").strip()
    if not t:
        return 0
    if t.isdigit():
        return int(t)
    limpio = t.replace("-", "").replace("/", "")[:8]
    return int(limpio) if limpio.isdigit() else 0


def mes_de(fecha: Any) -> int:
    f = fecha_a_int(fecha)
    return (f // 100) % 100 if f else 0


def anio_de(fecha: Any) -> int:
    f = fecha_a_int(fecha)
    return f // 10000 if f else 0


def trimestre_de(fecha: Any) -> int:
    m = mes_de(fecha)
    return (m - 1) // 3 + 1 if m else 0


def a_float(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    t = str(v).strip().replace(" ", "")
    if not t or t.lower() in {"none", "null", "-"}:
        return 0.0
    # 1.234,56 -> 1234.56  |  1234.56 -> 1234.56
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return 0.0


# ---------- líneas y saldos ----------

@dataclass
class Linea:
    cuenta: str
    debe: float
    haber: float
    fecha: int
    documento: str = ""
    serie: str = ""
    descripcion: str = ""
    tercero: str = ""
    contrapartida: str = ""
    linea_n: str = ""
    ejercicio: str = ""
    punteo_cuenta: str = ""
    punteo_bancario: str = ""
    crudo: dict = field(default_factory=dict)

    @property
    def importe(self) -> float:
        return self.debe - self.haber


def a_lineas(detalles: Iterable[dict]) -> list[Linea]:
    salida = []
    for d in detalles:
        salida.append(Linea(
            cuenta=str(d.get("Cuenta") or "").strip(),
            debe=a_float(d.get("Debe")),
            haber=a_float(d.get("Haber")),
            fecha=fecha_a_int(d.get("Fecha")),
            documento=str(d.get("Documento") or ""),
            serie=str(d.get("Serie") or ""),
            descripcion=str(d.get("Descripcion") or ""),
            tercero=str(d.get("Tercero") or ""),
            contrapartida=str(d.get("Contrapartida") or ""),
            linea_n=str(d.get("Linea") or ""),
            ejercicio=str(d.get("Ejercicio") or ""),
            punteo_cuenta=str(d.get("PunteoCuenta") or ""),
            punteo_bancario=str(d.get("PunteoBancario") or ""),
            crudo=d,
        ))
    return salida


def lineas_de_asientos(asientos: Iterable[dict]) -> list[Linea]:
    detalles: list[dict] = []
    for a in asientos or []:
        for d in a.get("Detalles") or []:
            if not d.get("Fecha"):
                d = {**d, "Fecha": a.get("Fecha"), "Documento": d.get("Documento") or a.get("Documento"),
                     "Serie": d.get("Serie") or a.get("Serie"), "Ejercicio": d.get("Ejercicio") or a.get("Ejercicio")}
            detalles.append(d)
    return a_lineas(detalles)


@dataclass
class Saldo:
    debe: float = 0.0
    haber: float = 0.0
    n: int = 0

    @property
    def deudor(self) -> float:
        return self.debe - self.haber

    @property
    def acreedor(self) -> float:
        return self.haber - self.debe


def saldos_por_cuenta(lineas: Iterable[Linea]) -> dict[str, Saldo]:
    mapa: dict[str, Saldo] = defaultdict(Saldo)
    for l in lineas:
        s = mapa[l.cuenta]
        s.debe += l.debe
        s.haber += l.haber
        s.n += 1
    return dict(mapa)


def suma_deudor(saldos: dict[str, Saldo], prefijos: Sequence[str], *, recortar: bool = True) -> float:
    """Σ(Debe−Haber) de las cuentas que empiezan por alguno de los prefijos.

    `recortar=False` devuelve el saldo real, que puede ser negativo (los informes
    actuales usaban Math.max(0, …) y ocultaban los saldos contrarios).
    """
    total = 0.0
    for cuenta, s in saldos.items():
        if any(cuenta.startswith(p) for p in prefijos):
            total += s.deudor
    return max(0.0, total) if recortar else total


def suma_acreedor(saldos: dict[str, Saldo], prefijos: Sequence[str], *, recortar: bool = True) -> float:
    total = 0.0
    for cuenta, s in saldos.items():
        if any(cuenta.startswith(p) for p in prefijos):
            total += s.acreedor
    return max(0.0, total) if recortar else total


def saldo_cuenta(saldos: dict[str, Saldo], prefijo: str, *, recortar: bool = False) -> float:
    return suma_deudor(saldos, [prefijo], recortar=recortar)


# ---------- agrupaciones ----------

def por_mes(lineas: Iterable[Linea]) -> dict[int, list[Linea]]:
    mapa: dict[int, list[Linea]] = defaultdict(list)
    for l in lineas:
        mapa[mes_de(l.fecha)].append(l)
    return dict(mapa)


def por_trimestre(lineas: Iterable[Linea]) -> dict[int, list[Linea]]:
    mapa: dict[int, list[Linea]] = defaultdict(list)
    for l in lineas:
        mapa[trimestre_de(l.fecha)].append(l)
    return dict(mapa)


def serie_mensual(lineas: Iterable[Linea], prefijos_ingreso: Sequence[str],
                  prefijos_gasto: Sequence[str]) -> list[dict[str, Any]]:
    """12 filas (una por mes) con ingresos, gastos y resultado: alimenta las gráficas."""
    filas = []
    por_m = por_mes(lineas)
    for m in range(1, 13):
        saldos = saldos_por_cuenta(por_m.get(m, []))
        ing = suma_acreedor(saldos, prefijos_ingreso)
        gas = suma_deudor(saldos, prefijos_gasto)
        filas.append({
            "mes": MESES[m - 1], "mes_num": m,
            "ingresos": round(ing, 2), "gastos": round(gas, 2), "resultado": round(ing - gas, 2),
            "n_lineas": len(por_m.get(m, [])),
        })
    return filas


def agrupar_por_cuenta(lineas: Iterable[Linea], *, nivel: int = 3) -> list[dict[str, Any]]:
    """Saldos agregados por prefijo de cuenta (nivel 2-4 dígitos), para desgloses."""
    mapa: dict[str, Saldo] = defaultdict(Saldo)
    for l in lineas:
        clave = l.cuenta[:nivel] if len(l.cuenta) >= nivel else l.cuenta
        s = mapa[clave]
        s.debe += l.debe
        s.haber += l.haber
        s.n += 1
    filas = [{"cuenta": c, "debe": round(s.debe, 2), "haber": round(s.haber, 2),
              "saldo": round(s.deudor, 2), "n": s.n} for c, s in mapa.items()]
    return sorted(filas, key=lambda f: f["cuenta"])


def nombre_tercero(tercero: Any, descripcion: Any = "", *, largo: int = 44) -> str:
    """Nombre del tercero a partir de lo que da el ERP.

    En los datos reales de ABGA el campo `Tercero` viene **vacío** y el nombre viaja al final
    de la descripción del apunte, detrás del último guion:
    `ED/2025/00001-MARÍA SERRA CAÑELLAS`, `OP/2025/00005-Avintia Proyectos Y Construcciones S.L.`
    Sin normalizar esto, cada factura parece un tercero distinto y los listados de clientes y
    proveedores se llenan de ruido.
    """
    t = str(tercero or "").strip()
    if t and t.lower() not in {"none", "null", "-"}:
        return t[:largo]
    d = str(descripcion or "").strip()
    if not d:
        return "(sin identificar)"
    parte = d.rsplit("-", 1)[-1].strip() if "-" in d else d
    return (parte or d)[:largo]


def por_tercero(lineas: Iterable[Linea], prefijos: Sequence[str], *, normalizar: bool = True) -> list[dict[str, Any]]:
    mapa: dict[str, Saldo] = defaultdict(Saldo)
    for l in lineas:
        if any(l.cuenta.startswith(p) for p in prefijos):
            clave = nombre_tercero(l.tercero, l.descripcion) if normalizar else (l.tercero or l.descripcion[:40])
            s = mapa[clave or "(sin tercero)"]
            s.debe += l.debe
            s.haber += l.haber
            s.n += 1
    filas = [{"tercero": t, "debe": round(s.debe, 2), "haber": round(s.haber, 2),
              "saldo": round(s.deudor, 2), "n": s.n} for t, s in mapa.items()]
    return sorted(filas, key=lambda f: -abs(f["saldo"]))


def detectar_cierre(lineas: Iterable[Linea]) -> dict[str, Any]:
    """Detecta el cierre del ejercicio y devuelve las líneas operativas.

    En un ejercicio **cerrado** el ERP devuelve, además de los apuntes, dos asientos que no son
    actividad: el de *regularización* («Pérdidas y Ganancias»), que deja a cero las cuentas de
    gasto e ingreso (6xx/7xx) contra la 129, y el de *cierre* del balance. Sumarlos como si
    fueran actividad hace que un ejercicio cerrado dé **resultado 0** en todos los paneles: el
    panel se veía vacío sin decir por qué.

    El criterio es estricto para no llevarse por delante asientos legítimos del cierre del año:
    sólo se consideran asientos **fechados el 31/12** que toquen la cuenta 129; se distinguen por
    si además tocan cuentas de gasto o ingreso. Así no se confunden con el asiento de apertura
    (01/01), con la aplicación del resultado del año anterior (enero) ni con una regularización
    de existencias (610/612), que no toca la 129.
    """
    grupos: dict[tuple[str, str], list[Linea]] = defaultdict(list)
    for l in lineas:
        grupos[(l.serie, l.documento)].append(l)

    regularizacion: set[tuple[str, str]] = set()
    cierre_balance: set[tuple[str, str]] = set()
    resultado_libro = 0.0
    for clave, ls in grupos.items():
        if not ls or fecha_a_int(ls[0].fecha) % 10000 != 1231:  # sólo el 31/12
            continue
        if not any(l.cuenta.startswith("129") for l in ls):
            continue
        if any(l.cuenta.startswith(("6", "7")) for l in ls):
            regularizacion.add(clave)
            resultado_libro += sum(l.haber - l.debe for l in ls if l.cuenta.startswith("129"))
        else:
            cierre_balance.add(clave)

    fuera = regularizacion | cierre_balance
    operativas = [l for l in lineas if (l.serie, l.documento) not in fuera]
    return {
        "cerrado": bool(regularizacion),
        "asientos_regularizacion": sorted(regularizacion),
        "asientos_cierre": sorted(cierre_balance),
        "resultado_libro": round(resultado_libro, 2),
        "lineas_operativas": operativas,
        "n_lineas_fuera": len(list(lineas)) - len(operativas),
    }


def comprobar_cuadre(lineas: Iterable[Linea]) -> dict[str, Any]:
    """El libro debe cuadrar: ΣDebe == ΣHaber. Sirve de test de integridad."""
    debe = sum(l.debe for l in lineas)
    haber = sum(l.haber for l in lineas)
    return {"debe": round(debe, 2), "haber": round(haber, 2),
            "descuadre": round(debe - haber, 2), "n_lineas": len(list(lineas)) if not isinstance(lineas, list) else len(lineas)}


# ---------- series comparativas ----------

def serie_interanual(por_ejercicio: dict[int, list[Linea]], funcion_metrica,
                     anios: Sequence[int]) -> list[dict[str, Any]]:
    """Aplica una métrica a cada ejercicio y devuelve la serie lista para graficar."""
    filas = []
    for a in anios:
        saldos = saldos_por_cuenta(por_ejercicio.get(a, []))
        filas.append({"year": a, **funcion_metrica(saldos)})
    return filas
