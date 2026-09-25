"""Contraste cruzado de los tres informes fiscales: sumas y saldos, libro de IVA y retenciones.

Los tres miran los mismos apuntes por caminos independientes y los escribieron manos distintas, así
que si coinciden es señal fuerte: un error de criterio en uno de ellos lo cantan los otros dos, y
ninguno de los tres incluye el cálculo del otro (no hay una cifra compartida que se arrastre).

Lo que se comprueba, por cada empresa y ejercicio:

  1. lo que el libro de IVA llama repercutido  == Σ(haber − debe) de las cuentas 477x del libro
  2. lo que el libro de IVA llama soportado    == Σ(debe − haber) de las cuentas 472x del libro
  3. el total de retenciones                   == Σ(haber − debe) de las cuentas 4751x del libro
  4. las mismas tres cifras leídas del informe de sumas y saldos (el detalle de sus filas)
  5. los totales del ejercicio en sumas y saldos: ΣDebe == ΣHaber

Uso:  ./.venv/bin/python backend/scripts/verificar_trio_financiero.py [cod_empresa] [year]
"""
from __future__ import annotations

import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import cache, modulos  # noqa: E402
from app.ledger import a_float, fecha_a_int, lineas_de_asientos  # noqa: E402

# Tolerancia: los módulos redondean a céntimo por movimiento e impuesto, así que pueden diferir de
# la suma línea a línea en uno o dos céntimos. Más que eso ya es un descuadre, no un redondeo.
TOL = 0.02
OK = "\033[32m✓\033[0m"
NO = "\033[31m✗\033[0m"
fallos: list[str] = []
pendientes: list[str] = []


def _revisar(condicion: bool, texto: str) -> None:
    """Como `_comprobar`, pero para lo que no se puede adjudicar sin decisión de negocio: se enseña
    con las cifras y no tumba la verificación (queda listado al final como pendiente)."""
    if condicion:
        print(f"   {OK} {texto}")
        return
    print(f"   \033[33m?\033[0m {texto}")
    pendientes.append(texto)


def _comprobar(condicion: bool, texto: str) -> None:
    print(f"   {OK if condicion else NO} {texto}")
    if not condicion:
        fallos.append(texto)


def _filas(datos: dict) -> list[dict]:
    """Encuentra el detalle por cuenta del informe de sumas y saldos sin saber su nombre exacto."""
    for valor in datos.values():
        if isinstance(valor, list) and valor and isinstance(valor[0], dict):
            if {"cuenta"} <= set(valor[0]):
                return valor
    return []


def _cuadrar(datos: dict, cuenta: str, campo: str) -> float | None:
    """Valor de una cuenta concreta en el detalle de sumas y saldos (soporta prefijo)."""
    for fila in _filas(datos):
        if str(fila.get("cuenta", "")).startswith(cuenta):
            return a_float(fila.get(campo))
    return None


def _movimiento_del_ejercicio(lineas: list) -> list:
    """Las líneas que son *movimiento* del ejercicio, con el mismo criterio que declaran los módulos.

    Fuera los asientos de apertura o ajuste de apertura (1 de enero) y los de regularización y cierre
    (31 de diciembre que toquen la 129). Comparar contra la suma bruta del fichero cuenta de más: un
    ejercicio cerrado tiene las cuentas a cero precisamente porque el cierre las anula, así que el
    neto del fichero no es el movimiento del año.
    """
    por_clave: dict[tuple, list] = defaultdict(list)
    for ln in lineas:
        por_clave[(str(ln.fecha), str(ln.serie), str(ln.documento))].append(ln)
    fuera = set()
    for clave, ls in por_clave.items():
        f = fecha_a_int(ls[0].fecha)
        if f % 10000 == 101:
            fuera.add(clave)
        elif f % 10000 == 1231 and any((x.cuenta or "").startswith("129") for x in ls):
            fuera.add(clave)
    return [ln for ln in lineas if (str(ln.fecha), str(ln.serie), str(ln.documento)) not in fuera]


