#!/usr/bin/env python
"""Verificación del módulo `libro_retenciones` (libro de retenciones por periodos).

Recalcula el libro **desde los apuntes crudos** (los `Detalles` del fixture, sin pasar por el
módulo: ni `Linea`, ni sus funciones) y comprueba que los números del módulo coinciden:

  1. el contrato de `CONTRATO-MODULOS.md` (NOMBRE, TITULO, INTERNO, DESPLAZAMIENTOS, PARAMETROS,
     calcular / informe_html / metricas_dashboard);
  2. cuota de cada movimiento, totales por bloque y por trimestre, número de movimientos;
  3. **completeness**: devengos + movimientos no retenidos = saldo de cada cuenta de Hacienda
     del ejercicio (ningún apunte se pierde por el camino);
  4. la base derivada y el tipo (%) de cada movimiento, recalculados a mano;
  5. el HTML: `<div`, Arial 13px, 780px, importes es-ES que salen como importe propio de su celda,
     modelos 111/115, aviso de que son retenciones contabilizadas y no declaraciones;
  6. el parámetro `trimestre` (None = los cuatro; 1-4 = sólo ese, también «Q3» o «3T»);
  7. `metricas_dashboard` con las cuatro claves pedidas y sus valores;
  8. el mismo cálculo contra una segunda empresa real de la caché local (6221, 2025), si está,
     para que no se verifique con un único libro (nunca se llama al ERP: `ttl=-1`).

Uso:  cd <raíz del proyecto> && ./.venv/bin/python backend/scripts/verificar_libro_retenciones.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import modulos                                   # noqa: E402
from app.ledger import fmt, fmt_pct, lineas_de_asientos, saldos_por_cuenta  # noqa: E402

TOLERANCIA = 0.02
COD_EMPRESA, EMPRESA = "6091", "MB Dommo, S.L."

CUENTAS_LIBRO = ("4751", "4752", "4750", "4759", "473")
FAMILIA_TRABAJO = ("64",)
FAMILIA_PROFESIONAL = ("60", "62")

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
    return abs(float(a or 0) - float(b or 0)) <= tol


# ---------------------------------------------------------------- recálculo independiente

def _n(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _raiz(cuenta: str) -> str:
    return "473" if cuenta.startswith("473") else str(cuenta)[:4]


def _trimestre(fecha: int) -> int:
    mes = (int(fecha or 0) // 100) % 100
    return (mes - 1) // 3 + 1 if mes else 0


def recalcular(asientos: list[dict]) -> dict:
    """Libro de retenciones recalculado a mano sobre los apuntes crudos.

    Mismas reglas que declara el módulo (apertura/cierre fuera, cuota = saldo de la cuenta en el
    asiento, base = contrapartida del asiento, devengo = con contrapartida de renta), pero
    implementadas aquí desde cero para que la comprobación sea de verdad independiente.
    """
    grupos: dict[tuple, list[dict]] = {}
    for a in asientos:
        for d in a.get("Detalles") or []:
            fila = dict(d)
            fila.setdefault("Fecha", a.get("Fecha"))
            fila["Serie"] = fila.get("Serie") or a.get("Serie") or ""
            fila["Documento"] = fila.get("Documento") or a.get("Documento") or ""
            fila["Descripcion"] = fila.get("Descripcion") or a.get("Descripcion") or ""
            grupos.setdefault((str(fila["Serie"]), str(fila["Documento"])), []).append(fila)

    movimientos, otros = [], []
    n_apertura = n_cierre = 0
    saldo_cuenta: dict[str, float] = {}

    for clave, lineas in grupos.items():
        fecha = int(_n(lineas[0].get("Fecha")))
        toca_129 = any(str(l.get("Cuenta") or "").startswith("129") for l in lineas)
        toca_67 = any(str(l.get("Cuenta") or "").startswith(("6", "7")) for l in lineas)
        # cierre/regularización: 31/12 tocando la 129 (mismo criterio que app/ledger.detectar_cierre)
        es_cierre = fecha % 10000 == 1231 and toca_129
        es_apertura = fecha % 10000 == 101
        tiene = any(str(l.get("Cuenta") or "").startswith(CUENTAS_LIBRO) and (_n(l.get("Debe")) or _n(l.get("Haber")))
                    for l in lineas)
        if not tiene:
            continue
        if es_cierre:
            n_cierre += 1
            continue
        if es_apertura:
            n_apertura += 1
            continue

        por_cuenta: dict[str, list[dict]] = {}
        for l in lineas:
            c = str(l.get("Cuenta") or "")
            if c.startswith(CUENTAS_LIBRO) and (_n(l.get("Debe")) or _n(l.get("Haber"))):
                por_cuenta.setdefault(_raiz(c), []).append(l)

        b640 = sum(_n(x.get("Debe")) - _n(x.get("Haber")) for x in lineas
                   if str(x.get("Cuenta") or "").startswith(("640", "641")))
        b64 = sum(_n(x.get("Debe")) - _n(x.get("Haber")) for x in lineas
                  if str(x.get("Cuenta") or "").startswith(FAMILIA_TRABAJO))
        b62 = sum(_n(x.get("Debe")) - _n(x.get("Haber")) for x in lineas
                  if str(x.get("Cuenta") or "").startswith(FAMILIA_PROFESIONAL))
        b7 = sum(_n(x.get("Haber")) - _n(x.get("Debe")) for x in lineas
                 if str(x.get("Cuenta") or "").startswith("7"))
        hay43 = any(str(x.get("Cuenta") or "").startswith("43") for x in lineas)

        for raiz, cuentas in por_cuenta.items():
            saldo = sum(_n(x.get("Haber")) - _n(x.get("Debe")) for x in cuentas)
            cuota = -saldo if raiz == "473" else saldo
            fila = {
                "fecha": fecha, "cuenta": raiz, "cuota": round(cuota, 2),
                "serie": clave[0], "documento": clave[1],
                "descripcion": str(cuentas[0].get("Descripcion") or ""),
                "tercero": str(cuentas[0].get("Tercero") or ""),
            }
            renta = bool(b64 or b62 or b7) or hay43
            hay_pago = any(str(x.get("Cuenta") or "").startswith(("57", "470", "476", "554", "555"))
                           for x in lineas)
            if cuota <= 0:
                # Lo que disminuye la cuenta es un pago o liquidación del modelo (contrapartida de
                # tesorería u otra cuenta de Hacienda): va aparte y no se netea. Pero si trae
                # contrapartida de renta y ninguna cuenta de pago, es una RECTIFICACIÓN (factura de
                # abono que revierte la retención): es un devengo, en negativo, y sí entra.
                if cuota < 0 and renta and not hay_pago and raiz == "4751":
                    familia = ("trabajo" if (b64 and abs(b64) >= abs(b62))
                               else ("profesionales" if b62 else "otras"))
                    fila.update({"tipo": familia, "base": None})
                    movimientos.append(fila)
                    continue
                fila.update({"tipo": "otras", "base": None})
                otros.append(fila)
                continue
            if raiz == "473":
                fila.update({"tipo": "otras", "base": round(b7, 2) if b7 > 0 else None})
                (movimientos if (b7 > 0 or hay43) else otros).append(fila)
                continue
            candidatos = []
            if b64 > 0:
                candidatos.append(("trabajo", b640 if b640 > 0 else b64))
            if b62 > 0:
                candidatos.append(("profesionales", b62))
            if raiz != "4751":
                fila.update({"tipo": "otras", "base": None})
                (movimientos if candidatos else otros).append(fila)
                continue
            if not candidatos:
                fila.update({"tipo": "otras", "base": None})
                otros.append(fila)
                continue
            candidatos.sort(key=lambda c: -abs(c[1]))
            tipo, base = candidatos[0]
            fila.update({"tipo": tipo, "base": round(base, 2), "tipo_pct":
                         round(cuota / base * 100, 2) if base > 0 and cuota > 0 else None})
            movimientos.append(fila)

        for raiz in {_raiz(str(l.get("Cuenta") or "")) for l in lineas
                     if str(l.get("Cuenta") or "").startswith(CUENTAS_LIBRO)}:
            # mismo signo que el libro: en la 473 (activo) la retención soportada aumenta en el debe
            signo = -1.0 if raiz == "473" else 1.0
            saldo_cuenta[raiz] = saldo_cuenta.get(raiz, 0.0) + signo * sum(
                _n(l.get("Haber")) - _n(l.get("Debe")) for l in lineas if _raiz(str(l.get("Cuenta") or "")) == raiz)

    def suma(filas, tipo):
        return round(sum(f["cuota"] for f in filas if f["tipo"] == tipo), 2)

    def base_de(filas, tipo):
        return round(sum(f["base"] or 0.0 for f in filas if f["tipo"] == tipo), 2)

    por_trimestre = []
    for q in (1, 2, 3, 4):
        filas = [f for f in movimientos if _trimestre(f["fecha"]) == q]
        t, p = suma(filas, "trabajo"), suma(filas, "profesionales")
        por_trimestre.append({"trimestre": q, "trabajo": t, "profesionales": p,
                              "otras": suma(filas, "otras"), "total": round(t + p, 2),
                              "n": len(filas)})

    return {
        "trabajo": suma(movimientos, "trabajo"), "profesionales": suma(movimientos, "profesionales"),
        "otras": suma(movimientos, "otras"),
        "total": round(suma(movimientos, "trabajo") + suma(movimientos, "profesionales"), 2),
        "baseTrabajo": base_de(movimientos, "trabajo"), "baseProfesionales": base_de(movimientos, "profesionales"),
        "n_movimientos": len(movimientos), "n_otros": len(otros),
        "porTrimestre": por_trimestre, "movimientos": movimientos, "otrosMovimientos": otros,
        "saldoCuentas": {k: round(v, 2) for k, v in saldo_cuenta.items()},
        "n_apertura": n_apertura, "n_cierre": n_cierre,
    }


# ---------------------------------------------------------------- verificación

def verificar_empresa(nombre: str, cod: str, year: int, asientos: list[dict], modulo) -> dict:
    lineas = lineas_de_asientos(asientos)
    ctx = {"empresa": nombre, "cod_empresa": cod, "year": year, "year_anterior": year - 1,
           "nombre_mes": "septiembre", "trimestre": None, "email": ""}
    datos = modulo.calcular({year: lineas}, ctx)
    html = modulo.informe_html(datos, ctx)
    esperado = recalcular(asientos)

    print(f"\n   Apuntes: {len(asientos)} asientos · {len(lineas)} líneas")
    print(f"   Trabajo          {fmt(datos['retencionesTrabajo']):>15}   base {fmt(datos['baseTrabajo'])}"
          f"   tipo medio {fmt_pct(datos['tipoMedioTrabajo'])}")
    print(f"   Profesionales    {fmt(datos['retencionesProfesionales']):>15}   base {fmt(datos['baseProfesionales'])}"
          f"   tipo medio {fmt_pct(datos['tipoMedioProfesionales'])}")
    print(f"   Otras cuentas    {fmt(datos['retencionesOtras']):>15}   (4752/4750/4759/473, fuera del IRPF)")
    print(f"   TOTAL IRPF       {fmt(datos['retencionesTotal']):>15}   ·  {datos['n_movimientos']} movimientos "
          f"· {datos['n_otros']} pagos/liquidaciones")
    for d in datos["porTrimestre"]:
        print(f"     {d['trimestre']}T {fmt(d['trabajo']):>13} trabajo + {fmt(d['profesionales']):>12} profesionales"
              f" = {fmt(d['total']):>13}  ({d['nMovimientos']} mov.)")

    print("   Comprobaciones del cálculo:")
    comprobar(cerca(datos["retencionesTrabajo"], esperado["trabajo"]),
              f"retenciones de trabajo == recalculado ({fmt(esperado['trabajo'])})")
    comprobar(cerca(datos["retencionesProfesionales"], esperado["profesionales"]),
              f"retenciones de profesionales == recalculado ({fmt(esperado['profesionales'])})")
    comprobar(cerca(datos["retencionesOtras"], esperado["otras"]),
              f"otras cuentas == recalculado ({fmt(esperado['otras'])})")
    comprobar(cerca(datos["retencionesTotal"], esperado["total"]),
              f"total == trabajo + profesionales ({fmt(esperado['total'])})")
    comprobar(cerca(datos["baseTrabajo"], esperado["baseTrabajo"]),
              f"base de trabajo == recalculada ({fmt(esperado['baseTrabajo'])})")
    comprobar(cerca(datos["baseProfesionales"], esperado["baseProfesionales"]),
              f"base de profesionales == recalculada ({fmt(esperado['baseProfesionales'])})")
    comprobar(datos["n_movimientos"] == esperado["n_movimientos"],
              f"nº de movimientos == recalculado ({esperado['n_movimientos']})")
    comprobar(datos["n_otros"] == esperado["n_otros"],
              f"nº de pagos/liquidaciones == recalculado ({esperado['n_otros']})")
    for q, e in zip(datos["porTrimestre"], esperado["porTrimestre"]):
        comprobar(cerca(q["trabajo"], e["trabajo"]) and cerca(q["profesionales"], e["profesionales"])
                  and cerca(q["otras"], e["otras"]) and q["nMovimientos"] == e["n"],
                  f"{q['trimestre']}T: trabajo {fmt(e['trabajo'])}, profesionales {fmt(e['profesionales'])}, "
                  f"otras {fmt(e['otras'])}, {e['n']} movimientos")

    # completeness: cada cuenta del libro, devengos + pagos = saldo del ejercicio (sin apertura/cierre)
    devengos: dict[str, float] = {}
    for f in datos["movimientos"]:
        devengos[f["cuenta"]] = devengos.get(f["cuenta"], 0.0) + f["cuota"]
    pagos: dict[str, float] = {}
    for f in datos["otrosMovimientos"]:
        pagos[f["cuenta"]] = pagos.get(f["cuenta"], 0.0) + f["cuota"]
    for cuenta, saldo in sorted(esperado["saldoCuentas"].items()):
        total = round(devengos.get(cuenta, 0.0) + pagos.get(cuenta, 0.0), 2)
        comprobar(cerca(total, saldo),
                  f"completeness {cuenta}: movimientos del libro {fmt(total)} == saldo de la cuenta {fmt(saldo)}")
    comprobar(cerca(sum(devengos.values()) + sum(pagos.values()), sum(esperado["saldoCuentas"].values())),
              "completeness global: no se pierde ningún movimiento de las cuentas de retención")
    if not esperado["n_apertura"] and not esperado["n_cierre"]:
        # sin apertura ni cierre, el saldo de cada cuenta del libro lo confirma el motor contable
        del_proyecto: dict[str, float] = {}
        for cuenta, s in saldos_por_cuenta(lineas).items():
            if cuenta.startswith(CUENTAS_LIBRO):
                raiz = _raiz(cuenta)
                signo = -1.0 if raiz == "473" else 1.0
                del_proyecto[raiz] = del_proyecto.get(raiz, 0.0) + signo * (s.haber - s.debe)
        comprobar(all(cerca(v, esperado["saldoCuentas"].get(k, 0.0)) for k, v in del_proyecto.items()),
                  "los saldos por cuenta del recálculo coinciden con los del motor contable")

    # base y tipo (%) movimiento a movimiento
    por_clave = {(f["serie"], f["documento"], f["cuenta"]): f for f in esperado["movimientos"]}
    revisados = 0
    for f in datos["movimientos"]:
        e = por_clave.get((f["serie"], f["num_documento"], f["cuenta"]))
        if not e:
            comprobar(False, f"movimiento {f['fecha_txt']} {f['documento']} {f['cuenta']}: "
                             f"el recálculo no lo encuentra (ni su asiento)")
            break
        revisados += 1
        mismo = cerca(f["cuota"], e["cuota"]) and ((f["base"] is None and e["base"] is None)
                                                  or cerca(f["base"] or 0, e["base"] or 0))
        if not mismo:
            comprobar(False, f"movimiento {f['fecha_txt']} {f['documento']} {f['cuenta']}: "
                             f"cuota/base {f['cuota']}/{f['base']} != recalculado {e['cuota']}/{e['base']}")
            break
        if not cerca(f["cuota"], sum(x["cuota"] for x in datos["movimientos"]
                                     if x["serie"] == f["serie"] and x["num_documento"] == f["num_documento"]
                                     and x["cuenta"] == f["cuenta"])):
            comprobar(False, f"asiento {f['documento']} cuenta {f['cuenta']}: la fila no lleva el total del asiento")
            break
    comprobar(revisados == len(datos["movimientos"]),
              f"los {revisados} movimientos del módulo cuadran con el recálculo (cuota y base, asiento a asiento)")
    comprobar(all((f["tipo_pct"] is None) == (not f["base"] or f["base"] <= 0 or f["cuota"] <= 0)
                  for f in datos["movimientos"]),
              "el tipo (%) sólo aparece cuando hay base y cuota positivas")
    comprobar(all(f["fecha"] and f["cuenta"] and f["documento"] and f["descripcion"]
                  for f in datos["movimientos"]),
              "cada movimiento lleva fecha, documento, cuenta y descripción")
    sin_base = [f for f in datos["movimientos"] if not f["base"]]
    comprobar(datos["n_sin_base"] == len(sin_base),
              f"declara los {len(sin_base)} movimientos sin base derivable (no la inventa)")

    # contrato del HTML
    print("   Comprobaciones del informe:")
    comprobar(html.lstrip().startswith("<div"), "el HTML empieza por '<div'")
    comprobar("```" not in html and not re.search(r"(?m)^#{1,6} ", html), "sin markdown ni bloques de código")
    comprobar("Arial" in html and "font-size:13px" in html and "max-width:780px" in html,
              "Arial 13px y ancho 780px (cliente)")
    comprobar("ABGA Consultores" in html and "USO INTERNO" not in html, "pie de cliente, sin etiqueta de uso interno")
    comprobar("#1a4b8c" in html, "cabeceras en #1a4b8c")
    comprobar(all(x in html for x in ("4751", "4752", "4750", "4759", "473")),
              "el informe nombra las cuentas del libro (qué cuenta alimenta cada bloque)")
    comprobar("111" in html and "115" in html and "123" in html,
              "relaciona cada trimestre con su modelo (111, 115 y 123)")
    comprobar("contabilizadas" in html and "no las declaraciones presentadas" in html,
              "aviso: son retenciones contabilizadas, no declaraciones presentadas")
    if sin_base:
        comprobar("sin base" in html, f"el detalle muestra «sin base» en los {len(sin_base)} casos sin base derivable")
    else:
        comprobar(True, "no hay movimientos sin base derivable en este libro (no se inventa ninguna)")
    importes_html = re.findall(r">(-?[\d.]+,\d{2} €)<", html)
    comprobar(bool(importes_html), f"hay importes es-ES como importe propio de su celda ({len(importes_html)})")
    for valor, etiqueta in ((datos["retencionesTrabajo"], "retenciones de trabajo"),
                            (datos["retencionesProfesionales"], "retenciones de profesionales"),
                            (datos["retencionesTotal"], "total de retenciones")):
        comprobar(fmt(valor) in importes_html, f"el importe de {etiqueta} ({fmt(valor)}) sale como importe de celda")
    comprobar(html.count("Subtotal") == sum(1 for d in datos["porTrimestre"] if d["nMovimientos"]),
              "cada trimestre con movimientos lleva su fila de subtotal en el detalle")
    comprobar(html.count("<svg") == 1, "el informe lleva su gráfica SVG")
    comprobar(all(x in html for x in ("Ene", "Dic", "TOTAL")), "el reparto mensual llega a los doce meses")

    # parámetros
    print("   Comprobaciones del parámetro trimestre:")
    for valor, esperado_t in (("Q3", 3), ("3T", 3), ("4", 4), (2, 2)):
        t, aviso = modulo.normalizar_trimestre(valor)
        comprobar(t == esperado_t, f"normalizar_trimestre({valor!r}) → {esperado_t} ({aviso or 'sin aviso'})")
    comprobar(modulo.normalizar_trimestre(None)[0] is None, "PARAMETROS['trimestre'] = None → los cuatro trimestres")
    for t in (1, 2, 3, 4):
        ctx_t = dict(ctx, trimestre=t)
        datos_t = modulo.calcular({year: lineas}, ctx_t)
        html_t = modulo.informe_html(datos_t, ctx_t)
        e = esperado["porTrimestre"][t - 1]
        solo_su_detalle = (f"Detalle del {t}T" in html_t
                           and all(f"Detalle del {o}T" not in html_t for o in (1, 2, 3, 4) if o != t))
        comprobar(datos_t["trimestres"] == [t] and cerca(datos_t["retencionesTotal"], esperado["total"])
                  and datos_t["trimestreActual"]["trimestre"] == t
                  and cerca(datos_t["trimestreActual"]["total"], e["total"]) and solo_su_detalle,
                  f"con trimestre={t} el detalle es sólo del {t}T ({fmt(e['total'])}) y el ejercicio no cambia")

    metricas = modulo.metricas_dashboard(datos)
    print("   Comprobaciones de metricas_dashboard:")
    comprobar(set(metricas) == {"retencionesTrabajo", "retencionesProfesionales", "retencionesTotal",
                               "n_movimientos"}, f"devuelve las cuatro claves pedidas ({sorted(metricas)})")
    comprobar(cerca(metricas["retencionesTrabajo"], datos["retencionesTrabajo"])
              and cerca(metricas["retencionesProfesionales"], datos["retencionesProfesionales"])
              and cerca(metricas["retencionesTotal"], datos["retencionesTotal"])
              and metricas["n_movimientos"] == datos["n_movimientos"],
              "los valores coinciden con los del cálculo")
    return datos


def main() -> int:
    print("=" * 78)
    print("Verificación del módulo libro_retenciones · fixtures reales de 6091 y caché local")
    print("=" * 78)

    print("\n[1] Contrato de módulos")
    definicion = modulos.obtener("libro_retenciones")
    comprobar(definicion.disponible, f"el módulo carga ({definicion.error or 'sin errores'})")
    modulo = definicion.modulo
    comprobar(getattr(modulo, "NOMBRE", None) == "libro_retenciones", "NOMBRE == 'libro_retenciones'")
    comprobar(getattr(modulo, "TITULO", None) == "Libro de retenciones",
              f"TITULO == {getattr(modulo, 'TITULO', None)!r}")
    comprobar(getattr(modulo, "INTERNO", None) is False, "INTERNO is False (es informe de cliente)")
    comprobar(list(getattr(modulo, "DESPLAZAMIENTOS", [])) == [0], "DESPLAZAMIENTOS == [0]")
    parametros = getattr(modulo, "PARAMETROS", {})
    comprobar(parametros.get("trimestre", "falta") is None,
              f"PARAMETROS == {parametros} (trimestre por defecto None = los cuatro)")
    for nombre in ("calcular", "informe_html", "metricas_dashboard"):
        comprobar(callable(getattr(modulo, nombre, None)), f"exporta {nombre}()")

    for year in (2025, 2024):
        ruta = RAIZ / "fixtures" / f"apuntes_6091_{year}.json"
        if not ruta.exists():
            comprobar(False, f"falta el fixture {ruta.name}")
            continue
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        print(f"\n[2] Empresa {crudo['empresa']} · ejercicio {year} · fixture {ruta.name}")
        verificar_empresa(EMPRESA, COD_EMPRESA, int(crudo["year"]), crudo["asientos"], modulo)

    print("\n[3] Segunda empresa real (caché local, sin tocar el ERP)")
    try:
        from app import cache  # noqa: PLC0415

        guardados = cache.leer_apuntes("6221", 2025, ttl=-1)
    except Exception as e:  # caché no disponible: no es un fallo del módulo
        guardados, e_ = None, e
        print(f"   (no se pudo usar la caché: {e_})")
    if guardados and guardados.get("asientos"):
        verificar_empresa("Empresa 6221", "6221", 2025, guardados["asientos"], modulo)
    else:
        print("   (la caché no tiene apuntes de 6221/2025: se verifica sólo con los fixtures)")

    print("\n" + "=" * 78)
    print(f"{comprobaciones - len(fallos)}/{comprobaciones} comprobaciones correctas")
    if fallos:
        print(f"FALLOS ({len(fallos)}):")
        for f in fallos:
            print("   ·", f)
        return 1
    print("OK: libro de retenciones verificado (contrato, recálculo desde los apuntes y HTML)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
