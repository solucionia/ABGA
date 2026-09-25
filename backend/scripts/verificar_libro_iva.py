#!/usr/bin/env python
"""Verificación del módulo `libro_iva` (Libro de IVA repercutido y soportado).

Recalcula el libro **desde los apuntes crudos** (el JSON tal cual lo da el ERP: `Cuenta`, `Debe`,
`Haber`, `Fecha`, `Serie`, `Documento`), sin usar ninguna primitiva del módulo, y lo contrasta
movimiento a movimiento, mes a mes y trimestre a trimestre con lo que devuelve `libro_iva`.
Después comprueba el contrato de módulos y la maquetación del HTML.

Datos: `fixtures/apuntes_6091_2025.json` (ejercicio completo), `fixtures/apuntes_6091_2024.json`
(parcial, con abonos en negativo) y, si está en la caché local, la empresa 6221/2025 (8.708
asientos), que es el caso grande. **No se llama al ERP**: los fixtures y la caché son locales y
`cache.leer_apuntes()` con `ttl=-1` sólo lee SQLite (devuelve None si no está).

Uso:  cd <raíz del proyecto> && ./.venv/bin/python backend/scripts/verificar_libro_iva.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import modulos                        # noqa: E402
from app.ledger import fmt, fmt_pct, lineas_de_asientos  # noqa: E402

TOLERANCIA = 0.05          # el módulo redondea a céntimos
P_REP, P_SOP = "477", "472"
P_ING, P_GAS = "7", "6"

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


def informes_esc(texto: str) -> str:
    """Escapado del informe: los avisos se pintan escapados, hay que buscarlos así."""
    from app.informes import esc
    return esc(texto)


def cerca(a, b, tol: float = TOLERANCIA) -> bool:
    return abs(float(a or 0) - float(b or 0)) <= tol


# ---------------------------------------------------------------- recálculo crudo (independiente)

def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def recalcular(asientos: list[dict]) -> dict:
    """Libro de IVA recalculado a mano desde los asientos crudos del ERP.

    Reproduce a propósito las mismas reglas declaradas por el módulo (agrupar por asiento, cuota
    neta de 472/477, base = cuentas 6xx/7xx del propio asiento), pero sin reutilizar su código:
    así el contraste vale como comprobación independiente.
    """
    por_asiento: dict[tuple, list[dict]] = {}
    for a in asientos:
        for d in a.get("Detalles") or []:
            if not d.get("Fecha"):     # mismo relleno que hace ledger.lineas_de_asientos
                d = {**d, "Fecha": a.get("Fecha"),
                     "Documento": d.get("Documento") or a.get("Documento"),
                     "Serie": d.get("Serie") or a.get("Serie")}
            clave = (int(d.get("Fecha") or 0), str(d.get("Serie") or ""), str(d.get("Documento") or ""))
            por_asiento.setdefault(clave, []).append(d)

    movs: list[dict] = []
    cuota_total = [0.0, 0.0]           # [repercutido, soportado] de TODAS las líneas 472/477
    for (fecha, serie, doc), ds in por_asiento.items():
        l_rep = [d for d in ds if str(d.get("Cuenta") or "").startswith(P_REP)]
        l_sop = [d for d in ds if str(d.get("Cuenta") or "").startswith(P_SOP)]
        for d in l_rep:
            cuota_total[0] += _num(d.get("Haber")) - _num(d.get("Debe"))
        for d in l_sop:
            cuota_total[1] += _num(d.get("Debe")) - _num(d.get("Haber"))
        if not l_rep and not l_sop:
            continue
        hay_ing = any(str(d.get("Cuenta") or "").startswith(P_ING) for d in ds)
        hay_gas = any(str(d.get("Cuenta") or "").startswith(P_GAS) for d in ds)
        base_rep = sum(_num(d.get("Haber")) - _num(d.get("Debe")) for d in ds
                       if str(d.get("Cuenta") or "").startswith(P_ING))
        base_sop = sum(_num(d.get("Debe")) - _num(d.get("Haber")) for d in ds
                       if str(d.get("Cuenta") or "").startswith(P_GAS))
        for tipo, lineas, base, derivable in (("R", l_rep, base_rep, hay_ing),
                                              ("S", l_sop, base_sop, hay_gas)):
            if not lineas:
                continue
            cuota = sum((_num(d.get("Haber")) - _num(d.get("Debe"))) if tipo == "R"
                        else (_num(d.get("Debe")) - _num(d.get("Haber"))) for d in lineas)
            if abs(cuota) < 0.005:
                continue
            movs.append({"tipo": tipo, "clave": (fecha, serie, doc), "fecha": fecha,
                         "cuota": round(cuota, 2), "base": round(base, 2) if derivable else None,
                         "mes": (fecha // 100) % 100, "trimestre": ((fecha // 100) % 100 - 1) // 3 + 1
                         if (fecha // 100) % 100 else 0})

    def bloque(ms: list[dict]) -> dict:
        rep = sum(m["cuota"] for m in ms if m["tipo"] == "R")
        sop = sum(m["cuota"] for m in ms if m["tipo"] == "S")
        return {
            "repercutido": round(rep, 2), "soportado": round(sop, 2), "diferencia": round(rep - sop, 2),
            "baseRepercutida": round(sum(m["base"] for m in ms if m["tipo"] == "R" and m["base"] is not None), 2),
            "baseSoportada": round(sum(m["base"] for m in ms if m["tipo"] == "S" and m["base"] is not None), 2),
            "nMovimientos": len(ms),
            "nSinBase": sum(1 for m in ms if m["base"] is None),
        }

    del_trimestre = {q: [m for m in movs if m["trimestre"] == q] for q in (1, 2, 3, 4)}
    por_mes = {m: [x for x in movs if x["mes"] == m] for m in range(1, 13)}
    return {
        "movs": movs,
        "total": bloque(movs),
        "porTrimestre": {q: bloque(del_trimestre[q]) for q in (1, 2, 3, 4)},
        "porMes": {m: bloque(por_mes[m]) for m in range(1, 13)},
        "cuota_lineas_472_477": (round(cuota_total[0], 2), round(cuota_total[1], 2)),
        "sin_fecha": [m for m in movs if not m["trimestre"]],
    }


# ---------------------------------------------------------------- contraste módulo vs crudo

def contrastar_anio(nombre: str, asientos: list[dict], modulo, year: int, trimestre=None) -> dict:
    """Contrasta el módulo con el recálculo crudo para un ejercicio. Devuelve el HTML y los datos."""
    print(f"\n[contraste] {nombre} — {len(asientos)} asientos crudos")
    crudo = recalcular(asientos)
    lineas = lineas_de_asientos(asientos)
    ctx = {"empresa": "empresa de prueba", "cod_empresa": "0000", "year": year,
           "year_anterior": year - 1, "nombre_mes": "septiembre", "trimestre": trimestre, "email": ""}
    datos = modulo.calcular({year: lineas}, ctx)
    html = modulo.informe_html(datos, ctx)

    total = crudo["total"]
    print(f"   {len(lineas)} líneas · {total['nMovimientos']} movimientos de IVA "
          f"({total['nSinBase']} sin base derivable)")
    print(f"   repercutido {fmt(total['repercutido'])} · soportado {fmt(total['soportado'])} · "
          f"diferencia {fmt(total['diferencia'])}")

    comprobar(cerca(datos["ivaRepercutido"], total["repercutido"]),
              f"IVA repercutido == recálculo crudo ({fmt(total['repercutido'])})")
    comprobar(cerca(datos["ivaSoportado"], total["soportado"]),
              f"IVA soportado == recálculo crudo ({fmt(total['soportado'])})")
    comprobar(cerca(datos["ivaDiferencia"], total["diferencia"]),
              f"diferencia == repercutido − soportado ({fmt(total['diferencia'])})")
    comprobar(cerca(datos["ivaDiferencia"], round(datos["ivaRepercutido"] - datos["ivaSoportado"], 2)),
              "la diferencia cuadra con las dos cuotas del propio informe")
    comprobar(datos["nMovimientos"] == total["nMovimientos"],
              f"n.º de movimientos == recálculo crudo ({total['nMovimientos']})")
    comprobar(datos["nSinBase"] == total["nSinBase"],
              f"movimientos sin base derivable == recálculo crudo ({total['nSinBase']})")
    comprobar(cerca(datos["baseRepercutida"], total["baseRepercutida"]) and
              cerca(datos["baseSoportada"], total["baseSoportada"]),
              f"bases derivadas == recálculo crudo ({fmt(total['baseRepercutida'])} / "
              f"{fmt(total['baseSoportada'])})")
    # las cuotas del libro tienen que ser las de las cuentas 472/477, sin recortes ni signos cambiados
    comprobar(cerca(total["repercutido"], crudo["cuota_lineas_472_477"][0]) and
              cerca(total["soportado"], crudo["cuota_lineas_472_477"][1]),
              "las cuotas del ejercicio son exactamente Σ477(haber−debe) y Σ472(debe−haber) de los apuntes")
    if total["diferencia"] > 0:
        esperado = "A ingresar"
    elif total["diferencia"] < 0:
        esperado = "A compensar o a devolver"
    else:
        esperado = "Cero"
    comprobar(datos["resultado"] == esperado, f"lectura de la diferencia: {esperado}")

    # ---- movimiento a movimiento ----
    movs_mod = modulo.movimientos_de(lineas)
    clave = lambda m: (m["fecha"], m["serie"], m["documento"], m["tipo"])  # noqa: E731
    a_mod = {clave(m): m for m in movs_mod}
    a_crudo = {(m["fecha"], m["clave"][1], m["clave"][2], m["tipo"]): m for m in crudo["movs"]}
    comprobar(len(a_mod) == len(a_crudo) == len(crudo["movs"]),
              f"mismo número de movimientos que el recálculo ({len(a_crudo)})")
    comprobar(set(a_mod) == set(a_crudo), "los mismos asientos y signos, ni uno de más ni de menos")
    dif_cuota = [k for k in a_crudo if k in a_mod and not cerca(a_mod[k]["cuota"], a_crudo[k]["cuota"])]
    comprobar(not dif_cuota, f"cuota idéntica en los {len(a_crudo)} movimientos")
    dif_base = [k for k in a_crudo if k in a_mod
                and ((a_mod[k]["base"] is None) != (a_crudo[k]["base"] is None)
                     or (a_mod[k]["base"] is not None and not cerca(a_mod[k]["base"], a_crudo[k]["base"])))]
    comprobar(not dif_base, "base idéntica (y vacía donde corresponde) en todos los movimientos")
    vacias_mal = [k for k, v in a_mod.items() if v["base"] is None and v["tipo_pct"] is not None]
    comprobar(not vacias_mal, "si no hay base derivable, el tipo también se deja vacío")
    tipos_malos = [k for k, v in a_mod.items()
                   if v["base"] and v["tipo_pct"] is not None and not cerca(v["tipo_pct"], v["cuota"] / v["base"] * 100, 0.02)]
    comprobar(not tipos_malos, "el tipo es exactamente cuota ÷ base (sin tipos teóricos)")

    # ---- por mes y por trimestre ----
    for m in range(1, 13):
        esperado_m = crudo["porMes"][m]
        obtenido = next(x for x in datos["porMes"] if x["mes"] == m)
        if not (cerca(obtenido["repercutido"], esperado_m["repercutido"]) and
                cerca(obtenido["soportado"], esperado_m["soportado"]) and
                cerca(obtenido["diferencia"], esperado_m["diferencia"]) and
                obtenido["nMovimientos"] == esperado_m["nMovimientos"]):
            comprobar(False, f"mes {m}: cuotas y diferencia == recálculo crudo")
            break
    else:
        comprobar(True, "los 12 meses cuadran con el recálculo crudo (cuotas, diferencia y n.º de movimientos)")
    for q in (1, 2, 3, 4):
        esperado_t = crudo["porTrimestre"][q]
        obtenido = next(x for x in datos["porTrimestre"] if x["trimestre"] == q)
        if not (cerca(obtenido["repercutido"], esperado_t["repercutido"]) and
                cerca(obtenido["soportado"], esperado_t["soportado"]) and
                cerca(obtenido["baseRepercutida"], esperado_t["baseRepercutida"]) and
                cerca(obtenido["baseSoportada"], esperado_t["baseSoportada"]) and
                obtenido["nSinBase"] == esperado_t["nSinBase"]):
            comprobar(False, f"{q}T: cuotas, bases y movimientos sin base == recálculo crudo")
            break
    else:
        comprobar(True, "los cuatro trimestres cuadran con el recálculo crudo (cuotas, bases y sin-base)")
    suma_t = round(sum(x["diferencia"] for x in datos["porTrimestre"]), 2)
    esperado_suma = round(sum(crudo["porTrimestre"][q]["diferencia"] for q in (1, 2, 3, 4)), 2)
    comprobar(cerca(suma_t, esperado_suma),
              f"la suma de las diferencias trimestrales cuadra ({fmt(esperado_suma)})")
    if not crudo["sin_fecha"]:
        comprobar(cerca(suma_t, datos["ivaDiferencia"]),
                  "sin movimientos sin fecha: la suma trimestral es la del ejercicio")

    # ---- detalle: subtotales y recortes declarados ----
    comprobar(len(datos["detalle"]) == (4 if trimestre is None else 1),
              f"el detalle trae {'los cuatro trimestres' if trimestre is None else 'sólo el trimestre pedido'} "
              f"({len(datos['detalle'])})")
    for d in datos["detalle"]:
        esperado_t = crudo["porTrimestre"][d["trimestre"]]
        comprobar(cerca(d["repercutido"], esperado_t["repercutido"]) and
                  cerca(d["soportado"], esperado_t["soportado"]),
                  f'{d["trimestre"]}T: el subtotal del detalle es la cuota del trimestre '
                  f'({fmt(esperado_t["repercutido"])} / {fmt(esperado_t["soportado"])})')
        comprobar(len(d["filasRepercutido"]) == d["listadosRepercutido"] and
                  len(d["filasSoportado"]) == d["listadosSoportado"],
                  f'{d["trimestre"]}T: se listan {d["listadosRepercutido"]}+{d["listadosSoportado"]} '
                  f'movimientos de {d["nRepercutido"]}+{d["nSoportado"]} (recorte declarado)')
        comprobar(d["listadosRepercutido"] <= d["nRepercutido"] and d["listadosSoportado"] <= d["nSoportado"],
                  f'{d["trimestre"]}T: nunca se listan más movimientos de los que hay')
        if d["listadosSoportado"] < d["nSoportado"]:
            comprobar(any(f'{d["trimestre"]}T soportado' in a for a in datos["avisos"]),
                      f'{d["trimestre"]}T: el recorte del detalle se declara en un aviso')

    # ---------------- contrato del HTML ----------------
    print("   — HTML —")
    comprobar(html.startswith("<div"), "el HTML empieza por '<div'")
    comprobar("```" not in html and not re.search(r"(?m)^#{1,6} ", html),
              "sin markdown ni bloques de código")
    comprobar("font-family:Arial" in html and "font-size:13px" in html, "Arial 13 px")
    comprobar("max-width:780px" in html, "ancho máximo 780 px")
    comprobar("#1a4b8c" in html and "#c62828" in html and "#2e7d32" in html,
              "colores de cabecera, negativos y positivos")
    comprobar("ABGA Consultores" in html and "USO INTERNO" not in html,
              "pie de cliente (no es informe interno)")
    importes = re.findall(r">(-?[\d.]+,\d{2}) €<", html)
    comprobar(len(importes) > 20, f"importes en formato es-ES como valor propio de su celda ({len(importes)})")
    comprobar(all(re.fullmatch(r"-?\d{1,3}(\.\d{3})*,\d{2}", i) for i in importes),
              "todos los importes van con separador de miles español")
    comprobar(not re.search(r">\d{1,3},\d{3}\.\d{2}", html),
              "no hay importes en formato anglosajón (1,234.56)")
    for q in (1, 2, 3, 4):
        if trimestre is None or trimestre == q:
            comprobar(f"Subtotal {q}T" in html, f"el detalle lleva subtotal del {q}T")
    comprobar(all(f"{q}T" in html for q in (1, 2, 3, 4)),
              "el resumen muestra los cuatro trimestres aunque no se listen todos")
    comprobar("TOTAL" in html, "el resumen lleva el total del ejercicio")
    comprobar("contrapartida" in html.lower() and "6xx" in html and "7xx" in html,
              "el informe declara de dónde se deriva la base")
    # el tipo medio que declara el informe se recalcula aquí desde los movimientos con base
    con_base = [m for m in movs_mod if m["base"] is not None]
    base_cb = sum(m["base"] for m in con_base)
    cuota_cb = sum(m["cuota"] for m in con_base)
    comprobar(cerca(datos["cuotaConBaseRepercutido"],
                    sum(m["cuota"] for m in con_base if m["tipo"] == "R")) and
              cerca(datos["cuotaConBaseSoportado"],
                    sum(m["cuota"] for m in con_base if m["tipo"] == "S")),
              "las cuotas con base derivada cuadran con los movimientos del propio módulo")
    if base_cb:
        comprobar(fmt_pct(cuota_cb / base_cb * 100) in html,
                  f"el tipo medio declarado ({fmt_pct(cuota_cb / base_cb * 100)}) es Σ cuota ÷ Σ base")
    comprobar("303" in html, "el informe recuerda que no es el modelo 303 presentado")
    comprobar(html.count("<table") >= (4 if trimestre is None else 3),
              f"hay {html.count('<table')} tablas (resumen, meses, método y detalle)")
    if datos["nSinBase"]:
        comprobar("sin base derivable" in html, "el informe avisa de los movimientos sin base")
    return {"datos": datos, "html": html, "crudo": crudo}


# ---------------------------------------------------------------- main

def cargar_fixture(year: int) -> list[dict] | None:
    ruta = RAIZ / "fixtures" / f"apuntes_6091_{year}.json"
    if not ruta.exists():
        return None
    return json.loads(ruta.read_text(encoding="utf-8"))["asientos"]


def main() -> int:
    print("=" * 78)
    print("Verificación del módulo libro_iva · empresa 6091 (MB Dommo) y caché local")
    print("=" * 78)

    print("\n[1] Contrato del módulo")
    definicion = modulos.obtener("libro_iva")
    comprobar(definicion.disponible, f"el módulo carga ({definicion.error or 'sin errores'})")
    modulo = definicion.modulo
    comprobar(getattr(modulo, "NOMBRE", None) == "libro_iva", "NOMBRE == 'libro_iva'")
    comprobar(getattr(modulo, "TITULO", None) == "Libro de IVA", f"TITULO == {getattr(modulo, 'TITULO', None)!r}")
    comprobar(getattr(modulo, "INTERNO", None) is False, "INTERNO is False")
    comprobar(list(getattr(modulo, "DESPLAZAMIENTOS", [])) == [0], "DESPLAZAMIENTOS == [0]")
    comprobar(getattr(modulo, "PARAMETROS", None) == {"trimestre": None},
              f"PARAMETROS == {{'trimestre': None}} ({getattr(modulo, 'PARAMETROS', None)})")
    comprobar(callable(getattr(modulo, "calcular", None)), "exporta calcular(por_anio, ctx)")
    comprobar(callable(getattr(modulo, "informe_html", None)), "exporta informe_html(datos, ctx)")
    comprobar(callable(getattr(modulo, "metricas_dashboard", None)), "exporta metricas_dashboard(datos)")

    fuente = (RAIZ / "backend" / "app" / "modulos" / "libro_iva.py").read_text(encoding="utf-8")
    comprobar(not re.search(r"\b(import|from)\s+.*\b(apicon|cache)\b", fuente),
              "el módulo no importa el cliente del ERP ni la caché")
    comprobar("requests" not in fuente and "sqlite" not in fuente, "no hay acceso a red ni a base de datos")
    comprobar("print(" not in fuente, "el módulo no escribe por pantalla (los avisos van en datos['avisos'])")

    asientos_25 = cargar_fixture(2025)
    if not asientos_25:
        print("FALTAN FIXTURES: ejecuta backend/scripts/traer_ejercicio.py")
        return 2

    print("\n[2] Libro de IVA 2025 (los cuatro trimestres) contrastado con los apuntes crudos")
    r25 = contrastar_anio("fixture 6091/2025 (completo)", asientos_25, modulo, 2025, None)
    metricas = modulo.metricas_dashboard(r25["datos"])
    comprobar(set(metricas) == {"ivaRepercutido", "ivaSoportado", "ivaDiferencia", "n_movimientos"},
              f"metricas_dashboard devuelve exactamente las cuatro claves pedidas ({sorted(metricas)})")
    comprobar(cerca(metricas["ivaDiferencia"], r25["datos"]["ivaDiferencia"]) and
              metricas["n_movimientos"] == r25["datos"]["nMovimientos"],
              "las métricas del panel coinciden con el informe")
    comprobar(all(isinstance(r25["datos"].get(k), (int, float)) for k in
                  ("ivaRepercutido", "ivaSoportado", "ivaDiferencia", "baseRepercutida",
                   "baseSoportada", "nMovimientos", "nSinBase")),
              "los agregados del contrato son números, no texto formateado")
    comprobar(isinstance(r25["datos"].get("avisos"), list) and
              all(isinstance(a, str) for a in r25["datos"]["avisos"]),
              f"datos['avisos'] es una lista de strings ({len(r25['datos']['avisos'])} avisos)")
    texto_avisos = " ".join(r25["datos"]["avisos"]).lower()
    comprobar("contabilizado" in texto_avisos and "303" in texto_avisos,
              "un aviso recuerda que es IVA contabilizado, no la declaración presentada")
    comprobar("contrapartida" in texto_avisos and "derivar" in texto_avisos,
              "un aviso declara el método (base derivada de la contrapartida)")
    comprobar("no se han estimado" in texto_avisos,
              "un aviso deja claro que las bases que no se pueden derivar no se estiman")

    print("\n[3] Parámetro `trimestre`")
    for valor, esperados in ((None, [1, 2, 3, 4]), (3, [3]), ("2", [2]), ("Q4", [4]), (7, [1, 2, 3, 4])):
        ctx = {"year": 2025, "trimestre": valor}
        datos = modulo.calcular({2025: lineas_de_asientos(asientos_25)}, ctx)
        comprobar(datos["trimestres_mostrados"] == esperados,
                  f"trimestre={valor!r} → detalle de {esperados}")
        if valor == 7:
            comprobar(any("no se reconoce" in a for a in datos["avisos"]),
                      "un trimestre inválido se declara en vez de adivinar")
        comprobar(cerca(datos["ivaRepercutido"], r25["datos"]["ivaRepercutido"]),
                  f"trimestre={valor!r}: el resumen del ejercicio no cambia con el parámetro")

    print("\n[4] Ejercicio 2024 del fixture (parcial, con abonos en negativo)")
    asientos_24 = cargar_fixture(2024)
    if asientos_24:
        contrastar_anio("fixture 6091/2024 (parcial)", asientos_24, modulo, 2024, None)
    else:
        print("   (no hay fixture de 2024; se omite)")

    print("\n[5] Más libros reales desde la caché local (sin tocar el ERP)")
    casos_cache = [("6221", 2025), ("6091", 2026), ("1092", 2025)]
    try:
        from app import cache  # noqa: E402  (la caché sólo la usa el verificador)
    except Exception as e:                        # configuración ausente…
        cache = None
        print(f"   (no se pudo usar la caché local: {type(e).__name__}: {e})")
    for empresa, ejercicio in casos_cache if cache else []:
        guardado = cache.leer_apuntes(empresa, ejercicio, ttl=-1)
        if not guardado or not guardado.get("asientos"):
            print(f"   ({empresa}/{ejercicio} no está en la caché; se omite)")
            continue
        print(f"   caché {empresa}/{ejercicio}: {len(guardado['asientos'])} asientos guardados")
        r = contrastar_anio(f"caché {empresa}/{ejercicio}", guardado["asientos"], modulo, ejercicio, None)
        kb = len(r["html"]) / 1024
        print(f"   → HTML de {kb:.0f} KB con el detalle recortado y declarado")
        comprobar(kb < 700, f"{empresa}/{ejercicio}: el HTML se mantiene manejable ({kb:.0f} KB)")
        if r["datos"]["nMovimientos"] > r25["datos"]["nMovimientos"]:
            comprobar(True, f"{empresa}/{ejercicio}: {r['datos']['nMovimientos']} movimientos de IVA "
                            f"(más que el fixture de 2025)")

    print("\n[6] Casos límite (no revientan y no inventan)")
    ctx_vacio = {"year": 2025, "trimestre": None}
    datos_vacio = modulo.calcular({2025: []}, ctx_vacio)
    html_vacio = modulo.informe_html(datos_vacio, ctx_vacio)
    comprobar(datos_vacio["nMovimientos"] == 0 and datos_vacio["ivaRepercutido"] == 0,
              "un ejercicio sin apuntes devuelve todo a cero")
    comprobar(html_vacio.startswith("<div") and "0,00 €" in html_vacio,
              "el informe de un ejercicio vacío se pinta igual (con ceros)")
    comprobar(any("No hay apuntes" in a for a in datos_vacio["avisos"]),
              "y lo declara en vez de callarse")
    datos_lista = modulo.calcular(lineas_de_asientos(asientos_25), ctx_vacio)
    comprobar(datos_lista["nMovimientos"] == r25["datos"]["nMovimientos"],
              "acepta también las líneas sueltas (no sólo el diccionario por ejercicio)")
    datos_otro = modulo.calcular({2024: lineas_de_asientos(asientos_25)}, {"year": 2025, "trimestre": None})
    comprobar(datos_otro["nMovimientos"] == r25["datos"]["nMovimientos"] and
              any("ejercicio" in a for a in datos_otro["avisos"]),
              "si no llegan los apuntes del ejercicio pedido lo usa el que hay y lo declara")

    print("\n[7] Aviso que el informe pinta de verdad")
    html = r25["html"]
    for aviso in r25["datos"]["avisos"]:
        comprobar(informes_esc(aviso[:60]) in html, f"el informe muestra el aviso «{aviso[:52]}…»")

    print("\n" + "=" * 78)
    print(f"{comprobaciones - len(fallos)}/{comprobaciones} comprobaciones correctas")
    if fallos:
        print(f"FALLOS ({len(fallos)}):")
        for f in fallos:
            print("   ·", f)
        return 1
    print("OK: módulo libro_iva verificado (contrato, contraste con los apuntes crudos y HTML)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
