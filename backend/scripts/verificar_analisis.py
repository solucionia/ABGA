"""Verifica el módulo `analisis` con los apuntes reales, sin tocar el ERP.

    ./.venv/bin/python backend/scripts/verificar_analisis.py [año]

Comprueba:
  1. que se puede calcular y maquetar, y que el HTML empieza por `<div` (requisito del portal);
  2. el recuento por nivel de riesgo y el detalle de cada análisis;
  3. que la ejecución es determinista (dos pasadas dan lo mismo);
  4. que ningún análisis devuelve cifras sin dato: los que no se pueden calcular son
     `no_evaluable` y dicen el motivo.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import informes as inf  # noqa: E402
from app import modulos  # noqa: E402
from app.ledger import fmt, lineas_de_asientos  # noqa: E402
from app.modulos import analisis as mod_analisis  # noqa: E402


def cargar(year: int):
    ruta = RAIZ / "fixtures" / f"apuntes_6091_{year}.json"
    if not ruta.exists():
        raise SystemExit(f"falta el fixture {ruta}")
    return lineas_de_asientos(json.load(ruta.open(encoding="utf-8"))["asientos"])


def main() -> int:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    por_anio = {year: cargar(year), year - 1: cargar(year - 1)}
    ctx = {"empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": year,
           "year_anterior": year - 1, "nombre_mes": "septiembre", "trimestre": 3, "email": ""}

    m = modulos.obtener("analisis")
    if not m.disponible:
        raise SystemExit(f"el módulo no está disponible: {m.error}")

    datos = m.calcular(por_anio, ctx)
    html = m.informe_html(datos, ctx)
    r = datos["resumen"]

    print(f"=== analisis — empresa 6091, ejercicio {year} ===")
    print(f"líneas analizadas: {datos['n_lineas']:,}  ·  HTML: {len(html):,} caracteres".replace(",", "."))
    print(f"\nsemáforo: {r['n_total']} comprobaciones  ·  {r['n_rojo']} rojas  ·  {r['n_naranja']} "
          f"naranjas  ·  {r['n_verde']} verdes  ·  {r['n_no_evaluable']} no evaluables")
    print(f"nivel global: {r['nivel_global']}   importe señalado: {fmt(r['importe_riesgo'])}")

    print("\n=== análisis, por familia ===")
    for familia, titulo in mod_analisis.FAMILIAS:
        lista = datos["por_familia"].get(familia) or []
        print(f"\n-- {titulo} ({len(lista)}) --")
        for h in lista:
            marca = {"alerta": "ROJO ", "aviso": "NARANJ", "ok": "VERDE", "no_evaluable": "N/EV "}[h["nivel"]]
            imp = f" [{fmt(h['importe'])}]" if h["importe"] is not None else ""
            mag = ""
            if h.get("magnitud"):
                mag = f" [{h['magnitud']['valor']} {h['magnitud']['unidad']}]"
            print(f"   {marca} {h['titulo']}: {h['detalle']}{imp}{mag}")

    print("\n=== comprobaciones de forma ===")
    fallos = []
    inf.comprobar_html if hasattr(inf, "comprobar_html") else None

    def ok(nombre, condicion, extra=""):
        print(f"   {'ok   ' if condicion else 'FALLO'} {nombre}{(' — ' + extra) if extra else ''}")
        if not condicion:
            fallos.append(nombre)

    ok("el HTML empieza por <div", html.lstrip().startswith("<div"))
    ok("sin markdown ni bloques de código", "```" not in html and "<pre" not in html)
    ok("CSS inline y fuente Arial", "Arial" in html and "max-width:780px" in html)
    ok("lleva el pie de ABGA", "913 788 740" in html)
    ok("los cuatro niveles aparecen en el resumen",
       all(k in datos["resumen"] for k in ("n_rojo", "n_naranja", "n_verde", "n_no_evaluable")))
    ok("hay avisos", bool(datos["avisos"]))
    ok("las no evaluables explican el motivo",
       all(len(h["detalle"]) > 20 for h in datos["hallazgos"] if h["nivel"] == "no_evaluable"))
    ok("ninguna comprobación se ha roto por excepción",
       not any("no se ha podido ejecutar" in h["detalle"] for h in datos["hallazgos"]))

    datos2 = m.calcular(por_anio, ctx)
    html2 = m.informe_html(datos2, ctx)
    ok("determinista: dos pasadas dan el mismo resultado",
       json.dumps(datos, sort_keys=True, default=str) == json.dumps(datos2, sort_keys=True, default=str)
       and html == html2)

    metricas = m.metricas_dashboard(datos)
    ok("metricas_dashboard devuelve los recuentos",
       metricas.get("n_total") == r["n_total"] and metricas.get("n_rojo") == r["n_rojo"])

    print("\n=== resultado ===")
    if fallos:
        print(f"FALLOS: {', '.join(fallos)}")
        return 1
    print("todas las comprobaciones han pasado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
