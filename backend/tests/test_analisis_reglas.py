"""Las comprobaciones del catálogo, una a una (la segunda tanda: Fase 8, de 32 a 50).

Lo que se prueba aquí es la **semántica de cada regla nueva**: con estos apuntes, ¿sale rojo, naranja,
verde o gris? Se fabrica el ejercicio con `tests.sintetico` (asientos que cuadran por construcción, sin
`.env` ni ERP) y se llama a la regla con el contexto que arma el propio módulo (`_contexto`), que es la
misma puerta que usa el motor: si una regla cambia de criterio, esto se pone rojo antes que el cliente.

Las tres primeras pruebas no miran una regla, sino el **contrato del catálogo**: cuántas hay, de qué
familias y que todo criterio ajustable esté declarado (un umbral que se lee en una regla y no está en
`UMBRALES_POR_DEFECTO`/`ESQUEMA_UMBRALES` es un ajuste que el cliente no puede hacer y el informe no
publica).
"""

from __future__ import annotations

from typing import Any

from app.ledger import detectar_cierre, lineas_de_asientos
from app.modulos import analisis as mod
from tests import sintetico

CTX: dict[str, Any] = {"empresa": "Empresa sintética, S.L.", "cod_empresa": "0000", "year": 2025,
                       "year_anterior": 2024, "nombre_mes": "diciembre", "trimestre": 4, "email": ""}


def a(fecha: int, documento: int, descripcion: str, movimientos: list[tuple[str, float, float]],
      *, year: int = 2025) -> dict[str, Any]:
    """Un asiento del ERP en una línea, para no repetir la firma completa en cada prueba."""
    return sintetico.asiento(fecha, "1", documento, descripcion, movimientos, year=year)


def operativas(asientos: list[dict[str, Any]]) -> list:
    """Lo mismo que hace el servicio al cargar: si el ejercicio está cerrado, se quedan fuera el
    asiento de regularización y el de cierre. Analizar con ellos dentro da un panel a cero (gastos e
    ingresos se anulan), así que las pruebas tienen que pasar por aquí, como pasa el portal."""
    lineas = lineas_de_asientos(asientos)
    cierre = detectar_cierre(lineas)
    return cierre["lineas_operativas"] if cierre["cerrado"] else lineas


