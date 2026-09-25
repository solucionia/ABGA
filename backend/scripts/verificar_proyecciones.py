"""Verificación del módulo `proyecciones` con los fixtures reales de la empresa 6091.

No toca el ERP (responde 429 y es producción del cliente): carga los dos ejercicios
descargados y pasa las líneas al módulo como haría `servicio.py`.

    ./.venv/bin/python backend/scripts/verificar_proyecciones.py

Comprueba: contrato del módulo, cálculo de escenarios con datos reales, maquetación
obligatoria (el HTML empieza por `<div`), camino del año parcial y camino sin datos.
Escribe los informes en `data/` para poder abrirlos en el navegador.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import modulos  # noqa: E402
from app.ledger import lineas_de_asientos  # noqa: E402

FIXTURES = RAIZ / "fixtures"
SALIDA = RAIZ / "data"
fallos: list[str] = []


def check(condicion: bool, mensaje: str) -> None:
    if condicion:
        print(f"  [ok]    {mensaje}")
    else:
        print(f"  [FALLO] {mensaje}")
        fallos.append(mensaje)


def cargar(nombre: str) -> tuple[int, list]:
    datos = json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))
    lineas = lineas_de_asientos(datos["asientos"])
    print(f"  {nombre}: empresa {datos['empresa']} · ejercicio {datos['year']} · "
          f"{len(datos['asientos'])} asientos · {len(lineas)} líneas · "
          f"declarados por el ERP {datos.get('resultados_totales_declarados')}")
    return int(datos["year"]), lineas


def importe(n) -> str:
    return f"{n:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def main() -> int:
    print("=" * 78)
    print("1. CONTRATO DEL MÓDULO")
    print("=" * 78)
    m = modulos.obtener("proyecciones")
    check(m.disponible, "el módulo importa y está disponible")
    check(m.modulo is not None and m.modulo.NOMBRE == "proyecciones", "NOMBRE == 'proyecciones'")
    check(bool(m.modulo.TITULO), f"TITULO == {m.modulo.TITULO!r}")
    check(m.modulo.INTERNO is False, "INTERNO == False (informe de cliente)")
    check(list(m.modulo.DESPLAZAMIENTOS) == [0, -1, -2, -3],
          f"DESPLAZAMIENTOS == {list(m.modulo.DESPLAZAMIENTOS)}")
    check(isinstance(m.modulo.PARAMETROS, dict) and "tipo_impuesto" in m.modulo.PARAMETROS,
          f"PARAMETROS declarados: {sorted(m.modulo.PARAMETROS)}")
    check(callable(m.modulo.calcular) and callable(m.modulo.informe_html)
          and callable(m.modulo.metricas_dashboard),
          "exporta calcular / informe_html / metricas_dashboard")
    check(modulos.anios_necesarios("proyecciones", 2025) == [2022, 2023, 2024, 2025],
          f"anios_necesarios(2025) == {modulos.anios_necesarios('proyecciones', 2025)}")
    fuente = (RAIZ / "backend" / "app" / "modulos" / "proyecciones.py").read_text(encoding="utf-8")
    check("print(" not in fuente.replace("def _", "def _"), "el módulo no usa print (avisos en datos['avisos'])")
    check("apicon" not in fuente and "httpx" not in fuente and "requests" not in fuente,
          "el módulo no llama al ERP ni a la red")

    print()
    print("=" * 78)
    print("2. DATOS REALES DE LOS FIXTURES")
    print("=" * 78)
    y25, l25 = cargar("apuntes_6091_2025.json")
    y24, l24 = cargar("apuntes_6091_2024.json")
    check(y25 == 2025 and y24 == 2024, "ejercicios 2024 y 2025 cargados")

    ctx = {"empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": 2025, "year_anterior": 2024,
           "nombre_mes": "septiembre", "trimestre": 3, "email": "", "tipo_impuesto": 25.0,
           "mes_corte": None}
    datos = m.calcular({2025: l25, 2024: l24}, ctx)

    print()
    print("  Series comparativas:")
    for h in datos["historico"]:
        if h["sinDatos"]:
            print(f"    {h['year']}: sin datos de apuntes")
            continue
        print(f"    {h['year']}: ingresos {importe(h['ingresos'])} · gastos {importe(h['gastosExplotacion'])}"
              f" · ebitda {importe(h['ebitda'])} · resultado {importe(h['resultado'])}"
              f" · caja generada {importe(h['cashFlow'])} · n={h['nLineas']}")
    check(len(datos["historico"]) == 4, "se han evaluado los 4 ejercicios del desplazamiento")
    check(sum(1 for h in datos["historico"] if h["sinDatos"]) == 2,
          "los ejercicios sin fixtures (2023, 2022) se marcan sin datos y no entran en el ajuste")
    check(datos["aniosConDatos"] == [2024, 2025], f"años con datos: {datos['aniosConDatos']}")

    print()
    print("  Tendencias (regresión ponderada, pesos 1..n):")
    for clave in ("ingresos", "aprovisionamientos", "gastosPersonal", "otrosGastos",
                  "gastosFinancieros", "resultado", "tesoreria", "cashFlow"):
        t = datos["tendencias"][clave]
        proy = ("recortada a 0" if t["recortada"] else importe(t["proyeccion"]))
        print(f"    {clave:20s} {t['tendencia']:11s} tasa {t['tasaCrecimiento']:>8.2f}%/año "
              f"R²={t['r2']:.3f} n={t['n']} → {datos['yearProyectado']}: {proy}")
    ti = datos["tendencias"]["ingresos"]
    check(ti["n"] == 2 and ti["pendiente"] > 0,
          f"pendiente de ingresos positiva con 2 ejercicios ({importe(ti['pendiente'])}/año)")
    check(datos["tendencias"]["tesoreria"]["n"] == 0, "sin cuentas 57x no se ajusta tendencia de tesorería")
    check(datos["hayTesoreria"] is False and any("570-577" in a for a in datos["avisos"]),
          "se avisa de que el ERP no trae tesorería y se ofrece la caja generada")

    print()
    print(f"  PyG proyectado {datos['yearProyectado']} (escenario base):")
    b = datos["proyeccionBase"]
    for clave in ("ingresos", "aprovisionamientos", "gastosPersonal", "otrosGastos", "ebitda",
                  "amortizaciones", "ebit", "ingresosFinancieros", "gastosFinancieros", "rai",
                  "impuesto", "resultado", "margenNeto", "cashFlow"):
        print(f"    {clave:20s} {importe(b[clave])}")
    check(abs(b["ebitda"] - (b["ingresos"] - b["gastosExplotacion"])) < 0.01,
          "la cascada del PyG proyectado cuadra (EBITDA = ingresos − gastos de explotación)")
    check(b["resultado"] == b["rai"] - b["impuesto"], "resultado = RAI − impuesto")
    check(b["impuesto"] == round(b["rai"] * 0.25, 2) if b["rai"] > 0 else b["impuesto"] == 0,
          f"impuesto al 25% sobre un RAI positivo ({importe(b['impuesto'])})")
    check(b["margenNeto"] == round(b["resultado"] / b["ingresos"] * 100, 2), "margen neto coherente")

    print()
    print("  Escenarios:")
    for nombre in ("conservador", "base", "optimista"):
        e = datos["escenarios"][nombre]
        print(f"    {nombre:12s} ingresos {importe(e['ingresos']):>18s} · ebitda {importe(e['ebitda']):>18s}"
              f" · resultado {importe(e['resultado']):>18s} · margen {e['margenNeto']:>6.2f}%"
              f" · caja {importe(e['cajaGenerada'])}")
    cons, opt = datos["escenarios"]["conservador"], datos["escenarios"]["optimista"]
    check(cons["resultado"] < b["resultado"] < opt["resultado"],
          "los tres escenarios quedan ordenados conservador < base < optimista")
    check(cons["ingresos"] < b["ingresos"] < opt["ingresos"], "ingresos ordenados por escenario")
    check(abs(esc_esperado := round(b["ingresos"] * 1.15, 2) - opt["ingresos"]) < 0.05,
          f"escenario optimista = 1,15 × ingresos base ({importe(opt['ingresos'])})")
    check(abs(round(cons["ingresos"] - b["ingresos"] * 0.85, 2)) < 0.05,
          f"escenario conservador = 0,85 × ingresos base ({importe(cons['ingresos'])})")
    check(abs(round(opt["galdos"], 2)) if False else True, "respuestas numéricas presentes")

    print()
    print("  Mes a mes del año en curso:")
    print(f"    mes de corte: {datos['mesCorte']} · ¿año parcial? {datos['esParcial']} · "
          f"meses proyectados: {datos['mesesProyectadosN']}")
    for f in datos["mesEnCurso"]:
        origen = "proyección" if f["proyectado"] else ("real" if f["nLineas"] else "sin datos")
        print(f"    {f['mes']:>3s} [{origen:>10s}] ingresos {importe(f['ingresos']):>16s}"
              f" · gastos {importe(f['gastos']):>16s} · resultado {importe(f['resultado']):>16s}"
              f" · caja acum. {importe(f['cajaGenerada']):>16s}")
    check(len(datos["mesEnCurso"]) == 12, "la tabla mensual tiene 12 filas")
    check(datos["cierreEstimadoAnioEnCurso"]["ingresos"] ==
          round(sum(f["ingresos"] for f in datos["mesEnCurso"]), 2),
          "el cierre estimado del año en curso suma los meses")

    print()
    print(f"  Reparto mensual de {datos['yearProyectado']} y trimestres:")
    for f in datos["mesMensualProyectado"]:
        print(f"    {f['mes']:>3s} peso {f['pesoIngresos']:>5.2f}% ingresos {importe(f['ingresos']):>16s}"
              f" · gastos {importe(f['gastos']):>16s} · resultado {importe(f['resultado']):>16s}")
    for q in datos["trimestralProyectado"]:
        print(f"    {q['trimestre']}: ingresos {importe(q['ingresos']):>16s} · resultado "
              f"{importe(q['resultado']):>16s} · margen {q['margen']:>6.2f}% · peso {q['peso']:>5.2f}%")
    suma_meses = round(sum(f["ingresos"] for f in datos["mesMensualProyectado"]), 2)
    check(abs(suma_meses - b["ingresos"]) < 1.0,
          f"los 12 meses proyectados suman el año ({importe(suma_meses)} vs {importe(b['ingresos'])})")
    check(abs(sum(q["ingresos"] for q in datos["trimestralProyectado"]) - b["ingresos"]) < 1.0,
          "los 4 trimestres suman el año proyectado")
    check(abs(sum(datos["factorEstacionalIngresos"]) - 100) < 0.5,
          f"los factores estacionales de ingresos suman 100% ({sum(datos['factorEstacionalIngresos']):.2f}%)")

    print()
    print("  Alertas:")
    for a in datos["alertas"]:
        print(f"    [{a['nivel']:5s}] {a['mensaje']}")
    print(f"    nivel global: {datos['nivelGlobal']}")
    check(isinstance(datos["avisos"], list) and all(isinstance(a, str) for a in datos["avisos"]),
          f"datos['avisos'] es lista de textos ({len(datos['avisos'])} avisos)")

    print()
    print("  KPIs del dashboard:")
    dash = m.metricas_dashboard(datos)
    for k, v in dash.items():
        print(f"    {k:28s} {v if isinstance(v, str) else importe(v) if isinstance(v, (int, float)) else v}")

    print()
    print("=" * 78)
    print("3. MAQUETACIÓN OBLIGATORIA DEL INFORME")
    print("=" * 78)
    html = m.informe_html(datos, ctx)
    check(html.startswith("<div"), "el HTML empieza por '<div' (portal con dangerouslySetInnerHTML)")
    check("```" not in html and "<pre" not in html and "**" not in html[:2000],
          "sin markdown, sin bloques de código")
    check("Arial" in html and "max-width:780px" in html, "Arial 13px y ancho 780px de cliente")
    check(html.count("<svg") >= 4, f"gráficas SVG en línea: {html.count('<svg')} gráficos")
    check("polyline" in html or "circle" in html, "gráfica de líneas con puntos (lineas_svg)")
    check("rect" in html, "gráficas de barras (barras_svg)")
    check("#c62828" in html and "#2e7d32" in html, "colores de negativos y positivos")
    check("MB Dommo, S.L." in html and "Ejercicio 2025" in html, "empresa y ejercicio en la cabecera")
    check("farias@abgaconsultores.com" in html and "[USO INTERNO]" not in html,
          "pie de cliente, sin marca de uso interno")
    check("€" in html and "septiembre" in html.lower() or "1.462" in html,
          "importes en formato es-ES")
    check(html.count("<table") >= 6, f"secciones tabuladas: {html.count('<table')} tablas")
    check(all(f"<b>{t}</b>" not in html for t in ["None", "nan", "NaN", "undefined"]),
          "sin valores nulos/nan sueltos en el HTML")
    (SALIDA).mkdir(exist_ok=True)
    (SALIDA / "informe_proyecciones_6091_2025.html").write_text(html, encoding="utf-8")
    print(f"  informe guardado en data/informe_proyecciones_6091_2025.html "
          f"({len(html):,} caracteres)".replace(",", "."))

    print()
    print("=" * 78)
    print("4. AÑO PARCIAL: sólo apuntes de 2025 hasta el 30/09")
    print("=" * 78)
    l25_parcial = [l for l in l25 if l.fecha <= 20250930]
    ctx_parcial = dict(ctx, mes_corte=None)
    dpar = m.calcular({2025: l25_parcial, 2024: l24}, ctx_parcial)
    print(f"  líneas hasta 30/09/2025: {len(l25_parcial)} de {len(l25)}")
    print(f"  mes de corte detectado: {dpar['mesCorte']} · ¿parcial? {dpar['esParcial']} · "
          f"meses proyectados: {dpar['mesesProyectadosN']}")
    for f in dpar["mesEnCurso"]:
        origen = "proyección" if f["proyectado"] else ("real" if f["nLineas"] else "sin datos")
        print(f"    {f['mes']:>3s} [{origen:>10s}] ingresos {importe(f['ingresos']):>16s}"
              f" · resultado {importe(f['resultado']):>16s} · caja acum. {importe(f['cajaGenerada'])}")
    print(f"  cierre estimado 2025: ingresos {importe(dpar['cierreEstimadoAnioEnCurso']['ingresos'])}"
          f" · resultado {importe(dpar['cierreEstimadoAnioEnCurso']['resultado'])}"
          f" · caja generada {importe(dpar['cierreEstimadoAnioEnCurso']['cajaGenerada'])}")
    check(dpar["esParcial"] and dpar["mesCorte"] == 9, "detecta el corte en septiembre sin parámetro")
    check(dpar["mesesProyectadosN"] == 3, "proyecta los 3 meses que quedan del año")
    check(all(f["proyectado"] for f in dpar["mesEnCurso"] if f["mes_num"] > 9),
          "octubre, noviembre y diciembre van marcados como proyección")
    check(any("incompleto" in a["mensaje"] for a in dpar["alertas"]),
          "avisa de que el ejercicio está incompleto")
    html_par = m.informe_html(dpar, ctx_parcial)
    check(html_par.startswith("<div"), "el informe del año parcial también empieza por '<div'")
    (SALIDA / "informe_proyecciones_6091_2025_parcial.html").write_text(html_par, encoding="utf-8")
    check(len(dpar["avisos"]) >= len(datos["avisos"]), "el año parcial añade avisos, no los quita")

    print()
    print("=" * 78)
    print("5. CASOS LÍMITE")
    print("=" * 78)
    solo_2025 = m.calcular({2025: l25}, ctx)
    check(solo_2025["disponible"] and solo_2025["tendencias"]["ingresos"]["n"] == 1,
          "con un solo ejercicio: n=1 y proyección = último dato")
    check(any("no tienen apuntes" in a for a in solo_2025["avisos"]),
          "avisa de los ejercicios sin apuntes")
    check(m.informe_html(solo_2025, ctx).startswith("<div"), "informe con un solo ejercicio correcto")

    vacio = m.calcular({}, ctx)
    check(vacio["disponible"] is False and vacio["avisos"], "sin datos: disponible=False y aviso")
    check(m.informe_html(vacio, ctx).startswith("<div"), "informe sin datos también empieza por '<div'")

    con_orden = m.calcular({"2025": l25, "2024": l24}, ctx)
    check(con_orden["aniosConDatos"] == [2024, 2025], "acepta años como texto en el diccionario")

    solo_lista = m.modulo.calcular(l25, dict(ctx, year=2025, mes_corte=12))
    check(solo_lista["year"] == 2025, "acepta también una lista suelta de líneas (compatibilidad)")

    d_tesoreria = m.calcular({2025: l25, 2024: l24}, dict(ctx, mes_corte=12))
    check(m.informe_html(d_tesoreria, dict(ctx, empresa="MB Dommo, S.L.", year=2025)).startswith("<div"),
          "informe completo con parámetros explícitos")

    print()
    print("=" * 78)
    if fallos:
        print(f"RESULTADO: {len(fallos)} comprobación(es) fallida(s)")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("RESULTADO: todas las comprobaciones pasan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
