"""Prueba offline del particionado por fechas del cliente del ERP.

Sustituye `_pagina_rango` por un ERP simulado que aplica de verdad el filtro
`Fecha ge/le` (y `$skip` como número de página) y comprueba que el recorrido devuelve
TODOS los asientos, sin huecos ni duplicados. Incluye un día con más asientos que una
página y varios días de frontera con fechas repetidas, que es donde el sistema anterior
y las primeras versiones de este cliente perdían registros.

Uso: ./.venv/bin/python backend/scripts/test_particionado.py
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import apicon  # noqa: E402
from app.config import cargar_config  # noqa: E402

PAGINA = apicon.PAGINA
FALLOS: list[str] = []


def check(cond: bool, texto: str, detalle: str = "") -> None:
    print(("  OK   " if cond else "  FALLO") + f" {texto}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLOS.append(texto)


def generar(anio: int, n: int, *, dia_denso: int | None = None, n_denso: int = 430,
            series_denso: list[str] | None = None) -> list[dict]:
    """Genera asientos repartidos por el año, con empates de fecha a propósito."""
    rnd = random.Random(20250914)
    inicio = date(anio, 1, 2)
    fin = date(anio, 12, 31)
    dias = (fin - inicio).days
    asientos = []
    for i in range(n):
        d = inicio + timedelta(days=rnd.randrange(dias))
        asientos.append({"Ejercicio": str(anio), "Serie": str(rnd.choice([1, 2, 3])),
                         "Documento": str(1000 + i), "Fecha": d.year * 10000 + d.month * 100 + d.day,
                         "Debe": round(rnd.uniform(10, 5000), 2), "Haber": 0,
                         "Detalles": [{"Cuenta": "700000000000"}]})
    if dia_denso:
        for i in range(n_denso):
            serie = (series_denso[i % len(series_denso)] if series_denso else "9")
            asientos.append({"Ejercicio": str(anio), "Serie": str(serie), "Documento": str(9000 + i),
                             "Fecha": dia_denso, "Debe": 100.0, "Haber": 0,
                             "Detalles": [{"Cuenta": "700000000000"}]})
    return asientos


def instalar_erp_falso(cli: apicon.ClienteApicon, asientos: list[dict], anio: int,
                       *, orden_estable: bool = True, filtro_incompleto: bool = False) -> dict:
    """ERP simulado: filtra por rango y pagina como el de verdad.

    `orden_estable=True` reproduce un ERP que mantiene el orden entre llamadas (el caso
    razonable). `orden_estable=False` reordena en cada llamada, que es el peor caso posible:
    con él no se puede garantizar la cobertura y lo que se exige es que el sistema **lo diga**,
    no que devuelva datos silenciosamente incompletos.
    """
    rnd = random.Random(7)
    stats = {"llamadas": 0, "devueltos": 0}

    por_fecha: dict[int, list[dict]] = {}
    for a in asientos:
        por_fecha.setdefault(int(a["Fecha"]), []).append(a)
    # orden fijo por día (el que vería el ERP), y variantes inestables si hace falta
    orden_dia = {f: list(rnd.sample(v, len(v))) for f, v in por_fecha.items()}

    # Defecto real comprobado en 6091/2024: el filtro por rango de fechas NO devuelve todos los
    # asientos del rango (396 de 2.221), aunque su fecha esté dentro; el listado sin filtro sí.
    rnd_omitidos = random.Random(99)
    todas_claves = [f"{a['Serie']}|{a['Documento']}|{a['Fecha']}" for a in asientos]
    omitidos = {f"{k}" for k in todas_claves if rnd_omitidos.random() < 0.08}
    anio_ini, anio_fin = anio * 10000 + 101, anio * 10000 + 1231
    # orden propio del listado completo (no monótono por fechas, como el del ERP)
    orden_anio = list(asientos)
    random.Random(5).shuffle(orden_anio)

    def falso(empresa: str, ejercicio: int, ini: int, fin: int, pagina: int = 1, **extra) -> dict:
        stats["llamadas"] += 1
        if ejercicio != anio:
            return {"Datos": [], "ResultadosTotales": 0}
        seleccion = []
        for f in sorted(f for f in por_fecha if ini <= f <= fin):
            lista = orden_dia[f] if orden_estable else rnd.sample(orden_dia[f], len(orden_dia[f]))
            seleccion.extend(lista)
        if filtro_incompleto and (ini, fin) != (anio_ini, anio_fin):
            seleccion = [a for a in seleccion
                         if f"{a['Serie']}|{a['Documento']}|{a['Fecha']}" not in omitidos]
        trozo = seleccion[(pagina - 1) * PAGINA: pagina * PAGINA]
        stats["devueltos"] += len(trozo)
        return {"Datos": trozo, "ResultadosTotales": len(seleccion), "PaginaActual": pagina,
                "ElementosEnPagina": len(trozo), "ElementosPorPagina": PAGINA}

    def falso_serie(empresa: str, ejercicio: int, fecha: int, serie: str) -> dict:
        stats["llamadas"] += 1
        seleccion = [a for a in por_fecha.get(int(fecha), []) if str(a.get("Serie")) == str(serie)]
        rnd.shuffle(seleccion)
        trozo = seleccion[:PAGINA]
        stats["devueltos"] += len(trozo)
        return {"Datos": trozo, "ResultadosTotales": len(seleccion), "PaginaActual": 1,
                "ElementosEnPagina": len(trozo), "ElementosPorPagina": PAGINA}

    def falso_ejercicio(empresa: str, ejercicio: int, pagina: int, tope: int) -> dict:
        """Recorrido sin filtro de fecha, como el `_pagina_ejercicio` real.

        Reproduce que la enumeración del ERP **no es monótona por fechas**: las páginas son
        trozos de un orden propio, así que una página puede empezar en enero y la siguiente en
        octubre. Es justo lo que hacía que el recorrido se cortase antes de tiempo.
        """
        stats["llamadas"] += 1
        if ejercicio != anio:
            return {"Datos": [], "ResultadosTotales": 0}
        trozo = orden_anio[(pagina - 1) * PAGINA: pagina * PAGINA]
        stats["devueltos"] += len(trozo)
        return {"Datos": trozo, "ResultadosTotales": len(orden_anio), "PaginaActual": pagina,
                "ElementosEnPagina": len(trozo), "ElementosPorPagina": PAGINA}

    cli._pagina_rango = falso  # type: ignore[method-assign]
    cli._pagina_rango_serie = falso_serie  # type: ignore[method-assign]
    cli._pagina_ejercicio = falso_ejercicio  # type: ignore[method-assign]
    return stats


def caso(nombre: str, asientos: list[dict], anio: int, *, orden_estable: bool = True,
         exigir_completo: bool = True, filtro_incompleto: bool = False) -> None:
    cli = apicon.ClienteApicon(cargar_config())
    stats = instalar_erp_falso(cli, asientos, anio, orden_estable=orden_estable,
                               filtro_incompleto=filtro_incompleto)
    cli._pagina_rango_original = cli._pagina_rango
    cache_previo = apicon.cache.guardar_apuntes
    apicon.cache.guardar_apuntes = lambda *a, **k: None  # no ensuciar la caché real
    try:
        info = cli._traer_todo("TEST", anio)
    finally:
        apicon.cache.guardar_apuntes = cache_previo

    esperados = len(asientos)
    print(f"\n=== {nombre} ===")
    print(f"  {esperados} asientos de partida · {info['n_asientos']} recuperados · "
          f"{info['peticiones']} peticiones · cobertura: {info['cobertura']}")
    claves = [(a["Serie"], a["Documento"]) for a in info["asientos"]]
    check(len(set(claves)) == len(claves), "no hay duplicados en el resultado")
    if exigir_completo:
        check(info["n_asientos"] == esperados, f"recupera los {esperados} asientos (sin huecos)")
        check("completa" in info["cobertura"], "la cobertura se declara completa")
    else:
        # con un ERP que reordena en cada llamada no se puede garantizar: lo que se exige es
        # que el sistema lo declare en lugar de devolver datos incompletos en silencio
        check("parcial" in info["cobertura"] or info["n_asientos"] == esperados,
              "si no puede cubrir todo, lo declara como parcial")
        check(info["n_asientos"] >= esperados * 0.95,
              "aun así recupera la práctica totalidad", f"{info['n_asientos']}/{esperados}")
    if info.get("dias_paginados"):
        print(f"  días que hubo que paginar: {info['dias_paginados']}")


def main() -> None:
    anio = 2024
    print("prueba del particionado por fechas (ERP simulado)")
    caso("año normal", generar(anio, 1200), anio)
    caso("año con volumen alto", generar(anio, 3000), anio)
    caso("un día con más de una página", generar(anio, 900, dia_denso=anio * 10000 + 630, n_denso=430), anio)
    caso("un día denso repartido en varias series",
         generar(anio, 900, dia_denso=anio * 10000 + 630, n_denso=430, series_denso=["1", "2", "9"]), anio)
    caso("año casi vacío", generar(anio, 3), anio)
    caso("año sin movimientos", [], anio)
    caso("peor caso: el ERP reordena en cada llamada",
         generar(anio, 1500, dia_denso=anio * 10000 + 630, n_denso=430),
         anio, orden_estable=False, exigir_completo=False)
    caso("el filtro por fecha del ERP omite asientos (defecto real de 6091/2024)",
         generar(anio, 2000, dia_denso=anio * 10000 + 630, n_denso=260),
         anio, filtro_incompleto=True)

    print("\n=== resultado ===")
    if FALLOS:
        print(f"{len(FALLOS)} fallos:")
        for f in FALLOS:
            print("  -", f)
        raise SystemExit(1)
    print("el particionado no pierde asientos en ningún caso")


if __name__ == "__main__":
    main()
