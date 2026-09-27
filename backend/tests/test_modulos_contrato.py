"""Contrato de los 13 módulos de informe, contra datos REALES (fixtures de `fixtures/`).

Es la versión con `assert` y una prueba por módulo de `backend/scripts/verificar_modulos.py`. Al
estar parametrizado, un módulo que se rompa falla solo el suyo en lugar de esconder los demás.

Uso:  ./.venv/bin/python -m pytest -m datos_reales -k modulos
"""

from __future__ import annotations

import re

import pytest

from app import informes as inf
from app import modulos
from app.ledger import lineas_de_asientos

pytestmark = pytest.mark.datos_reales

CTX = {"empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": 2025, "year_anterior": 2024,
       "nombre_mes": "septiembre", "trimestre": 3, "email": ""}

NOMBRES = [d.nombre for d in modulos.listar_todos()]


@pytest.fixture(scope="module")
def lineas_por_anio(asientos_reales: dict[int, list[dict]]) -> dict[int, list]:
    """Líneas por ejercicio. Los años que un módulo pida de más reutilizan 2024 a propósito.

    El fixture sólo trae 2023-2025: no se llama al ERP para rellenar huecos, que sería lento y
    tocaría el sistema en producción del cliente.
    """
    base = {y: lineas_de_asientos(a) for y, a in asientos_reales.items()}
    referencia = base.get(2025) or next(iter(base.values()))
    return {y: base.get(y, referencia) for y in range(2020, 2027)}


@pytest.mark.parametrize("nombre", NOMBRES)
def test_el_modulo_cumple_el_contrato(nombre: str, lineas_por_anio: dict[int, list]) -> None:
    d = modulos.obtener(nombre)
    assert d.disponible, f"el módulo {nombre} no se pudo importar: {d.error}"

    ctx = {**CTX, **d.parametros}
    por_anio = {y: lineas_por_anio[y] for y in modulos.anios_necesarios(nombre, 2025)}
    datos = d.calcular(por_anio, ctx)
    assert isinstance(datos, dict), "calcular() devuelve números en un dict"

    html = d.informe_html(datos, ctx)
    assert isinstance(html, str) and html.lstrip().startswith("<div"), "el HTML empieza por <div"
    assert "```" not in html and not re.search(r"(?m)^#{1,6} ", html), "sin markdown ni bloques"
    assert "Arial" in html and "style=" in html, "Arial 13px y CSS inline"

    if d.interno:
        assert "[USO INTERNO]" in html or "USO INTERNO" in html, \
            "los informes internos llevan la etiqueta de uso interno"
    else:
        assert "ABGA Consultores" in html, "los informes de cliente cierran con el pie de ABGA"

    esperado = "800" if d.interno or nombre == "memoria" else "780"
    assert f"max-width:{esperado}px" in html, f"ancho {esperado}px (la Memoria y los internos van a 800)"
    fuente = "11px" if d.interno or nombre == "memoria" else "13px"
    assert f"font-size:{fuente}" in html, f"fuente {fuente}"

    importes = re.findall(r">-?[\d.]+,\d{2} €<", html)
    assert importes, "los importes van en su celda, en formato es-ES (no embebidos en una frase)"

    assert isinstance(d.metricas_dashboard(datos), dict), "metricas_dashboard devuelve un dict"


def test_el_catalogo_no_duplica_modulos() -> None:
    assert len(NOMBRES) == len(set(NOMBRES))


def test_los_internos_estan_marcados(lineas_por_anio: dict[int, list]) -> None:
    """Duplicados no se le enseña al cliente; la conciliación sí."""
    internos = {d.nombre for d in modulos.listar_todos() if d.interno}
    assert "duplicados" in internos
    assert "conciliacion" not in internos
    assert "memoria" not in internos


def test_la_memoria_declara_lo_que_no_se_puede_sacar_del_erp(lineas_por_anio: dict[int, list]) -> None:
    """REQ-08 estimaba inmovilizado y vencimientos: aquí se declaran como pendientes, no se inventan."""
    d = modulos.obtener("memoria")
    datos = d.calcular({y: lineas_por_anio[y] for y in modulos.anios_necesarios("memoria", 2025)},
                       {**CTX, **d.parametros})
    avisos = " ".join(datos.get("avisos") or []).lower()
    assert avisos, "la Memoria tiene que declarar los cuadros que hay que completar a mano"
    assert any(p in avisos for p in ("mano", "estimad", "no se puede", "25", "vencimiento"))


def test_las_constantes_de_maquetacion_son_las_acordadas() -> None:
    assert (inf.ANCHO_CLIENTE, inf.ANCHO_MEMORIA) == (780, 800)
    assert (inf.FUENTE_CLIENTE, inf.FUENTE_MEMORIA) == ("13px", "11px")
    assert inf.AZUL == "#1a4b8c" and inf.NEGATIVO == "#c62828"
