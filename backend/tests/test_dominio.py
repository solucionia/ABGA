"""Pruebas del dominio contable (`app/ledger.py`) y de la cadena PyG/balance/panel.

No usan datos del cliente: los números salen de `tests/sintetico.py`, así que corren en cualquier
máquina y en la CI. Que el balance cuadre al céntimo con datos propios es la prueba de que la
aritmética del informe no depende de las particularidades del fixture real.
"""

from __future__ import annotations

import pytest

from app import informes as inf
from app.ledger import (
    Linea,
    anio_de,
    comprobar_cuadre,
    detectar_cierre,
    fecha_a_int,
    fmt,
    lineas_de_asientos,
    mes_de,
    nombre_tercero,
    por_mes,
    por_tercero,
    saldos_por_cuenta,
    suma_acreedor,
    suma_deudor,
    trimestre_de,
)
from app.modulos import dashboard, pyg
from tests import sintetico as sin

CTX = {"empresa": "Sintética S.L.", "cod_empresa": "6091", "year": 2025, "year_anterior": 2024,
       "nombre_mes": "septiembre", "trimestre": 3, "email": ""}


@pytest.fixture
def lineas() -> list[Linea]:
    return lineas_de_asientos(sin.anio(2025))


@pytest.fixture
def lineas_cerradas() -> list[Linea]:
    return lineas_de_asientos(sin.anio(2025, cerrado=True))


# ---------------------------------------------------------------- integridad del libro

def test_el_libro_cuadra(lineas: list[Linea]) -> None:
    cuadre = comprobar_cuadre(lineas)
    assert cuadre["descuadre"] == 0.0
    assert cuadre["debe"] == sin.TOTAL_DEBE
    assert cuadre["haber"] == sin.TOTAL_HABER


def test_cada_asiento_cuadra_por_separado() -> None:
    """No basta con que el total cuadre: dos asientos descuadrados con signo contrario se anulan."""
    for a in sin.anio(2025):
        assert a["Debe"] == a["Haber"], a["Descripcion"]


def test_saldos_por_cuenta(lineas: list[Linea]) -> None:
    saldos = saldos_por_cuenta(lineas)
    assert saldos["572000000000"].deudor == 46_000.00
    assert saldos["430000000001"].deudor == 24_520.00
    assert saldos["700000000000"].acreedor == 12_000.00
    assert saldos["477000000000"].acreedor == 2_520.00
    assert saldos["400000000000"].acreedor == 4_840.00


def test_suma_deudor_y_acreedor_por_prefijo(lineas: list[Linea]) -> None:
    saldos = saldos_por_cuenta(lineas)
    assert suma_deudor(saldos, ["572"]) == 46_000.00
    assert suma_acreedor(saldos, ["400", "410"]) == 5_690.00


def test_el_recorte_a_cero_es_una_decision_explicita() -> None:
    """El sistema anterior hacía `Math.max(0, …)` siempre y ocultaba los saldos contrarios.

    Se comprueba que la función sabe devolver el saldo real (`recortar=False`) y que el recorte
    sigue disponible para quien lo pida a propósito.
    """
    lineas = lineas_de_asientos([
        sin.asiento(20250101, "1", 1, "FA/2025/00009-Cliente con saldo contrario",
                    [("430000000009", 1_000.00, 0.0), ("700000000000", 0.0, 1_000.00)], year=2025),
        sin.asiento(20250102, "9", 9, "Rectificación de la factura anterior",
                    [("430000000009", 0.0, 3_000.00), ("708000000000", 3_000.00, 0.0)], year=2025),
    ])
    saldos = saldos_por_cuenta(lineas)
    assert suma_deudor(saldos, ["430"], recortar=False) == -2_000.00
    assert suma_deudor(saldos, ["430"]) == 0.0


# ---------------------------------------------------------------- cierre del ejercicio

def test_ejercicio_abierto_no_se_confunde_con_cerrado(lineas: list[Linea]) -> None:
    cierre = detectar_cierre(lineas)
    assert cierre["cerrado"] is False
    assert cierre["n_lineas_fuera"] == 0
    assert cierre["lineas_operativas"] == lineas


def test_ejercicio_cerrado_aparta_regularizacion_y_cierre(lineas_cerradas: list[Linea]) -> None:
    cierre = detectar_cierre(lineas_cerradas)
    assert cierre["cerrado"] is True
    assert cierre["resultado_libro"] == sin.RESULTADO
    assert cierre["n_lineas_fuera"] == 16            # 5 del asiento de regularización + 11 del de cierre
    assert len(cierre["asientos_regularizacion"]) == 1
    assert len(cierre["asientos_cierre"]) == 1


def test_la_apertura_y_la_aplicacion_del_resultado_no_son_cierre() -> None:
    """Sólo se aparta lo que está fechado el 31/12 y toca la 129 con cuentas de gasto o ingreso."""
    asientos = sin.anio(2025) + [
        sin.asiento(20250115, "9", 4, "Aplicacion del resultado del ejercicio anterior",
                    [("129000000000", 2_000.00, 0.0), ("121000000000", 0.0, 2_000.00)], year=2025),
    ]
    cierre = detectar_cierre(lineas_de_asientos(asientos))
    assert cierre["cerrado"] is False
    assert cierre["n_lineas_fuera"] == 0
    assert cierre["resultado_libro"] == 0.0