def ctx_de(*asientos: dict[str, Any], year: int = 2025,
           anteriores: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """El contexto del motor: el ejercicio que se prueba y, si hace falta, el anterior."""
    return mod._contexto({year: operativas(list(asientos)),
                          year - 1: operativas(list(anteriores or []))},
                         {**CTX, "year": year})


# ---------------------------------------------------------------- el contrato del catálogo

def test_el_catalogo_tiene_cincuenta_comprobaciones() -> None:
    """El número que dicen el README y la arquitectura, comprobado donde se puede comprobar."""
    por_familia: dict[str, int] = {}
    for r in mod.REGLAS:
        por_familia[r.familia] = por_familia.get(r.familia, 0) + 1
    assert len(mod.REGLAS) == 50
    assert por_familia == {"contable": 18, "fiscal": 12, "financiero": 13, "mercantil": 6,
                           "laboral": 1}


def test_cada_umbral_se_puede_ajustar_y_se_publica() -> None:
    """Un criterio con valor por defecto y sin esquema es un criterio que el cliente no puede ajustar."""
    assert set(mod.UMBRALES_POR_DEFECTO) == set(mod.ESQUEMA_UMBRALES)
    for clave, ficha in mod.ESQUEMA_UMBRALES.items():
        assert ficha["unidad"] and ficha["para"], f"umbral sin unidad o sin explicación: {clave}"
        assert ficha["min"] <= mod.UMBRALES_POR_DEFECTO[clave] <= ficha["max"], \
            f"el valor por defecto de {clave} se sale del rango que se admite al guardarlo"


def test_los_umbrales_nuevos_llegan_a_su_regla() -> None:
    """Ajustar un umbral por cliente tiene que cambiar el veredicto de la regla, no quedarse en la ficha."""
    apuntes = [a(20251220, 1, "IVA soportado", [("472000000000", 1000.0, 0.0),
                                                ("410000000001", 0.0, 1000.0)])]
    por_defecto = mod._r_iva_compensar(ctx_de(*apuntes))
    ajustado = mod._r_iva_compensar({**ctx_de(*apuntes),
                                     "u": {**mod.UMBRALES_POR_DEFECTO, "iva_a_compensar": 500.0}})
    assert por_defecto["nivel"] == mod.OK and ajustado["nivel"] == mod.AVISO


# ---------------------------------------------------------------- contables

def test_existencias_en_negativo() -> None:
    """Una salida de almacén sin entrada deja el inventario en negativo: es un error, no un dato."""
    c = ctx_de(a(20250110, 1, "Salida de almacén", [("610000000000", 500.0, 0.0),
                                                    ("300000000000", 0.0, 500.0)]))
    r = mod._r_existencias_negativas(c)
    assert r["nivel"] == mod.ALERTA
    assert r["importe"] == 500.0


def test_existencias_correctas() -> None:
    c = ctx_de(a(20250110, 1, "Entrada de almacén", [("300000000000", 500.0, 0.0),
                                                     ("400000000001", 0.0, 500.0)]))
    assert mod._r_existencias_negativas(c)["nivel"] == mod.OK


def test_amortizacion_por_encima_del_inmovilizado() -> None:
    c = ctx_de(a(20250101, 1, "Alta de maquinaria", [("211000000000", 1000.0, 0.0),
                                                     ("572000000000", 0.0, 1000.0)]),
               a(20251231, 2, "Amortización", [("681000000000", 1500.0, 0.0),
                                               ("281000000000", 0.0, 1500.0)]))
    r = mod._r_amortizacion(c)
    assert r["nivel"] == mod.ALERTA
    assert r["importe"] == 500.0


def test_amortizacion_normal() -> None:
    c = ctx_de(a(20250101, 1, "Alta de maquinaria", [("211000000000", 1000.0, 0.0),
                                                     ("572000000000", 0.0, 1000.0)]),
               a(20251231, 2, "Amortización", [("681000000000", 200.0, 0.0),
                                               ("281000000000", 0.0, 200.0)]))
    assert mod._r_amortizacion(c)["nivel"] == mod.OK


def test_sin_129_no_hay_resultado_pendiente() -> None:
    """Un ejercicio abierto no tiene la 129: no hay nada que aplicar."""
    c = ctx_de(a(20251220, 1, "Venta", [("430000000001", 1210.0, 0.0),
                                        ("700000000000", 0.0, 1000.0),
                                        ("477000000000", 0.0, 210.0)]))
    assert mod._r_resultado_sin_aplicar(c)["nivel"] == mod.OK


def test_resultado_del_ano_anterior_sin_aplicar() -> None:
    """La apertura trae el beneficio del año anterior en la 129 y nadie lo ha repartido."""
    c = ctx_de(a(20250101, 1, "Apertura del ejercicio", [("430000000001", 2000.0, 0.0),
                                                         ("129000000000", 0.0, 2000.0)]))
    r = mod._r_resultado_sin_aplicar(c)
    assert r["nivel"] == mod.AVISO and r["importe"] == 2000.0


def test_resultado_aplicado() -> None:
    """Apertura con la 129 y su aplicación a reservas: la cuenta queda a cero."""
    c = ctx_de(a(20250101, 1, "Apertura del ejercicio", [("430000000001", 2000.0, 0.0),
                                                         ("129000000000", 0.0, 2000.0)]),
               a(20250630, 2, "Aplicación del resultado", [("129000000000", 2000.0, 0.0),
                                                           ("113000000000", 0.0, 2000.0)]))
    assert mod._r_resultado_sin_aplicar(c)["nivel"] == mod.OK


def test_la_aplicacion_sin_la_apertura_no_se_juzga() -> None:
    """Si sólo está el asiento de aplicación (sin apertura), la 129 queda en el Debe: gris, no verde."""
    c = ctx_de(a(20250630, 2, "Aplicación del resultado", [("129000000000", 2000.0, 0.0),
                                                           ("113000000000", 0.0, 2000.0)]))
    assert mod._r_resultado_sin_aplicar(c)["nivel"] == mod.NO_EVALUABLE


def test_nominas_repetidas() -> None:
    """La misma nómina dos veces: mismo trabajador, mismo mes y mismo importe."""
    nomina = [("640000000000", 1500.0, 0.0), ("476000000000", 0.0, 1500.0)]
    c = ctx_de(a(20250131, 1, "NOMINA/2025/00001", nomina),
               a(20250131, 2, "NOMINA/2025/00001", nomina))
    r = mod._r_nominas_repetidas(c)
    assert r["nivel"] == mod.AVISO
    assert r["importe"] == 1500.0


def test_nominas_de_meses_distintos_no_son_repeticion() -> None:
    nomina = [("640000000000", 1500.0, 0.0), ("476000000000", 0.0, 1500.0)]
    c = ctx_de(a(20250131, 1, "NOMINA/2025/00001", nomina),
               a(20250228, 2, "NOMINA/2025/00002", nomina))
    assert mod._r_nominas_repetidas(c)["nivel"] == mod.OK


def test_anticipos_de_clientes() -> None:
    c = ctx_de(a(20250610, 1, "Anticipo de Cliente Uno", [("572000000000", 500.0, 0.0),
                                                          ("438000000000", 0.0, 500.0)]))
    r = mod._r_anticipos(c)
    assert r["nivel"] == mod.AVISO and r["importe"] == 500.0


# ---------------------------------------------------------------- fiscales

def test_iva_a_compensar_por_encima_del_limite() -> None:
    c = ctx_de(a(20251220, 1, "IVA soportado", [("472000000000", 4000.0, 0.0),
                                                ("410000000001", 0.0, 4000.0)]))
    r = mod._r_iva_compensar(c)
    assert r["nivel"] == mod.AVISO and r["importe"] == 4000.0


def test_retenciones_de_trabajo_sin_contabilizar() -> None:
    """Hay nóminas y ninguna cuenta 4751: el 111 y el 190 pueden estar sin contabilizar."""
    c = ctx_de(a(20250131, 1, "NOMINA/2025/00001", [("640000000000", 2000.0, 0.0),
                                                    ("476000000000", 0.0, 2000.0)]))
    r = mod._r_retenciones_trabajo(c)
    assert r["nivel"] == mod.AVISO and r["importe"] == 2000.0


def test_retenciones_de_trabajo_contabilizadas() -> None:
    c = ctx_de(a(20250131, 1, "NOMINA/2025/00001", [("640000000000", 2000.0, 0.0),
                                                    ("475100000000", 0.0, 300.0),
                                                    ("476000000000", 0.0, 1700.0)]))
    assert mod._r_retenciones_trabajo(c)["nivel"] == mod.OK


def test_impuesto_de_sociedades_sin_contabilizar() -> None:
    c = ctx_de(a(20251220, 1, "Venta con beneficio", [("430000000001", 1210.0, 0.0),
                                                      ("700000000000", 0.0, 1000.0),
                                                      ("477000000000", 0.0, 210.0)]))
    r = mod._r_is_contabilizado(c)
    assert r["nivel"] == mod.AVISO
    assert r["importe"] == 180.0        # 18 % de 1.000 € de resultado antes de impuestos


def test_iva_del_cuarto_trimestre_que_falta() -> None:
    c = ctx_de(a(20250215, 1, "Venta de febrero", [("430000000001", 1210.0, 0.0),
                                                   ("700000000000", 0.0, 1000.0),
                                                   ("477000000000", 0.0, 210.0)]),
               a(20250315, 2, "Venta de marzo", [("430000000001", 605.0, 0.0),
                                                 ("700000000000", 0.0, 500.0),
                                                 ("477000000000", 0.0, 105.0)]))
    assert mod._r_iva_4t(c)["nivel"] == mod.AVISO


def test_iva_del_cuarto_trimestre_presente() -> None:
    c = ctx_de(a(20250215, 1, "Venta de febrero", [("430000000001", 1210.0, 0.0),
                                                   ("700000000000", 0.0, 1000.0),
                                                   ("477000000000", 0.0, 210.0)]),
               a(20251115, 2, "Venta de noviembre", [("430000000001", 605.0, 0.0),
                                                     ("700000000000", 0.0, 500.0),
                                                     ("477000000000", 0.0, 105.0)]))
    assert mod._r_iva_4t(c)["nivel"] == mod.OK


# ---------------------------------------------------------------- financieras

def test_concentracion_de_proveedores() -> None:
    c = ctx_de(a(20250310, 1, "Compra al Proveedor Uno", [("600000000000", 1000.0, 0.0),
                                                          ("400000000001", 0.0, 1000.0)]),
               a(20250320, 2, "Compra al Proveedor Dos", [("600000000000", 9000.0, 0.0),
                                                          ("400000000002", 0.0, 9000.0)]))
    r = mod._r_concentracion_proveedores(c)
    assert r["nivel"] == mod.ALERTA
    assert r["importe"] == 9000.0


def test_antiguedad_de_la_deuda_de_proveedores() -> None:
    """Una factura de enero que sigue viva a final de año: más de 90 días con saldo."""
    c = ctx_de(a(20250115, 1, "FA/2025/00001-Proveedor Viejo S.L.", [("600000000000", 1000.0, 0.0),
                                                                    ("400000000001", 0.0, 1000.0)]),
               a(20251220, 2, "Cobro a cliente", [("572000000000", 100.0, 0.0),
                                                  ("700000000000", 0.0, 100.0)]))
    r = mod._r_antiguedad_proveedores(c)
    assert r["nivel"] == mod.AVISO
    assert r["importe"] == 1000.0


def test_clientes_vencidos_sin_deterioro() -> None:
    c = ctx_de(a(20250115, 1, "FA/2025/00001-Cliente Moroso S.L.", [("430000000001", 12000.0, 0.0),
                                                                    ("700000000000", 0.0, 12000.0)]),
               a(20251220, 2, "Compra", [("600000000000", 100.0, 0.0),
                                         ("400000000001", 0.0, 100.0)]))
    r = mod._r_deterioro_clientes(c)
    assert r["nivel"] == mod.ALERTA
    assert r["importe"] == 12000.0


def test_clientes_vencidos_con_deterioro() -> None:
    c = ctx_de(a(20250115, 1, "FA/2025/00001-Cliente Moroso S.L.", [("430000000001", 12000.0, 0.0),
                                                                    ("700000000000", 0.0, 12000.0)]),
               a(20251231, 3, "Deterioro de clientes", [("694000000000", 12000.0, 0.0),
                                                        ("490000000000", 0.0, 12000.0)]))
    assert mod._r_deterioro_clientes(c)["nivel"] == mod.OK


def test_carga_financiera_sobre_el_resultado() -> None:
    c = ctx_de(a(20251220, 1, "Venta", [("430000000001", 12100.0, 0.0),
                                        ("700000000000", 0.0, 10000.0),
                                        ("477000000000", 0.0, 2100.0)]),
               a(20251231, 2, "Intereses del préstamo", [("662000000000", 6000.0, 0.0),
                                                         ("572000000000", 0.0, 6000.0)]))
    r = mod._r_carga_financiera(c)
    assert r["nivel"] == mod.AVISO
    assert r["magnitud"]["unidad"] == "%" and r["magnitud"]["valor"] == 60.0


def test_rotacion_de_existencias_lenta() -> None:
    c = ctx_de(a(20250110, 1, "Compra de mercadería", [("600000000000", 100000.0, 0.0),
                                                       ("400000000001", 0.0, 100000.0)]),
               a(20250120, 2, "Entrada en almacén", [("300000000000", 50000.0, 0.0),
                                                     ("610000000000", 0.0, 50000.0)]))
    r = mod._r_rotacion_existencias(c)
    assert r["nivel"] == mod.AVISO
    # 365 días: el módulo mide sobre el **consumo** (compras menos variación de existencias), no
    # sobre la compra bruta. 50.000 € de almacén sobre 50.000 € de consumo dan un año entero.
    assert r["magnitud"] == {"valor": 365, "unidad": "días"}


def test_margen_neto_que_cae() -> None:
    anteriores = [a(20241220, 1, "Venta", [("430000000001", 12100.0, 0.0),
                                           ("700000000000", 0.0, 10000.0),
                                           ("477000000000", 0.0, 2100.0)], year=2024),
                  a(20241231, 2, "Gasto", [("620000000000", 8000.0, 0.0),
                                           ("410000000001", 0.0, 8000.0)], year=2024)]
    c = ctx_de(a(20251220, 1, "Venta", [("430000000001", 12100.0, 0.0),
                                        ("700000000000", 0.0, 10000.0),
                                        ("477000000000", 0.0, 2100.0)]),
               a(20251231, 2, "Gasto", [("620000000000", 9900.0, 0.0),
                                        ("410000000001", 0.0, 9900.0)]),
               anteriores=anteriores)
    r = mod._r_margen_neto(c)
    assert r["nivel"] == mod.ALERTA
    assert r["magnitud"]["valor"] == 19.0


# ---------------------------------------------------------------- mercantiles

def test_capital_pendiente_de_desembolsar() -> None:
    c = ctx_de(sintetico.apertura(2025),
               a(20250310, 2, "Desembolso pendiente", [("103000000000", 10000.0, 0.0),
                                                       ("556000000000", 0.0, 10000.0)]))
    r = mod._r_capital_desembolsado(c)
    assert r["nivel"] == mod.AVISO
    assert r["importe"] == 10000.0
    assert r["magnitud"]["valor"] == 25.0        # sobre los 40.000 € de capital de la apertura


def test_sociedad_sin_actividad() -> None:
    """Con sólo apertura y cierre no hay ventas ni gastos: la sociedad está dormida."""
    c = ctx_de(sintetico.apertura(2025))
    assert mod._r_sociedad_inactiva(c)["nivel"] == mod.AVISO


def test_perdidas_acumuladas_que_crecen() -> None:
    anteriores = [a(20241231, 1, "Pérdidas del 2024", [("121000000000", 3000.0, 0.0),
                                                       ("129000000000", 0.0, 3000.0)], year=2024)]
    c = ctx_de(a(20251231, 1, "Pérdidas del 2025", [("121000000000", 5000.0, 0.0),
                                                    ("129000000000", 0.0, 5000.0)]),
               anteriores=anteriores)
    r = mod._r_aplicacion_resultado(c)
    assert r["nivel"] == mod.AVISO
    assert r["importe"] == 2000.0
