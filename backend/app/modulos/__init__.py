"""Registro de módulos de informe.

Contrato que cumple cada módulo (`app/modulos/<nombre>.py`):

    NOMBRE: str                     # identificador que usa el portal ("pyg", "fiscal", …)
    TITULO: str                     # título humano del informe
    INTERNO: bool                   # True = sólo panel interno de ABGA (conciliacion, duplicados)
    DESPLAZAMIENTOS: list[int]      # ejercicios que necesita, relativos al pedido: [0, -1, -2…]
    PARAMETROS: dict[str, Any]      # parámetros extra que acepta y sus valores por defecto

    def calcular(por_anio: dict[int, list[Linea]], ctx: dict) -> dict     # números
    def informe_html(datos: dict, ctx: dict) -> str                       # HTML puro
    # opcional
    def metricas_dashboard(datos: dict) -> dict

`ctx` siempre trae: empresa (nombre), cod_empresa, year, year_anterior, nombre_mes,
trimestre, email, y los PARAMETROS ya resueltos.

Los módulos no hablan con el ERP ni con la caché: reciben las líneas ya cargadas. Así el
mismo cálculo sirve para el informe, para el dashboard y para las tareas programadas.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any

# Menús del portal, en el orden acordado con ABGA (reunión del 18/09/2026).
MENUS: list[tuple[str, str]] = [
    ("panel", "Panel"),
    ("fiscal-contable", "Fiscal y contable"),
    ("impuestos", "Impuestos"),
    ("herramientas", "Herramientas"),
]

# Orden en que se muestran dentro de cada menú. `interno=True` sólo aparece para ABGA:
# duplicados NO se le enseña al cliente (le genera desconfianza), la conciliación SÍ (y puede
# comentar los movimientos pendientes).
CATALOGO: list[tuple[str, str, bool, str]] = [
    ("dashboard", "Panel de control", False, "panel"),
    ("analisis", "Análisis y alertas", False, "panel"),
    ("pyg", "Balance y cuenta de pérdidas y ganancias", False, "fiscal-contable"),
    ("sumas_saldos", "Sumas y saldos", False, "fiscal-contable"),
    ("libro_iva", "Libro de IVA", False, "fiscal-contable"),
    ("libro_retenciones", "Libro de retenciones", False, "fiscal-contable"),
    ("tesoreria", "Tesorería y cobros", False, "fiscal-contable"),
    ("conciliacion", "Conciliación de mayores", False, "fiscal-contable"),
    ("fiscal", "Modelos y alertas fiscales", False, "impuestos"),
    ("autodespro", "Informe financiero", False, "herramientas"),
    ("proyecciones", "Proyecciones financieras", False, "herramientas"),
    ("memoria", "Memoria de cuentas anuales", False, "herramientas"),
    ("duplicados", "Detección de duplicados", True, "herramientas"),
]

# Pendientes de construir (acordados con ABGA y todavía no implementados).
PENDIENTES: list[tuple[str, str, str]] = []


@dataclass
class Definicion:
    nombre: str
    titulo: str
    interno: bool
    menu: str = "herramientas"
    modulo: ModuleType | None = None
    error: str | None = None

    @property
    def disponible(self) -> bool:
        return self.modulo is not None

    @property
    def desplazamientos(self) -> list[int]:
        return list(getattr(self.modulo, "DESPLAZAMIENTOS", [0]))

    @property
    def parametros(self) -> dict[str, Any]:
        return dict(getattr(self.modulo, "PARAMETROS", {}))

    def calcular(self, por_anio: dict[int, list], ctx: dict) -> dict:
        return self.modulo.calcular(por_anio, ctx)  # type: ignore[union-attr]

    def informe_html(self, datos: dict, ctx: dict) -> str:
        return self.modulo.informe_html(datos, ctx)  # type: ignore[union-attr]

    def metricas_dashboard(self, datos: dict) -> dict:
        f = getattr(self.modulo, "metricas_dashboard", None)
        return f(datos) if f else {}


_cache: dict[str, Definicion] = {}


def obtener(nombre: str) -> Definicion:
    if nombre in _cache:
        return _cache[nombre]
    fila = next((f for f in CATALOGO if f[0] == nombre), None)
    interno = fila[2] if fila else False
    titulo = fila[1] if fila else nombre
    menu = fila[3] if fila else "herramientas"
    try:
        mod = importlib.import_module(f".{nombre}", __package__)
        definicion = Definicion(nombre=nombre, titulo=titulo, interno=interno, menu=menu, modulo=mod)
    except ModuleNotFoundError as e:
        definicion = Definicion(nombre=nombre, titulo=titulo, interno=interno, menu=menu, modulo=None,
                                error=f"módulo no implementado ({e.name})")
    except Exception as e:  # error de importación dentro del módulo
        definicion = Definicion(nombre=nombre, titulo=titulo, interno=interno, menu=menu, modulo=None,
                                error=f"error al cargar el módulo: {e}")
    _cache[nombre] = definicion
    return definicion


def listar(incluir_internos: bool = False, menu: str | None = None) -> list[Definicion]:
    nombres = [n for n, _, interno, m in CATALOGO
               if (incluir_internos or not interno) and (menu is None or m == menu)]
    return [obtener(n) for n in nombres]


def listar_todos() -> list[Definicion]:
    return [obtener(n) for n, _, _, _ in CATALOGO]


def menu_de(nombre: str) -> str:
    return next((m for n, _, _, m in CATALOGO if n == nombre), "herramientas")


def limpiar_cache() -> None:
    _cache.clear()


def anios_necesarios(nombre: str, year: int) -> list[int]:
    d = obtener(nombre)
    return sorted({year + des for des in d.desplazamientos})