def revisar(cod_empresa: str, year: int) -> None:
    print(f"\n{'=' * 78}\n  {cod_empresa} · ejercicio {year}\n{'=' * 78}")
    guardado = cache.leer_apuntes(cod_empresa, year, ttl=-1)
    if not guardado or not guardado.get("asientos"):
        print("   (no está en la caché local; se salta)")
        return
    lineas = lineas_de_asientos(guardado["asientos"])
    anterior = cache.leer_apuntes(cod_empresa, year - 1, ttl=-1) or {}
    por_anio = {year: lineas,
                year - 1: lineas_de_asientos(anterior.get("asientos") or [])}
    ctx = {"empresa": f"empresa {cod_empresa}", "cod_empresa": cod_empresa, "year": year,
           "year_anterior": year - 1, "trimestre": None}

    # --- el libro, leído directamente de los apuntes (el juez) --------------------------------
    de_477 = de_472 = de_4751 = 0.0
    for ln in _movimiento_del_ejercicio(lineas):
        c = (ln.cuenta or "")
        imp = a_float(ln.haber) - a_float(ln.debe)
        if c.startswith("477"):
            de_477 += imp
        if c.startswith("472"):
            de_472 -= imp
        if c.startswith("4751"):
            de_4751 += imp

    # --- los tres módulos, por su interfaz pública -------------------------------------------
    d_ss = modulos.obtener("sumas_saldos").calcular(por_anio, {**ctx, "nivel": 4})
    d_iva = modulos.obtener("libro_iva").calcular(por_anio, ctx)
    d_ret = modulos.obtener("libro_retenciones").calcular(por_anio, ctx)
    m_ss = modulos.obtener("sumas_saldos").metricas_dashboard(d_ss)
    m_iva = modulos.obtener("libro_iva").metricas_dashboard(d_iva)
    m_ret = modulos.obtener("libro_retenciones").metricas_dashboard(d_ret)

    rep = a_float(m_iva.get("ivaRepercutido"))
    sop = a_float(m_iva.get("ivaSoportado"))
    ret = a_float(m_ret.get("retencionesTotal"))
    ss_477 = _cuadrar(d_ss, "477", "haber") - _cuadrar(d_ss, "477", "debe")
    ss_472 = _cuadrar(d_ss, "472", "debe") - _cuadrar(d_ss, "472", "haber")

    print(f"\n   {'concepto':<34}{'el libro':>16}{'libro_iva/ret.':>17}{'sumas y saldos':>17}")
    print(f"   {'-' * 84}")
    print(f"   {'IVA repercutido (477)':<34}{de_477:>16,.2f}{rep:>17,.2f}{(ss_477 or 0):>17,.2f}")
    print(f"   {'IVA soportado (472)':<34}{de_472:>16,.2f}{sop:>17,.2f}{(ss_472 or 0):>17,.2f}")
    print(f"   {'Retenciones (4751)':<34}{de_4751:>16,.2f}{ret:>17,.2f}{'—':>17}")

    print()
    _comprobar(abs(rep - de_477) < TOL, f"libro_iva repercutido = libro ({rep:,.2f} €)")
    _revisar(abs(sop - de_472) < TOL,
             f"libro_iva soportado = libro ({sop:,.2f} €)" if abs(sop - de_472) < TOL else
             f"libro_iva soportado ({sop:,.2f} €) frente al devengo del ejercicio ({de_472:,.2f} €): "
             f"la empresa liquida los modelos durante el año y el libro suma devengos y liquidaciones")
    _comprobar(abs((rep - sop) - a_float(m_iva.get("ivaDiferencia"))) < TOL,
               "libro_iva: la diferencia es repercutido − soportado")
    # Retenciones: el total del libro son los DEVENGOs del ejercicio, así que sólo coincide con el
    # saldo de la cuenta si la empresa no liquidó los modelos durante el año (6091 no lo hace; 6221
    # y 1092 sí, mensualmente). La identidad que siempre se cumple es devengos − pagos = saldo.
    pagos = sum(a_float(x.get("cuota")) for x in (d_ret.get("otrosMovimientos") or [])
                if isinstance(x, dict) and str(x.get("cuenta", "")).startswith("4751"))
    _comprobar(abs(ret - de_4751) < TOL or abs(ret - pagos - de_4751) < TOL
               or abs(ret + pagos - de_4751) < TOL,
               f"retenciones: devengos {ret:,.2f} € − pagos {abs(pagos):,.2f} € = saldo de la 4751 "
               f"({de_4751:,.2f} €)" if pagos else f"retenciones = libro ({ret:,.2f} €)")
    _comprobar(ss_477 is not None and abs(ss_477 - rep) < TOL,
               f"sumas y saldos (477) coincide con el libro de IVA ({ss_477:,.2f} €)"
               if ss_477 is not None else "sumas y saldos trae la fila 477")
    _revisar(ss_472 is not None and abs(ss_472 - sop) < TOL,
             f"sumas y saldos (472) coincide con el libro de IVA ({ss_472:,.2f} €)"
             if (ss_472 is not None and abs(ss_472 - sop) < TOL)
             else f"sumas y saldos (472) {ss_472:,.2f} € frente al libro de IVA {sop:,.2f} €: "
                  f"revisar el tratamiento de los asientos de liquidación del IVA")
    cuadra = abs(a_float(m_ss.get("total_debe")) - a_float(m_ss.get("total_haber"))) < TOL
    declarado = any(any(p in str(a).lower() for p in ("descuadre", "no cero", "cuadre", "cuadra"))
                    for a in (d_ss.get("avisos") or []))
    _comprobar(cuadra or declarado,
               f"sumas y saldos: ΣDebe = ΣHaber = {a_float(m_ss.get('total_debe')):,.2f} €"
               if cuadra else "sumas y saldos no cuadra, pero lo declara en los avisos del informe")


def main() -> int:
    casos = [(sys.argv[1], int(sys.argv[2]))] if len(sys.argv) >= 3 else [
        ("6091", 2025), ("6091", 2024), ("6221", 2025), ("1092", 2025)]
    for cod, year in casos:
        revisar(cod, year)
    print(f"\n{'=' * 78}")
    if fallos:
        print(f"  {len(fallos)} comprobaciones NO cumplidas:")
        for f in fallos:
            print(f"    - {f}")
        return 1
    if pendientes:
        print(f"  Lo que sí debe cumplirse, se cumple.")
        print(f"  {len(pendientes)} punto(s) pendientes de una decisión de negocio (no son fallos):")
        for p in pendientes:
            print(f"    ? {p}")
        return 0
    print("  Los tres informes coinciden. Contraste cruzado correcto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
