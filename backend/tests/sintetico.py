"""Datos sintéticos con forma de ERP: lo que permite probar el dominio sin datos del cliente.

Un ejercicio pequeño pero contablemente completo (apertura, venta con IVA repercutido, compra con
IVA soportado, nómina, servicios con retención) y, opcionalmente, el cierre. Los importes están
elegidos para que todo cuadre al céntimo y se pueda afirmar una cifra exacta en las pruebas:

    ΣDebe = ΣHaber                                    85.360,00
    Activo = 71.360,00 = PN (40.000) + resultado (2.000) + pasivo (29.360)

El formato es el del ERP (`/api/apuntes/`): asiento con `Detalles`, importes en `Debe`/`Haber`,
`Fecha` en entero YYYYMMDD y `Tercero` vacío (como en los datos reales de ABGA, el nombre va al
final de la descripción detrás del último guion).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _linea(cuenta: str, debe: float, haber: float, fecha: int, descripcion: str,
           documento: str, serie: str, ejercicio: str, n: int) -> dict[str, Any]:
    return {
        "Ejercicio": ejercicio, "Serie": serie, "Documento": documento, "Linea": n,
        "Cuenta": cuenta, "Fecha": fecha, "Debe": round(debe, 2), "Haber": round(haber, 2),
        "Descripcion": descripcion, "Contrapartida": "", "Justificante": "",
        "PunteoBancario": None, "PunteoCuenta": None, "Tercero": "",
    }


def asiento(fecha: int, serie: str, documento: int, descripcion: str,
            movimientos: Iterable[tuple[str, float, float]], *, year: int) -> dict[str, Any]:
    """Un asiento del ERP a partir de movimientos `(cuenta, debe, haber)`.

    Exige que cuadre: si no cuadra, la prueba no vale, así que salta en el propio generador.
    """
    movs = list(movimientos)
    debe = round(sum(d for _, d, _ in movs), 2)
    haber = round(sum(h for _, _, h in movs), 2)
    assert abs(debe - haber) < 0.005, f"el asiento «{descripcion}» no cuadra: {debe} vs {haber}"
    return {
        "Ejercicio": str(year), "Serie": serie, "Documento": documento, "TipoAsiento": 1,
        "Fecha": fecha, "Descripcion": descripcion, "Debe": debe, "Haber": haber,
        "Detalles": [_linea(c, d, h, fecha, descripcion, str(documento), serie, str(year), i + 1)
                     for i, (c, d, h) in enumerate(movs)],
        "DetallesAnalitica": [],
    }


def apertura(year: int) -> dict[str, Any]:
    return asiento(year * 10000 + 101, "9", 1, "Apertura del ejercicio", [
        ("572000000000", 50_000.00, 0.0),      # banco
        ("430000000001", 10_000.00, 0.0),      # clientes
        ("100000000000", 0.0, 40_000.00),      # capital
        ("170000000000", 0.0, 20_000.00),      # deuda a largo plazo
    ], year=year)


def actividad(year: int) -> list[dict[str, Any]]:
    """Los asientos de explotación del ejercicio, sin apertura ni cierre."""
    return [
        asiento(year * 10000 + 215, "1", 1, f"FA/{year}/00001-Cliente Uno S.L.", [
            ("430000000001", 14_520.00, 0.0),  # clientes (12.000 + 21% IVA)
            ("700000000000", 0.0, 12_000.00),  # ventas
            ("477000000000", 0.0, 2_520.00),   # IVA repercutido
        ], year=year),
        asiento(year * 10000 + 310, "2", 1, f"OP/{year}/00007-Proveedor Dos S.A.", [
            ("600000000000", 4_000.00, 0.0),   # compras
            ("472000000000", 840.00, 0.0),     # IVA soportado
            ("400000000000", 0.0, 4_840.00),   # proveedores
        ], year=year),
        asiento(year * 10000 + 331, "3", 1, "NOMINA MARZO", [
            ("640000000000", 5_000.00, 0.0),   # sueldos y salarios
            ("476000000000", 0.0, 1_000.00),   # organismos de la Seguridad Social
            ("572000000000", 0.0, 4_000.00),   # banco
        ], year=year),
        asiento(year * 10000 + 420, "2", 2, f"OP/{year}/00012-Asesor Externo S.L.", [
            ("623000000000", 1_000.00, 0.0),   # servicios de profesionales
            ("475100000000", 0.0, 150.00),     # Hacienda, retenciones practicadas
            ("410000000000", 0.0, 850.00),     # acreedores
        ], year=year),
    ]


def regularizacion(year: int) -> dict[str, Any]:
    """Asiento de regularización: deja a cero las cuentas de gasto e ingreso contra la 129."""
    return asiento(year * 10000 + 1231, "9", 2, "Regularizacion de gastos e ingresos", [
        ("600000000000", 0.0, 4_000.00),
        ("640000000000", 0.0, 5_000.00),
        ("623000000000", 0.0, 1_000.00),
        ("700000000000", 12_000.00, 0.0),
        ("129000000000", 0.0, 2_000.00),       # resultado del ejercicio (beneficio)
    ], year=year)


def cierre(year: int) -> dict[str, Any]:
    """Asiento de cierre del balance: activo y pasivo a cero."""
    return asiento(year * 10000 + 1231, "9", 3, "Cierre del ejercicio", [
        ("100000000000", 40_000.00, 0.0),
        ("170000000000", 20_000.00, 0.0),
        ("400000000000", 4_840.00, 0.0),
        ("476000000000", 1_000.00, 0.0),
        ("475100000000", 150.00, 0.0),
        ("477000000000", 2_520.00, 0.0),
        ("410000000000", 850.00, 0.0),
        ("129000000000", 2_000.00, 0.0),
        ("572000000000", 0.0, 46_000.00),
        ("430000000001", 0.0, 24_520.00),
        ("472000000000", 0.0, 840.00),
    ], year=year)


def anio(year: int, *, con_apertura: bool = True, cerrado: bool = False) -> list[dict[str, Any]]:
    """Un ejercicio completo, en el formato que devuelve `/api/apuntes/`."""
    asientos = ([apertura(year)] if con_apertura else []) + actividad(year)
    if cerrado:
        asientos = asientos + [regularizacion(year), cierre(year)]
    return asientos


# Cifras de referencia del ejercicio sintético, para afirmar con números en las pruebas.
TOTAL_DEBE = 85_360.00
TOTAL_HABER = 85_360.00
ACTIVO = 71_360.00          # 572: 46.000 + 430: 24.520 + 472: 840
PATRIMONIO_Y_PASIVO = 71_360.00   # 40.000 + 29.360 (20.000 + 4.840 + 1.000 + 150 + 2.520 + 850)
RESULTADO = 2_000.00
VENTAS = 12_000.00
