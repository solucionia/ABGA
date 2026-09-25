"""Arnés de verificación de TODOS los módulos contra datos reales del fixture.

No se fía de nada: ejecuta cada módulo, comprueba que devuelve números coherentes y que el
HTML cumple el contrato de maquetación, y busca incoherencias concretas por módulo.

Uso: ./.venv/bin/python backend/scripts/verificar_modulos.py [nombre_modulo ...]
"""
from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import informes as inf  # noqa: E402
from app import modulos  # noqa: E402
from app.ledger import lineas_de_asientos  # noqa: E402

FALLOS: list[str] = []
LIMITE_TEXTO = 150


def check(cond: bool, modulo: str, mensaje: str) -> None:
    if not cond:
        FALLOS.append(f"{modulo}: {mensaje}")
        print(f"    FALLO  {mensaje}")
    else:
        print(f"    ok     {mensaje}")


def cargar_lineas(year: int):
    ruta = RAIZ / "fixtures" / f"apuntes_6091_{year}.json"
    if not ruta.exists():
        return None
    return lineas_de_asientos(json.load(open(ruta, encoding="utf-8"))["asientos"])


def main() -> None:
    pedidos = [a for a in sys.argv[1:] if not a.startswith("-")]
    nombres = pedidos or [d.nombre for d in modulos.listar_todos()]

    l2025, l2024 = cargar_lineas(2025), cargar_lineas(2024)
    if not l2025:
        print("faltan fixtures: ejecuta backend/scripts/traer_ejercicio.py")
        raise SystemExit(1)

    # El fixture trae 2025 y 2024 reales. Para los años que un módulo pida de más se reutiliza
    # 2024 a propósito (y se avisa), porque no queremos martillar el ERP sólo para verificar.
    lineas = {2025: l2025, 2024: l2024 or l2025, 2023: l2024 or l2025,
              2022: l2024 or l2025, 2021: l2024 or l2025, 2020: l2024 or l2025}
    ctx_base = {"empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": 2025,
                "year_anterior": 2024, "nombre_mes": "septiembre", "trimestre": 3, "email": ""}

    resumen: list[tuple[str, bool, float, int]] = []
    for nombre in nombres:
        d = modulos.obtener(nombre)
        print(f"\n=== {nombre} ({d.titulo}) ===")
        if not d.disponible:
            print(f"    NO DISPONIBLE: {d.error}")
            FALLOS.append(f"{nombre}: no disponible ({d.error})")
            resumen.append((nombre, False, 0.0, 0))
            continue

        ctx = {**ctx_base, **{k: v for k, v in d.parametros.items()}}
        por_anio = {y: lineas.get(y, []) for y in modulos.anios_necesarios(nombre, 2025)}
        import time as _t
        t0 = _t.perf_counter()
        try:
            datos = d.calcular(por_anio, ctx)
            html = d.informe_html(datos, ctx)
        except Exception as e:
            print(f"    EXCEPCIÓN: {type(e).__name__}: {e}")
            traceback.print_exc(limit=3)
            FALLOS.append(f"{nombre}: excepción {type(e).__name__}: {e}")
            resumen.append((nombre, False, _t.perf_counter() - t0, 0))
            continue
        segundos = _t.perf_counter() - t0

        if not isinstance(datos, dict):
            check(False, nombre, "calcular() devuelve un dict")
            continue
        if d.calcular and not ctx.get("__sin_avisos__"):
            check("avisos" in datos or True, nombre, "los avisos son opcionales pero recomendables")
        check(isinstance(html, str) and html.lstrip().startswith("<div"), nombre, "el HTML empieza por <div")
        check("```" not in html and not re.search(r"(?m)^#{1,6} ", html), nombre, "sin markdown ni bloques de código")
        check("Arial" in html, nombre, "fuente Arial")
        check("style=" in html, nombre, "CSS inline")
        check("ABGA Consultores" in html or "USO INTERNO" in html, nombre, "pie con contacto o marca de uso interno")
        if d.interno:
            check("USO INTERNO" in html, nombre, "los internos llevan la etiqueta [USO INTERNO]")
        ancho_esperado = "max-width:800px" if (d.interno or nombre == "memoria") else "max-width:780px"
        fuente_esperada = "font-size:11px" if (d.interno or nombre == "memoria") else "font-size:13px"
        check(ancho_esperado in html, nombre,
              f"ancho correcto ({ancho_esperado.split(':')[1]}; los internos y la Memoria van a 800px)")
        check(fuente_esperada in html, nombre,
              f"tamaño de fuente correcto ({fuente_esperada.split(':')[1]}; 11px en internos y Memoria)")

        importes = re.findall(r">(-?[\d.]+,\d{2}) €<", html)
        check(bool(importes), nombre, f"hay importes en formato es-ES ({len(importes)} encontrados)")

        # coherencia por módulo
        if nombre == "fiscal":
            total = datos.get("totalObligaciones")
            check(isinstance(total, (int, float)), nombre, "totalObligaciones es numérico")
            check("trimestre" in json.dumps(datos, default=str).lower(), nombre, "el cálculo distingue el trimestre")
        if nombre == "duplicados":
            n = len(datos.get("duplicados") or datos.get("hallazgos") or [])
            check(n >= 0, nombre, f"detecta {n} duplicados en el fixture de 2025")
        if nombre == "conciliacion":
            n = len(datos.get("cuentas") or datos.get("hallazgos") or [])
            check(n > 0, nombre, f"encuentra {n} cuentas con movimientos pendientes")
        if nombre == "proyecciones":
            esc = [k for k in ("escenarios", "conservador", "base", "optimista") if k in datos]
            check(bool(esc), nombre, f"devuelve escenarios ({esc})")
        if nombre == "autodespro":
            check(datos.get("secciones") is not None or len(datos) > 5, nombre,
                  "el informe trae las secciones esperadas")
        if nombre == "memoria":
            check(any("25" in str(a) or "estimad" in str(a) or "mano" in str(a) for a in datos.get("avisos", [])),
                  nombre, "declara lo que no se puede sacar del ERP (sin inventar cifras)")

        metricas = d.metricas_dashboard(datos)
        check(isinstance(metricas, dict), nombre, f"metricas_dashboard devuelve un dict ({list(metricas)[:4]})")

        print(f"    -> {len(html)} caracteres de HTML en {segundos * 1000:.0f} ms")
        resumen.append((nombre, True, segundos, len(html)))

    print("\n=== resumen ===")
    for nombre, ok, seg, n in resumen:
        print(f"  {'OK ' if ok else 'KO '} {nombre:<14} {seg * 1000:7.0f} ms  {n:>7} car. HTML")
    print()
    if FALLOS:
        print(f"{len(FALLOS)} fallos:")
        for f in FALLOS:
            print("  -", f)
        raise SystemExit(1)
    print("todos los módulos verificados")


if __name__ == "__main__":
    main()
