"""Los 13 módulos, con datos sintéticos y en la CI: que el documento sea HTML de verdad.

`test_modulos_contrato.py` comprueba lo mismo contra los fixtures reales del ERP, que **no están en un
clon ni en la CI**: allí se omite. Por eso el informe de Proyecciones pudo estar devolviendo el cuerpo
metido en una tupla de un elemento (`('<table …',)`, con las comillas escapadas dentro de la página)
sin que nada se pusiera rojo: el HTML seguía empezando por `<div`, que era lo único que se miraba.

Aquí no se comprueba el cálculo —cada módulo tiene sus pruebas— sino el **documento**: que se pueda
pegar en la página. Se ejecuta sin `.env`, sin fixtures y sin ERP.
"""

from __future__ import annotations

import pytest

from app import modulos
from app.ledger import lineas_de_asientos
from tests import sintetico

CTX = {"empresa": "Empresa sintética, S.L.", "cod_empresa": "0000", "year": 2025,
       "year_anterior": 2024, "nombre_mes": "septiembre", "trimestre": 3, "email": ""}


@pytest.fixture(scope="module")
def lineas_por_anio() -> dict[int, list]:
    """Un ejercicio contable completo y sintético (el mismo para todos los años que pida cada módulo).

    Es a propósito: lo que se mira es el documento, no la aritmética de un ejercicio concreto.
    """
    ejercicio = lineas_de_asientos(sintetico.anio(2024))
    return dict.fromkeys(range(2018, 2030), ejercicio)


def _cuerpo_del_documento(html: str) -> str:
    """Lo que va dentro del cuerpo del informe (después del marco que pone `informes.envoltura`)."""
    marca = "border-top:none"
    i = html.find(marca)
    if i < 0:
        pytest.fail("el documento no lleva el marco de `informes.envoltura`")
    return html[html.index(">", i) + 1:]


@pytest.mark.parametrize("nombre", [d.nombre for d in modulos.listar_todos()])
def test_el_informe_es_un_documento(nombre: str, lineas_por_anio: dict[int, list]) -> None:
    """Ni `repr` de una tupla, ni comillas escapadas, ni el cuerpo como texto: HTML."""
    d = modulos.obtener(nombre)
    assert d.disponible, f"el módulo {nombre} no se pudo importar: {d.error}"

    ctx = {**CTX, **d.parametros}
    por_anio = {y: lineas_por_anio[y] for y in modulos.anios_necesarios(nombre, 2025)}
    datos = d.calcular(por_anio, ctx)
    assert isinstance(datos, dict), "calcular() devuelve los números en un dict"

    html = d.informe_html(datos, ctx)
    assert isinstance(html, str), f"informe_html devolvió {type(html).__name__}, no texto"
    assert html.lstrip().startswith("<div"), "el HTML empieza por <div (sin markdown)"

    # El fallo que se escapa: el cuerpo envuelto en una tupla o en un `str()` de sí mismo. Se ve como
    # comillas escapadas y paréntesis dentro del documento (y en pantalla, como texto en vez de tabla).
    assert "\\'" not in html, f"{nombre}: comillas escapadas dentro del HTML (¿una tupla o un repr?)"
    assert "('" not in html and "',)" not in html, \
        f"{nombre}: el cuerpo va dentro de una tupla en vez de ser el HTML"

    cuerpo = _cuerpo_del_documento(html)
    assert cuerpo.lstrip().startswith("<"), f"{nombre}: el cuerpo no empieza por una etiqueta"
    assert "</div>" in cuerpo, f"{nombre}: el cuerpo no trae HTML"


def test_los_trece_modulos_estan(lineas_por_anio: dict[int, list]) -> None:
    """Si un módulo deja de importarse, esto lo dice antes de que lo diga el portal."""
    assert len(modulos.listar_todos()) == 13
    for d in modulos.listar_todos():
        assert d.disponible, f"{d.nombre}: {d.error}"