# ---------------------------------------------------------------- utilidades del dominio

@pytest.mark.parametrize("entrada,esperado", [
    (20250101, 20250101), ("20250101", 20250101), (20250101.0, 20250101),
    ("2025-01-01", 20250101), (None, 0),
])
def test_fecha_a_int(entrada: object, esperado: int) -> None:
    assert fecha_a_int(entrada) == esperado


def test_mes_y_trimestre() -> None:
    assert mes_de(20250331) == 3
    assert anio_de(20250331) == 2025
    assert trimestre_de(20250331) == 1
    assert trimestre_de(20251001) == 4


def test_importes_en_formato_espanol() -> None:
    assert fmt(12_345.67) == "12.345,67 €"
    assert fmt(-1_234.5) == "-1.234,50 €"
    assert fmt(None) == "—"          # nunca "0,00 €" cuando el dato no existe
    assert inf.importe(-10.0).startswith("<span")     # coloreado, no texto con color dentro


@pytest.mark.parametrize("tercero,descripcion,esperado", [
    ("", "ED/2025/00001-MARÍA SERRA CAÑELLAS", "MARÍA SERRA CAÑELLAS"),
    ("", "OP/2025/00005-Avintia Proyectos Y Construcciones S.L.", "Avintia Proyectos Y Construcciones S.L."),
    # El caso que distingue «detrás del último guion» de «detrás del primero»: si el nombre
    # llevara guiones, cortar por el primero devolvería el resto de la descripción.
    ("", "OP/2025/00005-Proveedor-Dos S.A.", "Dos S.A."),
    ("Cliente SL", "FA/2025/00001-otra cosa", "Cliente SL"),
    ("", "Asiento sin guion", "Asiento sin guion"),
    ("", "", "(sin identificar)"),
])
def test_nombre_tercero(tercero: str, descripcion: str, esperado: str) -> None:
    """El campo `Tercero` llega vacío en los datos reales: el nombre va tras el último guion."""
    assert nombre_tercero(tercero, descripcion) == esperado


def test_agrupaciones_mensuales_y_por_tercero(lineas: list[Linea]) -> None:
    meses = por_mes(lineas)
    assert sorted(meses) == [1, 2, 3, 4]
    terceros = por_tercero(lineas, ["430", "400", "410"])
    nombres = {f["tercero"] for f in terceros}
    assert "Cliente Uno S.L." in nombres
    assert "Proveedor Dos S.A." in nombres


# ---------------------------------------------------------------- PyG, balance y panel

def test_la_cadena_de_resultados_es_coherente(lineas: list[Linea]) -> None:
    d = pyg.calcular_lineas(lineas, lineas)
    assert d["totalIngresos"] == d["ventas"] + d["otrosIngresos"] == sin.VENTAS
    assert d["ebitda"] == (d["totalIngresos"] - d["aprovisionamientos"] - d["gastosPersonal"]
                           - d["otrosGastosExplot"])
    assert d["ebit"] == d["ebitda"] - d["amortizaciones"]
    assert d["rai"] == d["ebit"] + d["ingresosFinancieros"] - d["gastosFinancieros"]
    assert d["resultadoNeto"] == d["rai"] - d["impuesto"] == sin.RESULTADO
    assert d["cashFlow"] == d["resultadoNeto"] + d["amortizaciones"]


def test_el_balance_cuadra_y_no_hay_cuentas_huerfanas(lineas: list[Linea]) -> None:
    """Activo == PN + pasivo, y ninguna cuenta del libro se queda sin clasificar."""
    d = pyg.calcular_lineas(lineas, lineas)
    assert d["totalActivo"] == sin.ACTIVO
    assert d["totalPasivo"] == sin.PATRIMONIO_Y_PASIVO
    assert d["cuadre"]["diferencia"] == 0.0
    assert d["cuadre"]["huerfanas"] == []
    assert d["totalActivo"] == d["activoNoCorriente"] + d["activoCorriente"]


def test_los_gastos_de_explotacion_no_incluyen_el_impuesto_de_sociedades(lineas: list[Linea]) -> None:
    """El defecto del sistema anterior: la 630 estaba dentro y se restaba otra vez tras el RAI."""
    assert "630" not in pyg.P_OTROS_GASTOS
    d = pyg.calcular_lineas(lineas, lineas)
    assert d["impuesto"] == 0.0        # en el ejercicio sintético no hay asiento de impuesto


def test_el_panel_es_coherente_con_el_informe(lineas: list[Linea]) -> None:
    datos = dashboard.calcular({2025: lineas, 2024: lineas}, CTX)
    informe = pyg.calcular_lineas(lineas, lineas)
    assert len(datos["mensual"]) == 12
    assert sum(f["ingresos"] for f in datos["mensual"]) == informe["totalIngresos"]
    assert len(datos["comparativa"]) == 3, "la comparativa trae siempre tres ejercicios"
    assert [c["year"] for c in datos["comparativa"]] == [2025, 2024, 2023], "del más nuevo al más antiguo"
    assert datos["avisos"], "un ejercicio con meses sin movimiento tiene que avisarlo"
