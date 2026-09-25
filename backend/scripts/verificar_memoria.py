#!/usr/bin/env python
"""Verificación del módulo `memoria` (REQ-08 Memoria de cuentas anuales, PGC PYME).

Carga los fixtures reales de la empresa 6091 (`apuntes_6091_2025.json` y el de 2024), calcula
la Memoria sin llamar al ERP (prohibido: es el sistema de producción del cliente) e imprime las
10 notas con sus cifras principales. Después comprueba:

  1. que el módulo cumple el contrato de `backend/CONTRATO-MODULOS.md` (NOMBRE, TITULO, INTERNO,
     DESPLAZAMIENTOS = [0, -1], parámetros, `calcular`, `informe_html`, `metricas_dashboard`);
  2. que el HTML empieza por `<div`, va a 800 px y a 11 px (lo que exige el ancho propio de la
     Memoria), sin markdown y con el pie de ABGA;
  3. que **cada cifra** cuadra con un recálculo independiente hecho aquí sobre los apuntes crudos;
  4. que **no queda ninguna estimación del workflow original**: ni el 25 % del RAI para el
     impuesto, ni el resultado del año anterior estimado, ni el ×1,2 / ×1,15 del inmovilizado, ni
     el reparto al 20 % de los vencimientos. Lo que no se puede sacar se declara en `avisos` y en
     el informe como «pendiente / a mano».

Uso:  cd <raíz del proyecto> && ./.venv/bin/python backend/scripts/verificar_memoria.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import modulos                                     # noqa: E402
from app.ledger import fmt, lineas_de_asientos              # noqa: E402

COD_EMPRESA = "6091"
EMPRESA = "MB Dommo, S.L."
TOLERANCIA = 0.05    # el módulo redondea a céntimos

fallos: list[str] = []
comprobaciones = 0


def comprobar(condicion: bool, mensaje: str) -> bool:
    global comprobaciones
    comprobaciones += 1
    if condicion:
        print(f"   ✓ {mensaje}")
    else:
        print(f"   ✗ {mensaje}")
        fallos.append(mensaje)
    return bool(condicion)


def cerca(a: float, b: float, tol: float = TOLERANCIA) -> bool:
    return abs(float(a) - float(b)) <= tol


def cargar(year: int) -> tuple[list[dict], list]:
    crudo = json.loads((RAIZ / "fixtures" / f"apuntes_6091_{year}.json").read_text(encoding="utf-8"))
    return crudo["asientos"], lineas_de_asientos(crudo["asientos"])


# ------------------------------------------------------------------ legado REQ-08, recalcular
def legado(year: int, asientos: list[dict], usa_estimacion: bool = True) -> dict:
    """Recalcula REQ-08 tal cual (con la estimación del 25 % y los ×1,2/×1,15) para contrastar."""
    lineas = [d for a in asientos for d in (a.get("Detalles") or [])]

    def num(v):
        return float(v or 0)

    def suma_a(pref):
        return sum(num(l.get("Haber")) - num(l.get("Debe"))
                   for l in lineas if any(str(l.get("Cuenta") or "").startswith(p) for p in pref))

    def suma_d(pref):
        return sum(num(l.get("Debe")) - num(l.get("Haber"))
                   for l in lineas if any(str(l.get("Cuenta") or "").startswith(p) for p in pref))

    ventas = suma_a(["700", "701", "702", "703", "704", "705"])
    otros = suma_a(["706", "708", "709", "74", "75"])
    total_ing = ventas + otros
    gastos = (suma_d(["600", "601", "602", "606", "607", "608", "609", "610", "611", "612"])
              + suma_d(["640", "641", "642", "643", "644", "649"])
              + suma_d(["620", "621", "622", "623", "624", "625", "626", "627", "628", "629",
                        "650", "651"])
              + suma_d(["680", "681", "682"]))
    # el REQ-08 original no miraba el grupo 67 (gastos excepcionales): la Memoria sí, como pyg
    gastos_67 = suma_d(["67"])
    rai = (total_ing - gastos + suma_a(["760", "761", "762", "769"])
           - suma_d(["660", "661", "662", "663", "664", "665", "669"]))
    rai_con_pyg = (total_ing - gastos - gastos_67 + suma_a(["760", "761", "762", "769"])
                   - suma_d(["660", "661", "662", "663", "664", "665", "669"]))
    impuesto_real = suma_d(["630"])
    impuesto_legado = impuesto_real or (rai * 0.25 if rai > 0 else 0.0)
    inmov_int = suma_d(["200", "201", "202", "203", "204", "205", "206", "207", "280"])
    inmov_mat = suma_d(["210", "211", "212", "213", "214", "215", "216", "217", "218", "219",
                        "281", "282"])
    return {
        "year": year,
        "ventas": ventas, "totalIng": total_ing,
        "amort": suma_d(["680", "681", "682"]),
        "gastFin": suma_d(["660", "661", "662", "663", "664", "665", "669"]),
        "rai": rai,
        "gastos67": gastos_67,
        "raiConPyg": rai_con_pyg,
        "impuestoReal": impuesto_real,
        "impuestoEstimado25": rai * 0.25 if (usa_estimacion and rai > 0) else 0.0,
        "resultadoCon25": rai - (impuesto_real or (rai * 0.25 if rai > 0 else 0.0)),
        "resultadoReal": rai_con_pyg - impuesto_real,
        "inmovInt": inmov_int, "inmovMat": inmov_mat,
        "inmovInicialInventado": inmov_int * 1.2 + inmov_mat * 1.15,
        "inmovDotacionInventada": inmov_int * 0.2 + inmov_mat * 0.15,
        "ivaRepercutido": suma_a(["477"]), "ivaSoportado": suma_d(["472"]),
        "retenciones": suma_a(["4751"]),
        "clientes": suma_d(["430", "431", "432", "433", "440", "441"]),
        "tesoreria": suma_d(["570", "571", "572", "573", "574", "575", "576", "577"]),
        "deudasCP": suma_a(["500", "501", "502", "503", "504", "505", "506", "507", "508", "509",
                            "520", "521", "522", "523", "524", "525", "526", "527", "528", "529",
                            "550", "551", "552", "553", "554"]),
        "proveedores": suma_a([str(n) for n in range(400, 420)]),
    }


# ------------------------------------------------------------------ impresión de las notas
def imprimir_notas(datos: dict) -> None:
    fiscal = datos["fiscal"]
    aplicacion = datos["aplicacionResultado"]
    nota = lambda n, t: print(f"\n   NOTA {n} · {t}")  # noqa: E731

    print(f"\n   Ejercicio {datos['year']} · {datos['empresa']} (empresa {datos['codEmpresa']}) · "
          f"{datos['nLineas']} líneas · primer asiento {datos['primeraFecha']}")
    nota(1, "Actividad de la empresa")
    print(f"      localidad {datos['localidad']} · administrador {datos['administrador'] or '(pendiente)'}")
    print(f"      formulación: {datos['fechaFormulacion']} · ingresos de explotación {fmt(datos['totalIngresos'])}")
    nota(2, "Bases de presentación")
    print(f"      ingresos {datos['yearAnterior']}: {fmt(datos['totalIngresosAnt'])} → "
          f"{datos['year']}: {fmt(datos['totalIngresos'])} ({datos['varIngresos']:+.1f}%)")
    print(f"      resultado {datos['yearAnterior']}: {fmt(datos['resultadoNetoAnt'])} → "
          f"{datos['year']}: {fmt(datos['resultadoNeto'])} ({datos['varResultado']:+.1f}%)")
    print(f"      activo total {fmt(datos['totalActivo'])} (año anterior {fmt(datos['totalActivoAnt'])}) · "
          f"patrimonio neto {fmt(datos['patrimonioNeto'])} · fondo de maniobra {fmt(datos['fondoManiobra'])}")
    print(f"      cuadre del libro: descuadre {fmt(datos['integridad']['cuadre']['descuadre'])}")
    print(f"      grupos sin ninguna cuenta: {', '.join(datos['integridad']['gruposSinMovimiento']) or 'ninguno'}")
    nota(3, "Aplicación de resultados")
    print(f"      base de reparto {fmt(aplicacion['baseReparto'])} · cuenta 129 {fmt(aplicacion['resultadoEnLibros'])} · "
          f"reservas de libre disposición {fmt(aplicacion['reservasDisponibles'])}")
    print(f"      propuesta: {aplicacion['propuesta'][:110]}")
    nota(4, "Normas de registro y valoración")
    print(f"      amortizaciones del ejercicio {fmt(datos['amortizaciones'])} · "
          f"correcciones por deterioro {fmt(datos['criterios']['correccionesValor'])} · "
          f"existencias {fmt(datos['existencias'])}")
    print(f"      personal: sueldos {fmt(datos['sueldos'])} · SS {fmt(datos['seguridadSocial'])} · "
          f"indemnizaciones {fmt(datos['indemnizaciones'])}")
    nota(5, "Inmovilizado intangible y material")
    for f in datos["inmovilizado"]:
        print(f"      {f['etiqueta']:<52} saldo inicial {'—' if f['saldoInicial'] is None else f['saldoInicial']}"
              f" · altas {fmt(f['altasEjercicio'])} · bajas {fmt(f['bajasEjercicio'])}"
              f" · dotación {fmt(f['dotacionEjercicio'])} · amort. acum. {fmt(-f['amortizacionAcumulada'])}"
              f" · saldo apuntes {fmt(f['saldoApuntes'])}")
    print(f"      TOTAL inmovilizado {fmt(datos['totalInmovilizado'])}")
    nota(6, "Activos financieros, clientes y deudores")
    print(f"      inversiones LP {fmt(datos['inversionesLP'])} · clientes {fmt(datos['clientes'])} · "
          f"otros deudores {fmt(datos['otrosDeudores'])} · tesorería {fmt(datos['tesoreria'])}")
    for c in datos["clientesDetalle"][:5]:
        print(f"      · {c['etiqueta'][:56]:<56} {fmt(c['saldo'])}")
    nota(7, "Pasivos financieros y deudas")
    for p in datos["pasivos"]:
        print(f"      {p['concepto'][:58]:<58} {fmt(p['importe']):>15}  ({p['vencimiento']})")
    print(f"      total pasivo exigible {fmt(datos['exigible'])} · "
          f"vencimientos por año: {'declarados pendientes' if not datos['vencimientos'] else datos['vencimientos']}")
    for c in datos["proveedoresDetalle"][:4]:
        print(f"      · {c['etiqueta'][:56]:<56} {fmt(c['saldo'])}")
    nota(8, "Situación fiscal")
    print(f"      IVA repercutido {fmt(fiscal['ivaRepercutido'])} · IVA soportado {fmt(fiscal['ivaSoportado'])} · "
          f"saldo {fmt(fiscal['saldoIVA'])}")
    print(f"      retenciones (4751) {fmt(fiscal['retencionesIRPF'])} · otras fiscales {fmt(fiscal['otrasDeudasFiscales'])}")
    print(f"      base imponible (RAI) {fmt(fiscal['baseImponible'])} · cuota IS registrada "
          f"{fmt(fiscal['cuotaImpuestoSociedades'])} · cuota diferencial {fmt(fiscal['cuotaDiferencial'])}")
    nota(9, "Operaciones con partes vinculadas")
    print(f"      texto del asesor: {(datos['nota9'][:80] + '…') if datos['nota9'] else '(pendiente, a mano)'}")
    nota(10, "Otra información y medio ambiente")
    print(f"      otra información: {(datos['nota10'][:60] + '…') if datos['nota10'] else '(pendiente, a mano)'}")
    print(f"      medio ambiente:   {(datos['nota10MedioAmbiente'][:60] + '…') if datos['nota10MedioAmbiente'] else '(pendiente, a mano)'}")
    print(f"\n   AVISOS ({len(datos['avisos'])})")
    for a in datos["avisos"]:
        print(f"      ! {a[:150]}")


# ------------------------------------------------------------------ verificación
def main() -> int:
    print("=" * 84)
    print("Verificación del módulo memoria · REQ-08 Memoria de cuentas anuales (PGC PYME)")
    print("=" * 84)

    asientos_2025, l2025 = cargar(2025)
    asientos_2024, l2024 = cargar(2024)
    print(f"\nApuntes reales: {COD_EMPRESA} · 2025 {len(asientos_2025)} asientos / {len(l2025)} líneas · "
          f"2024 {len(asientos_2024)} asientos / {len(l2024)} líneas")
    if not l2025 or not l2024:
        print("ERROR: faltan fixtures")
        return 2

    # ---------------------------------------------------------------- [1] contrato
    print("\n[1] Contrato de módulos (backend/CONTRATO-MODULOS.md)")
    definicion = modulos.obtener("memoria")
    comprobar(definicion.disponible, f"el módulo carga en el registro ({definicion.error or 'sin errores'})")
    if not definicion.disponible:
        print("\nNo se puede seguir sin módulo.")
        return 1
    modulo = definicion.modulo
    comprobar(getattr(modulo, "NOMBRE", None) == "memoria", "NOMBRE == 'memoria'")
    comprobar(isinstance(modulo.TITULO, str) and modulo.TITULO.strip() != "", f"TITULO == {modulo.TITULO!r}")
    comprobar(modulo.INTERNO is False, "INTERNO is False (no es de uso interno)")
    comprobar(list(modulo.DESPLAZAMIENTOS) == [0, -1], "DESPLAZAMIENTOS == [0, -1]")
    comprobar(callable(modulo.calcular) and callable(modulo.informe_html),
              "exporta calcular(por_anio, ctx) e informe_html(datos, ctx)")
    comprobar(callable(getattr(modulo, "metricas_dashboard", None)), "exporta metricas_dashboard(datos)")
    parametros = getattr(modulo, "PARAMETROS", {})
    esperados = {"nota9", "nota10", "nota10MedioAmbiente", "administrador", "localidad", "fechaFormulacion"}
    comprobar(esperados <= set(parametros), f"PARAMETROS declara {sorted(parametros)}")
    comprobar(parametros.get("localidad") == "Madrid", "PARAMETROS['localidad'] por defecto 'Madrid'")

    # ---------------------------------------------------------------- [2] cálculo con datos reales
    ctx = {"empresa": EMPRESA, "cod_empresa": COD_EMPRESA, "year": 2025, "year_anterior": 2024,
           "nombre_mes": "septiembre", "trimestre": 3, "email": "", "administrador": "D. Pedro Núñez",
           "nota9": "Sin operaciones con partes vinculadas distintas de las retribuciones del administrador.",
           "nota10": "La sociedad no tiene avales ni compromisos con terceros al cierre.",
           "nota10MedioAmbiente": "La sociedad no ha realizado inversiones ni gastos medioambientales."}
    datos = modulo.calcular({2025: l2025, 2024: l2024}, ctx)
    html = modulo.informe_html(datos, ctx)
    imprimir_notas(datos)

    print("\n[2] Contrato de maquetación del HTML")
    comprobar(html.lstrip().startswith("<div"), "el HTML empieza por '<div'")
    comprobar("max-width:800px" in html, "ancho 800 px (el propio de la Memoria)")
    comprobar("font-size:11px" in html, "cuerpo de letra 11 px (el propio de la Memoria)")
    comprobar("Arial" in html and "style=" in html, "Arial y CSS inline")
    comprobar("ABGA Consultores" in html, "pie con el contacto de ABGA")
    comprobar("```" not in html and not re.search(r"(?m)^#{1,6} ", html), "sin markdown ni bloques de código")
    importes = re.findall(r">([-+]?[\d.]+,\d{2}) €<", html)
    comprobar(len(importes) > 50, f"importes en formato es-ES ({len(importes)} encontrados)")
    comprobar(len(html) > 20000, f"el informe tiene contenido ({len(html)} caracteres)")
    for n in range(1, 11):
        comprobar(f"Nota {n} ·" in html, f"el informe incluye la Nota {n}")
    comprobar(datos["nLineas"] == len(l2025) and datos["nLineasAnterior"] == len(l2024),
              f"informa de las líneas cargadas ({datos['nLineas']} y {datos['nLineasAnterior']})")

    # ---------------------------------------------------------------- [3] recálculo independiente
    print("\n[3] Contraste con un recálculo independiente de los apuntes crudos")
    ref25, ref24 = legado(2025, asientos_2025), legado(2024, asientos_2024, usa_estimacion=False)
    pares = [
        ("ventas", datos["ventas"], ref25["ventas"]),
        ("total de ingresos de explotación", datos["totalIngresos"], ref25["totalIng"]),
        ("amortizaciones", datos["amortizaciones"], ref25["amort"]),
        ("gastos financieros", datos["gastosFinancieros"], ref25["gastFin"]),
        ("RAI", datos["rai"], ref25["raiConPyg"]),
        ("resultado del ejercicio (sin estimar el IS)", datos["resultadoNeto"], ref25["resultadoReal"]),
        ("resultado del ejercicio anterior (apuntes de 2024)", datos["resultadoNetoAnt"], ref24["resultadoReal"]),
        ("inmovilizado intangible", datos["inmovIntangible"], ref25["inmovInt"]),
        ("inmovilizado material", datos["inmovMaterial"], ref25["inmovMat"]),
        ("clientes", datos["clientes"], ref25["clientes"]),
        ("tesorería", datos["tesoreria"], ref25["tesoreria"]),
        ("acreedores comerciales", datos["proveedores"], ref25["proveedores"]),
        ("deudas a corto plazo (52x)", datos["deudasCreditoCP"], ref25["deudasCP"]),
        ("IVA repercutido", datos["fiscal"]["ivaRepercutido"], ref25["ivaRepercutido"]),
        ("IVA soportado", datos["fiscal"]["ivaSoportado"], ref25["ivaSoportado"]),
        ("retenciones 4751", datos["fiscal"]["retencionesIRPF"], ref25["retenciones"]),
    ]
    for nombre, obtenido, esperado in pares:
        comprobar(cerca(obtenido, esperado), f"{nombre}: {fmt(obtenido)} == recálculo ({fmt(esperado)})")
    comprobar(cerca(ref25["rai"] - datos["rai"], ref25["gastos67"]),
              f"la única diferencia con el REQ-08 original es el grupo 67 que el original omitía "
              f"({fmt(ref25['gastos67'])}); la Memoria lo incluye, como el módulo pyg")

    # altas del inmovilizado = movimientos del año entre los apuntes, sin apertura
    altas_reales = sum(float(d.get("Debe") or 0)
                       for a in asientos_2025 if int(a.get("Fecha") or 0) != 20250101
                       for d in (a.get("Detalles") or [])
                       if any(str(d.get("Cuenta") or "").startswith(p)
                              for p in ("200", "201", "202", "203", "204", "205", "206", "207",
                                        "210", "211", "212", "213", "214", "215", "216", "217",
                                        "218", "219")))
    comprobar(cerca(sum(f["altasEjercicio"] for f in datos["inmovilizado"]), altas_reales),
              f"altas del inmovilizado: {fmt(sum(f['altasEjercicio'] for f in datos['inmovilizado']))} "
              f"== movimientos del ejercicio ({fmt(altas_reales)})")

    # cuadre del libro recalculado aquí
    debe = sum(float(d.get("Debe") or 0) for a in asientos_2025 for d in (a.get("Detalles") or []))
    haber = sum(float(d.get("Haber") or 0) for a in asientos_2025 for d in (a.get("Detalles") or []))
    comprobar(cerca(datos["integridad"]["cuadre"]["debe"], debe)
              and cerca(datos["integridad"]["cuadre"]["haber"], haber),
              f"ΣDebe y ΣHaber del libro ({fmt(debe)} / {fmt(haber)})")

    # ---------------------------------------------------------------- [4] sin estimaciones inventadas
    print("\n[4] Control de las estimaciones que se han eliminado del workflow original")
    comprobar(cerca(datos["impuesto"], ref25["impuestoReal"]),
              f"el gasto por impuesto es el saldo real de la 630 ({fmt(ref25['impuestoReal'])}), "
              f"no el 25 % del RAI ({fmt(ref25['impuestoEstimado25'])})")
    comprobar(not cerca(datos["resultadoNeto"], ref25["resultadoCon25"], tol=1.0),
              f"el resultado ({fmt(datos['resultadoNeto'])}) NO es el del original con el 25 % "
              f"({fmt(ref25['resultadoCon25'])})")
    comprobar(not cerca(datos["resultadoNetoAnt"], ref24["rai"] - ref24["rai"] * 0.25, tol=1.0),
              "el resultado del ejercicio anterior sale de los apuntes de 2024, no del 25 % del RAI")
    comprobar(all(f["saldoInicial"] is None and f["saldoFinal"] is None for f in datos["inmovilizado"]),
              "el saldo inicial y el final del inmovilizado no se estiman (quedan a None hasta completarlos a mano)")
    comprobar(cerca(sum(f["saldoApuntes"] for f in datos["inmovilizado"]),
                    ref25["inmovInt"] + ref25["inmovMat"]),
              f"el saldo del inmovilizado es el de los apuntes "
              f"({fmt(sum(f['saldoApuntes'] for f in datos['inmovilizado']))})")
    comprobar(not cerca(sum(f["dotacionEjercicio"] for f in datos["inmovilizado"]),
                        ref25["inmovDotacionInventada"], tol=1.0),
              "la dotación del inmovilizado no es el 20 %/15 % inventado del original")
    comprobar(datos["vencimientos"] == [] and "Año 1" in html,
              "el reparto de vencimientos por año no se estima: sale en blanco con su aviso")
    celdas_pendientes = html.count('color:#8a95a6">—<')
    comprobar(celdas_pendientes >= 5, f"el informe marca con «—» las celdas no obtenibles ({celdas_pendientes})")
    comprobar(all(isinstance(a, str) for a in datos["avisos"]) and len(datos["avisos"]) >= 6,
              f"datos['avisos'] es una lista de {len(datos['avisos'])} strings")
    comprobar(any("a mano" in a for a in datos["avisos"]),
              "los avisos dicen explícitamente qué cuadro requiere completarse a mano")
    comprobar(any("25 %" in a or "25%" in a for a in datos["avisos"]),
              "los avisos explican que ya no se estima el 25 % del RAI")
    comprobar(any("20 %" in a for a in datos["avisos"]),
              "los avisos explican que ya no se reparten los vencimientos al 20 %")
    comprobar(all(a.split(".")[0][:40] in html or a[:40].split(",")[0] in html for a in datos["avisos"]),
              "los avisos también están escritos en el informe")
    comprobar("requiere completarse a mano" in html, "el informe dice qué requiere completarse a mano")

    # ---------------------------------------------------------------- [5] parámetros por defecto
    print("\n[5] Parámetros por defecto (los del workflow original)")
    ctx_sin = {"empresa": EMPRESA, "cod_empresa": COD_EMPRESA, "year": 2025, "year_anterior": 2024}
    datos_sin = modulo.calcular({2025: l2025, 2024: l2024}, ctx_sin)
    html_sin = modulo.informe_html(datos_sin, ctx_sin)
    comprobar(datos_sin["localidad"] == "Madrid", "sin parámetros, localidad = 'Madrid'")
    comprobar(datos_sin["fechaFormulacion"] == "31 de marzo de 2025",
              f"sin parámetros, formulación = {datos_sin['fechaFormulacion']!r}")
    comprobar(html_sin.startswith("<div"), "el informe con los valores por defecto también empieza por '<div'")
    comprobar(any("Nota 9" in a or "Nota 10" in a for a in datos_sin["avisos"]),
              "sin texto del asesor, las notas manuales se declaran pendientes")
    comprobar(cerca(datos_sin["totalIngresos"], datos["totalIngresos"]),
              "los números no cambian al no pasar parámetros")

    # ---------------------------------------------------------------- [6] coherencia con pyg
    print("\n[6] Coherencia con el informe de Balance y PyG (mismo ejercicio, mismas cifras)")
    try:
        pyg = modulos.obtener("pyg").modulo
        p = pyg.calcular({2025: l2025, 2024: l2024}, ctx)
        for clave in ("totalIngresos", "resultadoNeto", "totalActivo", "inmovIntangible",
                      "inmovMaterial", "tesoreria", "proveedoresSaldo"):
            comprobar(cerca(datos[clave if clave != "proveedoresSaldo" else "proveedores"], p[clave]),
                      f"{clave}: memoria {fmt(datos.get(clave, datos.get('proveedores', 0)))} == "
                      f"pyg {fmt(p[clave])}")
    except Exception as e:  # el módulo pyg puede estar en obras: no invalida la Memoria
        print(f"   · no se pudo contrastar con pyg ({type(e).__name__}: {e})")

    # ---------------------------------------------------------------- [7] determinismo y utilidades
    print("\n[7] Determinismo, métricas y salida")
    datos2 = modulo.calcular({2025: l2025, 2024: l2024}, ctx)
    comprobar(datos2["resultadoNeto"] == datos["resultadoNeto"]
              and datos2["totalActivo"] == datos["totalActivo"], "dos ejecuciones dan la misma cifra")
    comprobar(html == modulo.informe_html(datos, ctx), "el HTML es determinista")
    metricas = modulo.metricas_dashboard(datos)
    comprobar(isinstance(metricas, dict) and all(isinstance(v, (int, float)) for v in metricas.values()),
              f"metricas_dashboard devuelve {len(metricas)} cifras numéricas")
    ruta_html = Path("/tmp/memoria_6091_2025.html")
    ruta_html.write_text(html, encoding="utf-8")
    print(f"   · HTML guardado en {ruta_html} ({len(html)} caracteres)")
    datos_json = json.dumps(datos, default=str)
    comprobar(len(datos_json) > 2000 and '"avisos"' in datos_json,
              f"datos serializa a JSON para el portal ({len(datos_json)} caracteres)")

    # ---------------------------------------------------------------- resumen
    print("\n" + "=" * 84)
    print("Resumen de la Memoria del ejercicio 2025")
    print("-" * 84)
    print(f"   Ingresos de explotación        {fmt(datos['totalIngresos']):>16}")
    print(f"   Resultado antes de impuestos   {fmt(datos['rai']):>16}")
    print(f"   Impuesto sobre sociedades      {fmt(datos['impuesto']):>16}   (saldo real de la 630)")
    print(f"   Resultado del ejercicio        {fmt(datos['resultadoNeto']):>16}")
    print(f"   Total activo                   {fmt(datos['totalActivo']):>16}")
    print(f"   Patrimonio neto                {fmt(datos['patrimonioNeto']):>16}")
    print(f"   Pasivo exigible                {fmt(datos['exigible']):>16}")
    print(f"   Avisos / notas a mano          {len(datos['avisos']):>16}")
    print("-" * 84)
    print(f"{comprobaciones - len(fallos)}/{comprobaciones} comprobaciones correctas")
    if fallos:
        print(f"FALLOS ({len(fallos)}):")
        for f in fallos:
            print(f"   · {f}")
        return 1
    print("OK: módulo memoria verificado (contrato, HTML 800/11 px, 10 notas y sin estimaciones "
          "inventadas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
