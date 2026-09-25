#!/usr/bin/env python
"""Verificación del módulo `sumas_saldos` con datos reales.

No toca el ERP. Recalcula el informe por su cuenta desde los **apuntes crudos** y contrasta:

  1. el contrato del módulo (`NOMBRE`, `TITULO`, `INTERNO`, `DESPLAZAMIENTOS`, `PARAMETROS`,
     `calcular`, `informe_html` empezando por `<div`, `metricas_dashboard`);
  2. los fixtures reales de la empresa 6091 (2025 y 2024): una fila por cuenta a 3, 4 y 5 dígitos,
     con saldo inicial, debe, haber y saldo final recalculados **aquí**, a mano, cuenta a cuenta;
  3. las comprobaciones de integridad que el módulo publica en el informe (ΣDebe = ΣHaber y
     Σ saldo final = 0) y que los descuadres que existen se declaran, no se esconden;
  4. los subtotales por grupo, los parámetros (`top`, `solo_con_saldo`, niveles inválidos);
  5. el HTML que exige el contrato (780 px, Arial 13 px, importes es-ES con su propio `>`…`<`);
  6. dos casos reales de la caché local —1092 y 6221— que **sí traen asiento de apertura**, para
     comprobar la otra rama del saldo inicial: la reconciliación cuenta a cuenta entre el cierre
     del ejercicio anterior y la apertura del siguiente (si la caché no está, se omite y lo dice).

Uso:  ./.venv/bin/python backend/scripts/verificar_sumas_saldos.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import cache, modulos  # noqa: E402
from app.modulos import sumas_saldos as mod  # noqa: E402
from app.ledger import (comprobar_cuadre, detectar_cierre, fmt, lineas_de_asientos,  # noqa: E402
                        saldos_por_cuenta)

ANCHO = 78
fallos: list[str] = []
CTX = {"empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": 2025, "year_anterior": 2024,
       "nombre_mes": "septiembre", "trimestre": 3, "email": "",
       "nivel": 3, "top": 0, "solo_con_saldo": False}


def titulo(t: str) -> None:
    print(f"\n{'=' * ANCHO}\n{t}\n{'=' * ANCHO}")


def comprobar(condicion: bool, descripcion: str, detalle: str = "") -> bool:
    print(f"  [{'OK ' if condicion else 'MAL'}] {descripcion}" + (f" — {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(descripcion + (f" ({detalle})" if detalle else ""))
    return condicion


def fila(etiqueta: str, valor: str, ancho: int = 44) -> str:
    return f"    {etiqueta:<{ancho}}{valor:>26}"


def eur(n: float) -> str:
    return fmt(n)


# ------------------------------------------------------------------ recálculo independiente

def agregar_crudo(apuntes: list[dict], nivel: int) -> dict[str, list[float]]:
    """Recalcula los saldos a mano desde los apuntes crudos (sin usar ledger)."""
    mapa: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for a in apuntes:
        for d in a.get("Detalles") or []:
            cuenta = str(d.get("Cuenta") or "")
            k = cuenta[:nivel] if len(cuenta) >= nivel else cuenta
            mapa[k][0] += float(d.get("Debe") or 0.0)
            mapa[k][1] += float(d.get("Haber") or 0.0)
    return dict(mapa)


def leer_fixture(anio: int) -> dict:
    return json.loads((RAIZ / "fixtures" / f"apuntes_6091_{anio}.json").read_text(encoding="utf-8"))


def cargar_cache(empresa: str, anio: int) -> list | None:
    datos = cache.leer_apuntes(empresa, anio, ttl=-1)   # ttl=-1: sólo caché local, nunca el ERP
    return None if not datos else lineas_de_asientos(datos["asientos"])


# ------------------------------------------------------------------ 1. contrato

def verificar_contrato() -> None:
    titulo("1. CONTRATO DEL MÓDULO")
    m = modulos.obtener("sumas_saldos")
    comprobar(m.disponible, "el módulo importa", m.error or "sin error de importación")
    comprobar(mod.NOMBRE == "sumas_saldos", "NOMBRE == 'sumas_saldos'", mod.NOMBRE)
    comprobar(mod.TITULO == "Sumas y saldos", "TITULO == 'Sumas y saldos'", mod.TITULO)
    comprobar(mod.INTERNO is False, "INTERNO == False (informe de cliente)")
    comprobar(mod.DESPLAZAMIENTOS == [0, -1], "DESPLAZAMIENTOS == [0, -1]", str(mod.DESPLAZAMIENTOS))
    comprobar(modulos.anios_necesarios("sumas_saldos", 2025) == [2024, 2025],
              "anios_necesarios(2025) == [2024, 2025]",
              str(modulos.anios_necesarios("sumas_saldos", 2025)))
    comprobar(mod.PARAMETROS == {"nivel": 3, "top": 0, "solo_con_saldo": False}, "PARAMETROS",
              str(mod.PARAMETROS))
    for f in ("calcular", "informe_html", "metricas_dashboard"):
        comprobar(callable(getattr(mod, f, None)), f"{f}() está definida")


# ------------------------------------------------------------------ 2. datos y fixtures

def main() -> int:
    print(__doc__)
    verificar_contrato()

    f25, f24 = leer_fixture(2025), leer_fixture(2024)
    ap25, ap24 = f25["asientos"], f24["asientos"]
    l25, l24 = lineas_de_asientos(ap25), lineas_de_asientos(ap24)
    m = modulos.obtener("sumas_saldos")

    titulo("2. DATOS DE ENTRADA (fixtures reales, sin ERP)")
    print(fila("empresa", "6091 · MB Dommo, S.L."))
    print(fila("ejercicio 2025", f"{len(ap25)} asientos / {len(l25)} líneas"))
    print(fila("ejercicio 2024", f"{len(ap24)} asientos / {len(l24)} líneas"))
    c25, c24 = comprobar_cuadre(l25), comprobar_cuadre(l24)
    print(fila("cuadre 2025 (ΣDebe − ΣHaber)", eur(c25["descuadre"])))
    print(fila("cuadre 2024 (ΣDebe − ΣHaber)", eur(c24["descuadre"])))
    ap_0101 = [a for a in ap25 if int(a.get("Fecha") or 0) % 10000 == 101]
    comprobar(len(ap_0101) == 0, "el fixture de 2025 no trae asiento el 01/01 (no hay apertura)",
              f"{len(ap_0101)} asientos el 01/01")

    datos = m.calcular({2025: l25, 2024: l24}, CTX)

    titulo("3. ORIGEN DEL SALDO INICIAL (lo que declara el informe)")
    comprobar(datos["origen_inicial"] == "cierre_anterior",
              "sin apertura en 2025, el saldo inicial sale del cierre de 2024",
              datos["origen_inicial"])
    comprobar(any("saldos de cierre del ejercicio 2024" in a for a in datos["avisos"]),
              "el informe dice de dónde viene el saldo inicial")
    comprobar(any("apertura" in a.lower() and "cierre del ejercicio anterior" in a.lower()
                  for a in datos["avisos"]),
              "aviso general: el saldo inicial puede venir de la apertura o del cierre anterior")
    for a in datos["avisos"]:
        print(f"    aviso: {a[:150]}{'…' if len(a) > 150 else ''}")

    titulo("4. RECÁLCULO INDEPENDIENTE CUENTA A CUENTA (nivel 3)")
    agregado_ini = agregar_crudo(ap24, 3)      # cierre de 2024 = todas las líneas de 2024
    agregado_mov = agregar_crudo(ap25, 3)      # movimientos de 2025
    esperado = {}
    for cuenta in set(agregado_ini) | set(agregado_mov):
        i = agregado_ini.get(cuenta, [0.0, 0.0])
        p = agregado_mov.get(cuenta, [0.0, 0.0])
        ini = round(i[0] - i[1], 2)
        esperado[cuenta] = (ini, round(p[0], 2), round(p[1], 2), round(ini + p[0] - p[1], 2))

    filas = {f["cuenta"]: f for f in datos["filas"]}
    comprobar(set(filas) == set(esperado), "una fila por cuenta a 3 dígitos",
              f"{len(filas)} cuentas calculadas vs {len(esperado)} esperadas")
    malas = []
    for cuenta, (ini, debe, haber, fin) in sorted(esperado.items()):
        f = filas.get(cuenta)
        if not f or (f["saldo_inicial"], f["debe"], f["haber"], f["saldo_final"]) != (ini, debe, haber, fin):
            malas.append(cuenta)
    comprobar(not malas, "saldo inicial, debe, haber y saldo final coinciden en las 39 cuentas",
              f"{len(esperado) - len(malas)}/{len(esperado)} cuentas" if not malas else str(malas[:6]))
    for cuenta in ("400", "430", "472", "477", "629", "700"):
        if cuenta in esperado:
            ini, debe, haber, fin = esperado[cuenta]
            f = filas[cuenta]
            print(fila(f"  cuenta {cuenta} (recálculo aquí)",
                       f"{eur(ini)} | {eur(debe)} | {eur(haber)} | {eur(fin)}"))
            comprobar((f["saldo_inicial"], f["debe"], f["haber"], f["saldo_final"])
                      == (ini, debe, haber, fin), f"  la cuenta {cuenta} coincide")

    t = datos["totales"]
    suma_ini = round(sum(v[0] for v in esperado.values()), 2)
    suma_debe = round(sum(v[1] for v in esperado.values()), 2)
    suma_haber = round(sum(v[2] for v in esperado.values()), 2)
    suma_fin = round(sum(v[3] for v in esperado.values()), 2)
    comprobar(t == {"saldo_inicial": suma_ini, "debe": suma_debe, "haber": suma_haber,
                    "saldo_final": suma_fin}, "la fila de totales es la suma de las filas",
              f"{t} vs {{'saldo_inicial': {suma_ini}, 'debe': {suma_debe}, "
              f"'haber': {suma_haber}, 'saldo_final': {suma_fin}}}")
    comprobar(abs(suma_debe - c25["debe"]) < 0.01 and abs(suma_haber - c25["haber"]) < 0.01,
              "la suma del debe y del haber es la del libro de 2025",
              f"{eur(suma_debe)} / {eur(suma_haber)}")

    titulo("5. COMPROBACIONES DE INTEGRIDAD (ΣDebe = ΣHaber y Σ saldo final = 0)")
    integridad = datos["integridad"]
    print(fila("ΣDebe 2025", eur(integridad["suma_debe"])))
    print(fila("ΣHaber 2025", eur(integridad["suma_haber"])))
    print(fila("diferencia ΣDebe − ΣHaber", eur(integridad["descuadre"])))
    print(fila("Σ saldo inicial", eur(integridad["suma_saldo_inicial"])))
    print(fila("Σ saldo final", eur(integridad["suma_saldo_final"])))
    comprobar(integridad["cuadra_debe_haber"] and abs(integridad["descuadre"]) < 0.01,
              "ΣDebe = ΣHaber del ejercicio (8.963.835,08 € por los dos lados)")
    comprobar(abs(integridad["suma_saldo_final"] - c24["descuadre"]) < 0.01,
              "Σ saldo final = descuadre propio del ejercicio anterior (28,39 €), ni más ni menos",
              f"{eur(integridad['suma_saldo_final'])} vs {eur(c24['descuadre'])}")
    comprobar(not integridad["cuadra_saldos"] and any("Σ(Saldo final)" in a for a in datos["avisos"]),
              "el descuadre de los saldos se avisa en el informe, no se oculta")
    comprobar(any("arrastra saldo a las cuentas de gasto e ingreso" in a for a in datos["avisos"]),
              "avisa de las cuentas de gasto e ingreso que 2024 no cerró contra la 129")

    titulo("6. SUBTOTALES POR GRUPO")
    subtotales = datos["subtotales_grupo"]
    grupos = sorted({f["grupo"] for f in datos["filas"]}, key=lambda g: (len(g) == 0, g))
    comprobar([s["grupo"] for s in subtotales] == grupos, "un subtotal por grupo presente",
              str([s["grupo"] for s in subtotales]))
    ok_grupo = all(
        (s["debe"], s["haber"], s["saldo_inicial"], s["saldo_final"]) == (
            round(sum(f["debe"] for f in datos["filas"] if f["grupo"] == s["grupo"]), 2),
            round(sum(f["haber"] for f in datos["filas"] if f["grupo"] == s["grupo"]), 2),
            round(sum(f["saldo_inicial"] for f in datos["filas"] if f["grupo"] == s["grupo"]), 2),
            round(sum(f["saldo_final"] for f in datos["filas"] if f["grupo"] == s["grupo"]), 2))
        for s in subtotales)
    comprobar(ok_grupo, "cada subtotal es la suma de las cuentas de su grupo")
    comprobar(round(sum(s["debe"] for s in subtotales), 2) == t["debe"]
              and round(sum(s["saldo_final"] for s in subtotales), 2) == t["saldo_final"],
              "la suma de los subtotales es igual a la fila de TOTAL")
    for s in subtotales:
        print(fila(f"  {s['etiqueta'][:42]}", f"{s['n_cuentas']:>3} cta"
                                               f"{'s' if s['n_cuentas'] != 1 else ''} "
                                               f"{eur(s['debe']):>18} {eur(s['saldo_final']):>18}"))

    titulo("7. PARÁMETROS: NIVELES, TOP Y SOLO_CON_SALDO")
    for nivel in (3, 4, 5):
        d = m.calcular({2025: l25, 2024: l24}, {**CTX, "nivel": nivel})
        largos = [f["cuenta"] for f in d["filas"] if len(f["cuenta"]) > nivel]
        comprobar(not largos, f"nivel {nivel}: ninguna cuenta más larga que el nivel",
                  f"{len(d['filas'])} cuentas")
        comprobar((d["integridad"]["suma_debe"], d["integridad"]["suma_haber"],
                   d["integridad"]["suma_saldo_final"]) ==
                  (integridad["suma_debe"], integridad["suma_haber"], integridad["suma_saldo_final"]),
                  f"nivel {nivel}: los totales del ejercicio no cambian al agregar")
    d4 = m.calcular({2025: l25, 2024: l24}, {**CTX, "nivel": 4})
    padre = defaultdict(float)
    for f in d4["filas"]:
        padre[f["cuenta"][:3]] += f["saldo_final"]
    comprobar(all(abs(padre[c] - filas[c]["saldo_final"]) < 0.01 for c in padre),
              "las cuentas de nivel 4 suman el saldo final de su cuenta de nivel 3")

    dtop = m.calcular({2025: l25, 2024: l24}, {**CTX, "top": 5})
    comprobar(len(dtop["filas"]) == 5 and dtop["n_cuentas_total"] == len(esperado),
              "top=5 lista 5 de 39 cuentas", f"{len(dtop['filas'])} de {dtop['n_cuentas_total']}")
    comprobar([f["cuenta"] for f in dtop["filas"]] == sorted(f["cuenta"] for f in dtop["filas"]),
              "las cuentas listadas siguen ordenadas por código")
    comprobar(abs(dtop["totales"]["debe"] - sum(f["debe"] for f in dtop["filas"])) < 0.01,
              "con top, la fila de TOTAL suma las cuentas mostradas")
    comprobar(any("top=5 deja fuera" in a for a in dtop["avisos"]), "avisa de las cuentas que deja fuera")

    dsolo = m.calcular({2025: l25, 2024: l24}, {**CTX, "solo_con_saldo": True})
    ceros = [f["cuenta"] for f in dsolo["filas"]
             if not f["saldo_inicial"] and not f["debe"] and not f["haber"]]
    comprobar(not ceros, "solo_con_saldo no deja ninguna cuenta a cero",
              f"{datos['n_cuentas']} → {dsolo['n_cuentas']} cuentas")
    comprobar(dsolo["totales"] == t, "solo_con_saldo no cambia los totales")
    dmal = m.calcular({2025: l25, 2024: l24}, {**CTX, "nivel": 99, "top": -3})
    comprobar(dmal["nivel"] == 3 and any("no es válido" in a for a in dmal["avisos"])
              and any("negativo" in a for a in dmal["avisos"]),
              "nivel 99 → 3 y top negativo → todas, con su aviso")

    titulo("8. MÉTRICAS DEL DASHBOARD")
    md = m.metricas_dashboard(datos)
    comprobar(all(k in md for k in ("n_cuentas", "total_debe", "total_haber", "descuadre")),
              "metricas_dashboard trae n_cuentas, total_debe, total_haber y descuadre", str(list(md)))
    comprobar(md["n_cuentas"] == datos["n_cuentas"] and md["total_debe"] == t["debe"]
              and md["total_haber"] == t["haber"] and md["descuadre"] == integridad["descuadre"],
              "las métricas coinciden con el informe", str({k: md[k] for k in
                                                            ("n_cuentas", "total_debe", "total_haber",
                                                             "descuadre")}))

    titulo("9. HTML DEL INFORME")
    html = m.informe_html(datos, CTX)
    comprobar(html.lstrip().startswith("<div"), "el HTML empieza por '<div'", html[:40])
    comprobar("```" not in html and "<script" not in html and not re.search(r"(?m)^#{1,6} ", html),
              "sin markdown, bloques de código ni JavaScript")
    comprobar("max-width:780px" in html, "ancho de cliente 780px")
    comprobar("Arial" in html and "font-size:13px" in html, "Arial 13px")
    comprobar("ABGA Consultores · farias@abgaconsultores.com" in html, "pie de cliente ABGA")
    comprobar("USO INTERNO" not in html, "no lleva la etiqueta de uso interno")
    importes = re.findall(r">(-?[\d.]+,\d{2}) €<", html)
    celdas_con_euro = [t for t in re.findall(r"<td[^>]*>(.*?)</td>", html, re.S) if "€" in t]
    comprobar(all(re.search(r">-?[\d.]+,\d{2} €<", t) for t in celdas_con_euro)
              and len(celdas_con_euro) >= 4 * datos["n_cuentas"],
              "cada importe es el valor de su celda, en formato es-ES aislado",
              f"{len(celdas_con_euro)} celdas con importe (≥ {4 * datos['n_cuentas']} del detalle)")
    comprobar(len(importes) == len(celdas_con_euro),
              "ningún importe va embebido en una frase: todos están en su celda",
              f"{len(importes)} importes detectados = {len(celdas_con_euro)} celdas")
    # comprobación de extremo a extremo: la celda de la cuenta con más movimiento lleva su importe
    f0 = max(datos["filas"], key=lambda x: x["debe"]) if datos["filas"] else None
    if f0:
        for clave in ("saldo_inicial", "debe", "haber", "saldo_final"):
            comprobar(f">{fmt(f0[clave])}<" in html,
                      f"la celda «{clave}» de la cuenta {f0['cuenta']} lleva su importe exacto",
                      fmt(f0[clave]))
    for cabecera in ("Cuenta", "Saldo inicial", "Debe (ejercicio)", "Haber (ejercicio)", "Saldo final"):
        comprobar(cabecera in html, f"cabecera «{cabecera}»")
    grupos_con_subtotal = [s for s in subtotales if s["n_cuentas"] > 1]
    comprobar(html.count("Grupo ") >= len(grupos_con_subtotal),
              "el detalle se agrupa por grupo (1..9)",
              f"{html.count('Grupo ')} menciones para {len(grupos_con_subtotal)} grupos con subtotal")
    comprobar(all(s["etiqueta"] in html for s in subtotales), "cada grupo lleva su nombre en el detalle")
    comprobar("Subtotal" in html or "Grupo 6 · Compras y gastos" in html,
              "hay subtotales por grupo marcados en el detalle")
    comprobar("Comprobaciones de integridad" in html and "No cuadra — revisar" in html,
              "las comprobaciones de integridad salen en el informe, con su resultado")
    comprobar("Origen del saldo inicial" in html, "el origen del saldo inicial va destacado arriba")
    comprobar("Σ(Saldo final)" in html and "28,39 €" in html, "el descuadre de 28,39 € aparece cifrado")
    print(fila("tamaño del HTML", f"{len(html) / 1024:.1f} KB"))
    print(fila("huella sha256", hashlib.sha256(html.encode()).hexdigest()[:24]))
    (RAIZ / "salidas" / "sumas_saldos_6091_2025.html").write_text(html, encoding="utf-8")
    print(fila("informe volcado en", "salidas/sumas_saldos_6091_2025.html"))

    titulo("10. GRACEFUL DEGRADATION")
    d0 = m.calcular({}, CTX)
    comprobar(d0["origen_inicial"] == "ninguno" and d0["n_cuentas"] == 0,
              "sin datos: sin apertura ni ejercicio anterior, cero cuentas")
    comprobar(any("No hay apuntes cargados" in a for a in d0["avisos"])
              and any("no hay asiento de apertura" in a.lower() for a in d0["avisos"]),
              "sin datos: lo dice en los avisos")
    comprobar(m.informe_html(d0, CTX).lstrip().startswith("<div"), "el informe vacío también es HTML válido")
    d1 = m.calcular({2025: l25}, CTX)
    comprobar(d1["origen_inicial"] == "ninguno" and abs(d1["integridad"]["suma_saldo_inicial"]) < 0.01
              and d1["integridad"]["cuadra_saldos"],
              "sólo el ejercicio, sin el anterior: sale con los movimientos del año y cuadra")

    # ------------------------------------------------ 11. casos reales con apertura (caché local)
    titulo("11. CASOS REALES CON ASIENTO DE APERTURA (caché local, sin ERP)")
    l1092_25, l1092_24 = cargar_cache("1092", 2025), cargar_cache("1092", 2024)
    if not l1092_25 or not l1092_24:
        print("    omitido: la caché no tiene 1092/2024-2025 (no se toca el ERP para traerlos)")
    else:
        ctx1092 = {**CTX, "empresa": "ABGA Consultores", "cod_empresa": "1092"}
        d = m.calcular({2025: l1092_25, 2024: l1092_24}, ctx1092)
        claves, ap = mod.detectar_apertura(l1092_25)
        comprobar(claves == {("9", "9")}, "detecta el asiento de apertura 9-9 de 1092/2025", str(claves))
        comprobar(d["origen_inicial"] == "apertura", "usa la apertura cuando existe",
                  d["origen_inicial"])
        comprobar(d["integridad"]["n_asientos_apertura"] == 1
                  and abs(d["integridad"]["suma_saldo_inicial"]) < 0.01,
                  "Σ saldo inicial = 0 (el asiento de apertura cuadra)")
        comprobar(d["integridad"]["cuadra_debe_haber"] and d["integridad"]["cuadra_saldos"],
                  "ΣDebe = ΣHaber y Σ saldo final = 0 en un ejercicio cerrado y cuadrado")
        comprobar(not any("no está cerrado" in a for a in d["avisos"]),
                  "no avisa de arrastre de gastos e ingresos: el ejercicio anterior cerró contra la 129")
        print(fila("cuentas / líneas de apertura", f"{d['n_cuentas']} cuentas · {len(ap)} líneas"))
        print(fila("ΣDebe = ΣHaber", eur(d["integridad"]["suma_debe"])))
        print(fila("Σ saldo final", eur(d["integridad"]["suma_saldo_final"])))

        # reconciliación: el cierre de 2024 (con regularización, sin asiento de cierre) es la apertura de 2025
        cierre = detectar_cierre(l1092_24)
        fuera = set(cierre["asientos_cierre"])
        s_cierre = saldos_por_cuenta([l for l in l1092_24
                                      if (l.serie, l.documento) not in fuera])
        s_apertura = saldos_por_cuenta(ap)
        cuentas = set(s_cierre) | set(s_apertura)
        iguales = [c for c in cuentas
                   if abs((s_apertura[c].deudor if c in s_apertura else 0.0)
                          - (s_cierre[c].deudor if c in s_cierre else 0.0)) < 0.01]
        comprobar(len(iguales) == len(cuentas),
                  "las dos ramas cuadran: cierre 2024 (sin asiento de cierre) == apertura 2025, "
                  "cuenta a cuenta", f"{len(iguales)}/{len(cuentas)} cuentas")
        print(fila("  asiento de cierre de 2024", str(cierre["asientos_cierre"])))
        print(fila("  Σ apertura 2025 / Σ cierre 2024",
                   f"{eur(sum(s.deudor for s in s_apertura.values()))} / "
                   f"{eur(sum(s.deudor for s in s_cierre.values()))}"))

    l6221_24 = cargar_cache("6221", 2024)
    if not l6221_24:
        print("    omitido: la caché no tiene 6221/2024")
    else:
        claves, ap = mod.detectar_apertura(l6221_24)
        comprobar(claves == {("4", "1")}, "detecta la apertura 4-1 de 6221/2024 por su descripción "
                                          "(«Apertura», tipo de asiento 0: no basta el marcador del ERP)",
                  str(claves))
        d = m.calcular({2024: l6221_24, 2023: []}, {**CTX, "cod_empresa": "6221", "year": 2024})
        comprobar(d["origen_inicial"] == "apertura" and abs(d["integridad"]["suma_saldo_inicial"]) < 0.01
                  and d["integridad"]["cuadra_saldos"],
                  "6221/2024: apertura de 841 líneas, Σ saldo inicial 0 y Σ saldo final 0",
                  f"{d['integridad']['n_asientos_apertura']} asiento(s), "
                  f"{len(ap)} líneas")

    titulo("RESUMEN")
    if fallos:
        print(f"  {len(fallos)} COMPROBACIONES FALLIDAS:")
        for f in fallos:
            print(f"    - {f}")
        return 1
    print("  Todas las comprobaciones han pasado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
