#!/usr/bin/env python
"""Verificación del módulo `fiscal` (REQ-06 Alertas fiscales).

Calcula los cuatro trimestres del ejercicio 2025 de la empresa 6091 con los apuntes
guardados en `fixtures/` (nunca se llama al ERP), imprime las obligaciones de cada
trimestre y comprueba:

  1. que el módulo cumple el contrato de `CONTRATO-MODULOS.md`;
  2. que el HTML de cada trimestre empieza por `<div`;
  3. que los números del módulo coinciden con la fórmula del JavaScript original
     (`legacy/REQ-06-Calcular_Situación_Fiscal.js`) recalculada aquí de forma
     independiente sobre los mismos apuntes.

Uso:  cd <raíz del proyecto> && ./.venv/bin/python backend/scripts/verificar_fiscal.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import modulos                     # noqa: E402
from app.ledger import fmt, lineas_de_asientos  # noqa: E402

FIXTURE = RAIZ / "fixtures" / "apuntes_6091_2025.json"
COD_EMPRESA = "6091"
EMPRESA = "MB Dommo, S.L."

TOLERANCIA = 0.05   # el módulo redondea a céntimos; el original trabajaba con floats crudos

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


# ---------------------------------------------------------------- legado (JS) en Python

def calcular_legado(asientos: list[dict], year: int, trimestre: int) -> dict:
    """Recalcula REQ-06 tal cual, sobre los apuntes crudos: sirve de patrón de contraste."""
    lineas = [d for a in asientos for d in (a.get("Detalles") or [])]

    def de_num(v) -> float:
        return float(v or 0)

    def por_prefijo(prefijos):
        return [l for l in lineas if any(str(l.get("Cuenta") or "").startswith(p) for p in prefijos)]

    def rep(prefijos) -> float:
        return sum(de_num(l.get("Haber")) - de_num(l.get("Debe")) for l in por_prefijo(prefijos))

    def sop(prefijos) -> float:
        return sum(de_num(l.get("Debe")) - de_num(l.get("Haber")) for l in por_prefijo(prefijos))

    p477, p472, p4751 = ["477"], ["472"], ["4751"]
    iva_rep, iva_sop = rep(p477), sop(p472)
    saldo = iva_rep - iva_sop

    rangos = {
        1: (int(f"{year}0101"), int(f"{year}0331")),
        2: (int(f"{year}0401"), int(f"{year}0630")),
        3: (int(f"{year}0701"), int(f"{year}0930")),
        4: (int(f"{year}1001"), int(f"{year}1231")),
    }
    ini, fin = rangos[trimestre]
    del_trimestre = [l for l in lineas if ini <= int(l.get("Fecha") or 0) <= fin]
    iva_trim = (
        sum(de_num(l.get("Haber")) - de_num(l.get("Debe"))
            for l in del_trimestre if str(l.get("Cuenta") or "").startswith("477"))
        - sum(de_num(l.get("Debe")) - de_num(l.get("Haber"))
              for l in del_trimestre if str(l.get("Cuenta") or "").startswith("472"))
    )
    ret_trim = sum(de_num(l.get("Haber")) - de_num(l.get("Debe"))
                   for l in del_trimestre if str(l.get("Cuenta") or "").startswith("4751"))

    base_ing = rep(["700", "701", "702", "703", "704", "705", "706", "708", "709"])
    base_gas = sop(["600", "601", "602", "620", "621", "622", "623", "624", "625", "626", "627",
                    "628", "629", "640", "641", "642", "660", "661", "662", "680", "681", "682"])
    base_is = max(0.0, base_ing - base_gas)
    pago_202 = base_is * 0.18
    aplica_202 = trimestre in (1, 3)   # tokens.trimestre === 'Q1' || 'Q3'
    return {
        "ivaRepercutido": iva_rep, "ivaSoportado": iva_sop,
        "saldoIVA": saldo, "ivaAIngresar": max(0.0, saldo), "ivaADevolver": abs(min(0.0, saldo)),
        "ivaTrimestre": iva_trim, "retencionesTrimestre": ret_trim,
        "baseIS": base_is, "pagoFraccionadoIS": pago_202, "aplicaModelo202": aplica_202,
        "totalObligaciones": max(0.0, iva_trim) + max(0.0, ret_trim) + (pago_202 if aplica_202 else 0.0),
    }


# ---------------------------------------------------------------- verificación

def main() -> int:
    print("=" * 78)
    print(f"Verificación del módulo fiscal · fixture {FIXTURE.name}")
    print("=" * 78)

    if not FIXTURE.exists():
        print(f"ERROR: no existe el fixture {FIXTURE}")
        return 2
    crudo = json.loads(FIXTURE.read_text(encoding="utf-8"))
    asientos = crudo["asientos"]
    year = int(crudo["year"])
    lineas = lineas_de_asientos(asientos)
    print(f"\nApuntes: empresa {crudo['empresa']} · ejercicio {year} · "
          f"{len(asientos)} asientos · {len(lineas)} líneas")
    assert lineas, "el fixture no produjo líneas"

    print("\n[1] Contrato de módulos")
    definicion = modulos.obtener("fiscal")
    comprobar(definicion.disponible, f"el módulo carga en el registro ({definicion.error or 'sin errores'})")
    modulo = definicion.modulo
    comprobar(getattr(modulo, "NOMBRE", None) == "fiscal", "NOMBRE == 'fiscal'")
    comprobar(isinstance(getattr(modulo, "TITULO", None), str) and modulo.TITULO.strip() != "",
              f"TITULO == {getattr(modulo, 'TITULO', None)!r}")
    comprobar(getattr(modulo, "INTERNO", None) is False, "INTERNO is False")
    comprobar(list(getattr(modulo, "DESPLAZAMIENTOS", [])) == [0], "DESPLAZAMIENTOS == [0]")
    parametros = getattr(modulo, "PARAMETROS", {})
    comprobar("trimestre" in parametros, f"PARAMETROS declara `trimestre` ({parametros})")
    comprobar(parametros.get("trimestre") is None, "PARAMETROS['trimestre'] por defecto None")
    comprobar(callable(getattr(modulo, "calcular", None)), "exporta calcular(por_anio, ctx)")
    comprobar(callable(getattr(modulo, "informe_html", None)), "exporta informe_html(datos, ctx)")
    comprobar(callable(getattr(modulo, "metricas_dashboard", None)), "exporta metricas_dashboard(datos)")

    resumen = []
    for trimestre in (1, 2, 3, 4):
        ctx = {"empresa": EMPRESA, "cod_empresa": COD_EMPRESA, "year": year, "year_anterior": year - 1,
               "nombre_mes": "septiembre", "trimestre": trimestre, "email": ""}
        print(f"\n[2] Trimestre {trimestre}T")
        datos = modulo.calcular({year: lineas}, ctx)
        html = modulo.informe_html(datos, ctx)
        legado = calcular_legado(asientos, year, trimestre)

        print(f"   IVA repercutido (año)  {fmt(datos['ivaRepercutido']):>15}")
        print(f"   IVA soportado (año)    {fmt(datos['ivaSoportado']):>15}")
        print(f"   Saldo IVA {trimestre}T          {fmt(datos['ivaTrimestreActual']['saldo']):>15}"
              f"   ({'a ingresar' if datos['ivaTrimestreActual']['saldo'] > 0 else 'a devolver/compensar'})")
        print(f"   Retenciones IRPF {trimestre}T   {fmt(datos['retencionesTrimestre']):>15}")
        print(f"   Base estimada IS       {fmt(datos['baseIS']):>15}   18% → {fmt(datos['pagoFraccionadoIS'])}"
              f"   (mod. 202 {'sí' if datos['aplicaModelo202'] else 'no'} aplica)")
        print(f"   OBLIGACIONES {trimestre}T: IVA {fmt(datos['obligacionIVA'])} + retenciones "
              f"{fmt(datos['obligacionRetenciones'])} + 202 {fmt(datos['obligacion202'])} = "
              f"{fmt(datos['totalObligaciones'])}")
        for v in datos["vencimientos"]:
            marca = "" if v["aplica"] else "  (no aplica: recordatorio)"
            print(f"     · mod. {v['modelo']} {v['concepto']:<34} límite {v['humano']}{marca}")
        if datos["alertas"]:
            for a in datos["alertas"]:
                print(f"     ! [{a['nivel']}] {a['mensaje']}")
        print(f"   Nivel global: {datos['nivelGlobal']} · avisos: {len(datos['avisos'])}")

        print("   Comprobaciones:")
        comprobar(html.startswith("<div"), "el HTML empieza por '<div'")
        comprobar(not html.lstrip().startswith("```") and "<html" not in html[:200].lower(),
                  "el HTML no lleva markdown ni etiqueta <html>")
        comprobar(isinstance(datos.get("avisos"), list)
                  and all(isinstance(a, str) for a in datos["avisos"]),
                  "datos['avisos'] es una lista de strings")
        comprobar(isinstance(datos.get("data"), dict)
                  and isinstance(datos["data"].get("totalObligaciones"), (int, float)),
                  "datos['data']['totalObligaciones'] es un número")
        comprobar(isinstance(datos["totalObligaciones"], (int, float)),
                  f"datos['totalObligaciones'] es un número ({datos['totalObligaciones']})")
        comprobar(all(isinstance(datos.get(k), (int, float)) for k in
                      ("ivaRepercutido", "ivaSoportado", "saldoIVA", "ivaAIngresar", "ivaADevolver",
                       "retencionesIRPF", "retencionesTrimestre", "baseIS", "pagoFraccionadoIS",
                       "obligacionIVA", "obligacionRetenciones", "obligacion202")),
                  "los agregados del contrato son números, no texto formateado")
        comprobar(isinstance(modulo.metricas_dashboard(datos), dict),
                  "metricas_dashboard devuelve un dict")
        comprobar(len(datos["ivaTrimestreDetalle"]) == 4, "el desglose trae los 4 trimestres")
        comprobar(len(datos["vencimientos"]) >= 3 and all("humano" in v for v in datos["vencimientos"]),
                  "los vencimientos traen fecha límite legible")
        comprobar("303" in html and "202" in html, "el informe nombra los modelos 303 y 202")
        comprobar(str(datos["trimestre"]) in html or f"{trimestre}T" in html,
                  f"el informe muestra el trimestre ({trimestre}T)")
        # contraste con la fórmula del JavaScript original
        comprobar(cerca(datos["ivaRepercutido"], legado["ivaRepercutido"]), "IVA repercutido == REQ-06")
        comprobar(cerca(datos["ivaSoportado"], legado["ivaSoportado"]), "IVA soportado == REQ-06")
        comprobar(cerca(datos["saldoIVA"], legado["saldoIVA"]), "saldo IVA == REQ-06")
        comprobar(cerca(datos["ivaAIngresar"], legado["ivaAIngresar"]), "IVA a ingresar == REQ-06")
        comprobar(cerca(datos["ivaADevolver"], legado["ivaADevolver"]), "IVA a devolver == REQ-06")
        comprobar(cerca(datos["ivaTrimestreActual"]["saldo"], legado["ivaTrimestre"]),
                  f"saldo IVA del {trimestre}T == REQ-06")
        comprobar(cerca(datos["retencionesTrimestre"], legado["retencionesTrimestre"]),
                  f"retenciones del {trimestre}T == REQ-06")
        comprobar(cerca(datos["baseIS"], legado["baseIS"]), f"base IS == REQ-06 ({fmt(legado['baseIS'])})")
        comprobar(cerca(datos["pagoFraccionadoIS"], legado["pagoFraccionadoIS"]),
                  "pago fraccionado 18 % == REQ-06")
        comprobar(datos["aplicaModelo202"] == legado["aplicaModelo202"],
                  "aplica el mod. 202 cuando toca (1T y 3T, como el original)")
        comprobar(cerca(datos["totalObligaciones"], legado["totalObligaciones"]),
                  f"total obligaciones == REQ-06 ({fmt(legado['totalObligaciones'])})")
        resumen.append((trimestre, datos["totalObligaciones"], datos["nivelGlobal"]))

    print("\n[3] Trimestre por defecto (PARAMETROS['trimestre'] = None)")
    ctx_sin = {"empresa": EMPRESA, "cod_empresa": COD_EMPRESA, "year": year, "trimestre": None}
    datos_sin = modulo.calcular({year: lineas}, ctx_sin)
    comprobar(datos_sin["trimestre"] == modulo.trimestre_natural(),
              f"sin parámetro usa el trimestre natural ({datos_sin['trimestre']}T)")
    comprobar(modulo.informe_html(datos_sin, ctx_sin).startswith("<div"),
              "el informe del trimestre natural también empieza por '<div'")
    for valor, esperado in (("Q2", 2), ("3", 3), ("4T", 4), ("9", modulo.trimestre_natural())):
        obtenido, _ = modulo.normalizar_trimestre(valor)
        comprobar(obtenido == esperado, f"normalizar_trimestre({valor!r}) -> {esperado}")

    print("\n" + "=" * 78)
    print("Resumen de obligaciones por trimestre")
    print("-" * 78)
    for t, total, nivel in resumen:
        print(f"   {t}T {year}   {fmt(total):>15}   nivel {nivel}")
    print("-" * 78)
    print(f"{comprobaciones - len(fallos)}/{comprobaciones} comprobaciones correctas")
    if fallos:
        print(f"FALLOS ({len(fallos)}):")
        for f in fallos:
            print(f"   · {f}")
        return 1
    print("OK: módulo fiscal verificado (HTML, contrato y port del original)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
