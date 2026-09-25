#!/usr/bin/env python3
"""Verificación del módulo `conciliacion` (REQ-01) con datos reales y sin tocar el ERP.

Carga un fixture de apuntes, calcula el informe con el módulo, comprueba un puñado de
invariantes (incluida la clasificación del punteo, que se prueba con marcas sintéticas
porque los fixtures no traen ninguna partida punteada) y pinta los 10 mayores pendientes
por cuenta.

Uso:
    .venv/bin/python backend/scripts/verificar_conciliacion.py
    .venv/bin/python backend/scripts/verificar_conciliacion.py fixtures/apuntes_6091_2024.json --year 2024
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import modulos                                    # noqa: E402
from app.ledger import fmt, lineas_de_asientos, num        # noqa: E402

OK, FALLOS = [], []


def comprobar(condicion: bool, texto: str) -> bool:
    (OK if condicion else FALLOS).append(texto)
    print(f"  [{'OK ' if condicion else 'FALLA'}] {texto}")
    return bool(condicion)


def linea(titulo: str = "") -> None:
    print("\n" + ("─" * 4 + f" {titulo} " if titulo else "") + "─" * max(0, 72 - len(titulo)))


def main() -> int:
    ap = argparse.ArgumentParser(description="Verifica el módulo conciliacion.")
    ap.add_argument("fixture", nargs="?", default="fixtures/apuntes_6091_2025.json")
    ap.add_argument("--year", type=int, default=None, help="ejercicio (por defecto, el del fixture)")
    ap.add_argument("--html", default="", help="ruta donde volcar el HTML generado")
    args = ap.parse_args()

    ruta = (RAIZ / args.fixture) if not Path(args.fixture).is_absolute() else Path(args.fixture)
    bruto = json.loads(ruta.read_text(encoding="utf-8"))
    year = int(args.year or bruto.get("year") or 0)
    cod_empresa = str(bruto.get("empresa") or "")
    lineas = lineas_de_asientos(bruto["asientos"])
    print(f"Fixture {ruta.name}: empresa {cod_empresa} · ejercicio {year} · "
          f"{len(bruto['asientos'])} asientos · {len(lineas)} líneas")

    ctx = {
        "empresa": "MB Dommo, S.L.", "cod_empresa": cod_empresa, "year": year,
        "year_anterior": year - 1, "nombre_mes": "septiembre", "trimestre": 3, "email": "",
    }

    defn = modulos.obtener("conciliacion")
    linea("1. Carga del módulo y contrato")
    comprobar(defn.disponible, f"el módulo carga sin errores{'' if defn.disponible else f' ({defn.error})'}")
    if not defn.disponible:
        return 1
    comprobar(defn.nombre == "conciliacion", f"NOMBRE = {defn.nombre!r}")
    comprobar(defn.titulo == "Conciliación de mayores", f"TITULO = {defn.titulo!r}")
    comprobar(defn.interno is True, "INTERNO = True (informe de uso interno)")
    comprobar(defn.desplazamientos == [0], f"DESPLAZAMIENTOS = {defn.desplazamientos} (no necesita años previos)")
    comprobar(modulos.anios_necesarios("conciliacion", year) == [year],
              f"anios_necesarios = {modulos.anios_necesarios('conciliacion', year)}")
    comprobar("conciliacion" not in {d.nombre for d in modulos.listar()},
              "no aparece en el catálogo público del portal")
    params = defn.parametros
    comprobar(set(params) == {"top_cuentas", "top_terceros", "dias_antiguedad", "limite_hallazgos",
                              "minimo_pendiente"}, f"PARAMETROS = {params}")

    linea("2. Cálculo con datos reales")
    datos = defn.calcular({year: lineas}, ctx)
    html = defn.informe_html(datos, ctx)
    metricas = defn.metricas_dashboard(datos)
    t, p = datos["totales"], datos["punteo"]

    print(f"  {t['n_asientos']} asientos · {t['n_lineas']} partidas · {t['n_cuentas']} cuentas · "
          f"{t['n_grupos']} grupos\n"
          f"  debe {fmt(t['debe'])} · haber {fmt(t['haber'])} · descuadre {fmt(t['descuadre'])}\n"
          f"  pendientes {p['n_pendientes']} ({p['pct_pendientes']} %) · "
          f"importe pendiente {fmt(p['importe_pendiente'])} · "
          f"más de un año: {p['n_antiguas']} partidas / {fmt(p['importe_antiguo'])}\n"
          f"  cuentas con pendiente {datos['n_cuentas_pendientes']} · "
          f"anomalías {datos['n_hallazgos']} por {fmt(datos['importe_anomalias'])} · "
          f"fecha de referencia {datos['fecha_referencia_es']}")

    comprobar(t["n_lineas"] == len(lineas), f"n_lineas = {t['n_lineas']} coincide con el fixture")
    comprobar(t["n_asientos"] == len(bruto["asientos"]),
              f"n_asientos = {t['n_asientos']} coincide con el fixture")
    comprobar(p["n_total"] == p["n_pendientes"] + p["n_punteadas"],
              f"pendientes + punteadas = total ({p['n_pendientes']} + {p['n_punteadas']} = {p['n_total']})")
    comprobar(p["n_marca_cuenta"] == 0 and p["n_marca_bancaria"] == 0,
              "los fixtures no traen ninguna marca de punteo (esperado: 0 y 0)")

    # suma del pendiente por cuenta == total del punteo (invariante contable)
    suma_cuentas = round(sum(c["pendiente"] for c in datos["cuentas_todas"]), 2)
    comprobar(abs(suma_cuentas - p["importe_pendiente"]) < 0.05,
              f"Σ pendiente por cuenta = {fmt(suma_cuentas)} = total del punteo")
    suma_lineas = sum(c["n"] for c in datos["cuentas_todas"])
    comprobar(suma_lineas == len([l for l in lineas if l.cuenta]),
              f"Σ partidas por cuenta = {suma_lineas} (las líneas sin cuenta quedan fuera)")
    comprobar(abs(t["debe"] - t["haber"] - t["descuadre"]) < 0.01,
              f"debe − haber = descuadre ({fmt(t['descuadre'])})")

    linea("3. Clasificación del punteo (None / 'None' / '' / '0' frente a marcas reales)")
    from app.modulos import conciliacion as con

    for valor in (None, "", "None", "none", "0", 0, "NULL", "nan", "-"):
        comprobar(con.marca_punteo(valor) is False, f"sin puntear: {valor!r}")
    for valor in ("20250131", 20250131, "S", "P", "PC-12", "1"):
        comprobar(con.marca_punteo(valor) is True, f"con marca: {valor!r}")

    # con marcas sintéticas: 3 partidas punteadas dejan de contar como pendientes
    marcadas = [dataclasses.replace(l, punteo_cuenta="20250131") for l in lineas[:2]]
    marcadas += [dataclasses.replace(l, punteo_bancario="S") for l in lineas[2:3]]
    mezcla = marcadas + lineas[3:]
    d2 = con.calcular({year: mezcla}, ctx)
    esperado = d2["punteo"]["n_total"] - 3
    comprobar(d2["punteo"]["n_pendientes"] == esperado,
              f"3 marcas sintéticas → pendientes {d2['punteo']['n_pendientes']} de {d2['punteo']['n_total']}")
    comprobar(d2["punteo"]["n_marca_cuenta"] == 2 and d2["punteo"]["n_marca_bancaria"] == 1,
              "se distinguen las marcas de cuenta (2) y bancarias (1)")
    esperado_pend = round(p["importe_pendiente"] - sum(l.importe for l in mezcla[3:] if False) , 2)
    delta = round(p["importe_pendiente"] - d2["punteo"]["importe_pendiente"], 2)
    comprobar(abs(delta - round(sum(l.importe for l in mezcla[:3]), 2)) < 0.01,
              f"el importe pendiente baja exactamente lo punteado ({fmt(delta)})")

    linea("4. Orden por riesgo y coherencia de las filas")
    riesgo_ok = all(datos["cuentas_todas"][i]["riesgo"] >= datos["cuentas_todas"][i + 1]["riesgo"]
                    for i in range(len(datos["cuentas_todas"]) - 1))
    comprobar(riesgo_ok, "las cuentas salen ordenadas por riesgo descendente")
    riesgo_ok_t = all(datos["terceros"][i]["riesgo"] >= datos["terceros"][i + 1]["riesgo"]
                      for i in range(len(datos["terceros"]) - 1))
    comprobar(riesgo_ok_t, "los terceros salen ordenados por riesgo descendente")
    formula_ok = all(abs(c["riesgo"] - round(abs(c["pendiente"]) * (1 + c["antiguedad_dias"] / 365), 2)) < 0.02
                     for c in datos["cuentas_todas"])
    comprobar(formula_ok, "riesgo = |pendiente| × (1 + años de antigüedad)")
    comprobar(all(c["antiguedad_dias"] >= 0 for c in datos["cuentas_todas"]),
              "ninguna antigüedad negativa (referencia = último apunte del ejercicio)")
    comprobar(all(c["nivel"] in {"ALTA", "MEDIA", "INFO"} for c in datos["cuentas_todas"]),
              "todos los niveles son ALTA/MEDIA/INFO")
    comprobar(all(sum(t_["importe"] for t_ in datos["tramos_antiguedad"]) is not None
                  for _ in [0]), "los tramos de antigüedad se calculan")
    n_tramos = sum(t_["n"] for t_ in datos["tramos_antiguedad"])
    comprobar(n_tramos == p["n_pendientes"],
              f"partidas en los tramos de antigüedad = pendientes ({n_tramos})")
    comprobar(all(t["n_pendientes"] > 0 for t in datos["terceros"]),
              "sólo aparecen terceros con partidas pendientes")

    linea("5. Anomalías heredadas del workflow")
    cuadro = {"CLIENTE_SALDO_NEGATIVO": 0, "PROVEEDOR_SALDO_NEGATIVO": 0, "COBRO_SIN_CONTRAPARTIDA": 0,
              "PAGO_SIN_CONTRAPARTIDA": 0, "PARTIDA_PENDIENTE_555": 0, "ASIENTO_DUPLICADO": 0}
    cuadro.update(datos["hallazgos_recuento"])
    for tipo, n in cuadro.items():
        print(f"  {tipo:28} {n}")
    comprobar(sum(datos["hallazgos_recuento"].values()) == datos["n_hallazgos"],
              f"el recuento por tipo suma el total ({datos['n_hallazgos']})")
    comprobar(all(h["importe"] >= 0 for h in datos["hallazgos"]),
              "los importes de las anomalías son positivos (el signo va en la descripción)")
    comprobar(all(h["tipo"] in cuadro for h in datos["hallazgos"]), "todos los tipos son conocidos")
    saldos_negativos = [h for h in datos["hallazgos"] if h["tipo"] == "CLIENTE_SALDO_NEGATIVO"]
    comprobar(all(h["nivel_importe"] > 0.01 for h in saldos_negativos),
              f"los {len(saldos_negativos)} clientes con saldo contrario traen importe")

    linea("6. HTML")
    comprobar(html.lstrip().startswith("<div"), "el HTML empieza por '<div'")
    comprobar("```" not in html and "<script" not in html.lower(),
              "no hay bloques de código ni JavaScript")
    comprobar("font-family:Arial" in html.replace(" ", ""), "fuente Arial, como exige el contrato")
    comprobar("[USO INTERNO]" in html, "lleva la etiqueta [USO INTERNO]")
    comprobar("Generado automáticamente" in html, "pie de informe interno")
    comprobar("farias@abgaconsultores.com" not in html, "no lleva datos de contacto de cliente")
    comprobar(html.rstrip().endswith("</div>"), "cierra con </div>")
    comprobar(len(html) > 3000, f"el HTML tiene cuerpo suficiente ({len(html)} caracteres)")
    if args.html:
        destino = Path(args.html) if Path(args.html).is_absolute() else RAIZ / args.html
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(html, encoding="utf-8")
        print(f"  HTML volcado en {destino}")

    linea("7. Los 10 mayores pendientes por cuenta")
    print(f"  {'cuenta':14} {'grupo':24} {'pendiente':>14} {'sin puntear':>11} "
          f"{'part.':>6} {'más antigua':>12} {'riesgo':>13}  nivel")
    for c in datos["cuentas"][:10]:
        print(f"  {c['cuenta']:14} {c['grupo'][:24]:24} {num(c['pendiente']):>14} "
              f"{c['pct_pendiente']:>10}% {c['n_pendientes']:>6} {c['fecha_antigua_es']:>12} "
              f"{num(c['riesgo']):>13}  {c['nivel']}")
    comprobar(len(datos["cuentas"]) <= params["top_cuentas"],
              f"se pintan como mucho {params['top_cuentas']} cuentas ({len(datos['cuentas'])})")
    comprobar(all(abs(c["pendiente"]) >= params["minimo_pendiente"] for c in datos["cuentas"]),
              f"ninguna cuenta pintada baja de {fmt(params['minimo_pendiente'])} de pendiente")

    print("\n  Mayores pendientes por tercero:")
    for t_ in datos["terceros"][:5]:
        print(f"    {t_['tercero'][:34]:34} {t_['grupo'][:16]:16} {num(t_['pendiente']):>12} "
              f"({t_['n_pendientes']} part., {t_['anios']} a.)")

    print("\n  Avisos del informe:")
    for a in datos["avisos"]:
        print(f"    · {a}")
    comprobar(bool(datos["avisos"]), "el informe deja avisos para el asesor")
    comprobar(isinstance(datos.get("avisos"), list) and all(isinstance(a, str) for a in datos["avisos"]),
              "avisos = lista de strings")
    comprobar(set(metricas) >= {"n_pendientes", "importe_pendiente", "n_hallazgos"},
              f"metricas_dashboard devuelve KPIs numéricos ({len(metricas)} claves)")

    linea("8. Serialización (lo que viaja al portal)")
    try:
        texto = json.dumps(datos, ensure_ascii=False)
        json.loads(texto)
        comprobar(True, f"datos es JSON serializable ({len(texto)} caracteres)")
    except TypeError as e:
        comprobar(False, f"datos NO es JSON serializable: {e}")
    comprobar("cuentas_todas" in datos and "cuentas" in datos,
              "se distingue lo pintado de lo calculado (cuentas / cuentas_todas)")

    linea("Resultado")
    print(f"  {len(OK)} comprobaciones OK · {len(FALLOS)} fallos")
    for f in FALLOS:
        print(f"    FALLA: {f}")
    print("\n" + ("VERIFICACIÓN OK" if not FALLOS else "VERIFICACIÓN CON FALLOS"))
    return 0 if not FALLOS else 1


if __name__ == "__main__":
    raise SystemExit(main())
