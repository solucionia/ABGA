"""Pruebas contra los datos REALES de ABGA (los fixtures de `fixtures/`, fuera de git).

Son la versión con `assert` de `backend/scripts/verificar_nucleo.py`: mismas comprobaciones, pero
con nombre de prueba, mensaje de fallo legible y compatibles con `pytest -k` y la cobertura. Se
omiten solas cuando no hay fixtures (la CI no tiene datos del cliente).

Uso:  ./.venv/bin/python -m pytest -m datos_reales
"""

from __future__ import annotations

import re

import pytest

from app import informes as inf
from app.ledger import comprobar_cuadre, detectar_cierre, lineas_de_asientos
from app.modulos import dashboard, pyg

pytestmark = pytest.mark.datos_reales

CTX = {"empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": 2025, "year_anterior": 2024,
       "nombre_mes": "septiembre", "trimestre": 3, "email": ""}


@pytest.fixture
def reales(asientos_reales: dict[int, list[dict]]) -> dict[int, list]:
    if 2025 not in asientos_reales:
        pytest.skip("falta el fixture de 2025")
    return {y: lineas_de_asientos(a) for y, a in asientos_reales.items()}


def test_el_libro_real_cuadra(reales: dict[int, list]) -> None:
    cuadre = comprobar_cuadre(reales[2025])
    assert abs(cuadre["descuadre"]) <= 5, f"el libro no cuadra: {cuadre}"
    assert cuadre["n_lineas"] > 1_000, "el fixture tiene que traer el ejercicio entero, no una página"


def test_cobertura_completa_del_ejercicio(asientos_reales: dict[int, list]) -> None:
    """El defecto del sistema anterior: informar sobre 200 de 1.531 asientos sin decirlo."""
    assert len(asientos_reales[2025]) > 200, \
        "si el fixture trae ~200 asientos es que está truncado a una página del ERP"


def test_el_cierre_del_ejercicio_real_es_coherente(reales: dict[int, list]) -> None:
    """Si el extracto trae la regularización hay que apartarla, y si no, no se toca nada.

    Ojo: los fixtures son extractos y **no siempre traen los asientos de cierre ni la cuenta 129**
    (en 2025 no aparece ninguna línea con 129). El caso «cerrado» se prueba con datos sintéticos
    en `test_dominio.py`; aquí sólo se comprueba que el libro real no se altere por error.
    """
    cierre = detectar_cierre(reales[2025])
    if cierre["cerrado"]:
        assert cierre["resultado_libro"] != 0.0
        assert cierre["n_lineas_fuera"] > 0
        assert cierre["lineas_operativas"], "quedan líneas operativas tras apartar el cierre"
    else:
        assert cierre["n_lineas_fuera"] == 0
        assert cierre["lineas_operativas"] == reales[2025]


def test_los_huecos_conocidos_del_extracto(asientos_reales: dict[int, list]) -> None:
    """Deja escrito qué NO trae el fixture, para no cuadrar un balance contra datos incompletos.

    Ni asiento de apertura, ni cuentas 28x (amortización acumulada), ni 10x-12x (capital y
    reservas), ni tesorería 57x, ni asiento de regularización. No son despistes del cálculo: son
    huecos del extracto, y por eso el informe declara avisos en lugar de inventar las cifras.
    """
    cuentas = {str(d.get("Cuenta") or "")[:3]
               for a in asientos_reales.get(2025, []) for d in a.get("Detalles") or []}
    assert not any(c.startswith("57") for c in cuentas), "el extracto de 2025 no trae tesorería (57x)"
    assert "129" not in cuentas, "el extracto no trae la regularización (129)"


def test_pyg_real_cuadra_y_su_composicion_es_la_esperada(reales: dict[int, list]) -> None:
    d = pyg.calcular_lineas(reales[2025], reales.get(2024, []))
    assert abs(d["totalActivo"] - d["totalPasivo"]) <= 1.0, \
        f"balance descuadrado: activo={d['totalActivo']} pasivo+pn={d['totalPasivo']}"
    assert abs(d["totalActivo"] - (d["activoNoCorriente"] + d["activoCorriente"])) <= 0.5
    assert abs(d["activoNoCorriente"] - (d["inmovIntangible"] + d["inmovMaterial"]
                                        + d["inversionesLP"])) <= 0.5
    assert d["cuadre"]["huerfanas_total"] == 0, f"cuentas sin clasificar: {d['cuadre']['huerfanas']}"


def test_el_panel_real_suma_lo_mismo_que_el_informe(reales: dict[int, list]) -> None:
    informe = pyg.calcular_lineas(reales[2025], reales.get(2024, []))
    datos = dashboard.calcular({2025: reales[2025], 2024: reales.get(2024, []), 2023: []}, CTX)
    assert abs(sum(f["ingresos"] for f in datos["mensual"]) - informe["totalIngresos"]) <= 1.0
    assert len(datos["mensual"]) == 12
    assert len(datos["comparativa"]) == 3


@pytest.mark.parametrize("modulo", [pyg, dashboard])
def test_maquetacion_de_los_informes_reales(modulo, reales: dict[int, list]) -> None:
    """Las convenciones del cliente: HTML puro, Arial, ancho 780, colores de la casa y pie."""
    datos = (modulo.calcular_lineas(reales[2025], reales.get(2024, []))
             if modulo is pyg else
             modulo.calcular({2025: reales[2025], 2024: reales.get(2024, []), 2023: []}, CTX))
    html = modulo.informe_html(datos, CTX)
    assert html.lstrip().startswith("<div"), "el HTML debe empezar por <div (sin markdown)"
    assert "```" not in html and "<h1" not in html.lower()
    assert "Arial" in html and "style=" in html
    assert inf.AZUL in html and inf.NEGATIVO in html
    assert "max-width:780px" in html
    assert inf.PIE_CLIENTE.split(" · ")[0] in html
    assert re.search(r">-?[\d.]+,\d{2} €<", html), "los importes van en su celda y en formato es-ES"
