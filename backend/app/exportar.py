"""Exportar los informes: a Excel (CSV que Excel abre nativo) y a PDF (impresión del navegador).

Los informes son HTML con tablas y el HTML se genera aquí, así que la exportación se hace
recorriendo **las tablas del propio informe**: no hay que mantener un segundo camino de datos que
pueda desviarse del que ve el cliente. Sin dependencias externas: sólo stdlib.

- `tablas_de_html(html)` → [(titulo, cabeceras, filas)] con las tablas del informe.
- `a_csv(tablas)` → un CSV por tabla (si hay varias, en un ZIP), con cabecera y sin adornos.
- El PDF no se genera aquí: el portal lo hace con la impresión del navegador, que respeta el
  ancho de 780px y el CSS del informe (y evita meter un motor de PDF en el servidor).
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from html.parser import HTMLParser
from typing import Any

# Caracteres que Excel interpreta como inicio de fórmula y que pueden venir de un dato del ERP
_PELIGROSOS = ("=", "+", "-", "@")


class _Lector(HTMLParser):
    """Saca las tablas del informe y el título de la sección en la que están.

    Los informes no usan <h2>: los títulos de sección son un <div> con `border-left:4px solid`
    y `font-weight:bold` (ver `informes.seccion`). Se detecta ese div y se arrastra como título
    de las tablas que vienen detrás, para que el cliente abra «Balance de situación» y no «Tabla 3».
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tablas: list[tuple[str, list[list[str]]]] = []
        self._pila_tabla: list[list[list[str]]] = []
        self._fila: list[str] | None = None
        self._celda: list[str] | None = None
        self.seccion = ""
        self._capturando = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._pila_tabla.append([])
        elif tag == "tr" and self._pila_tabla:
            self._fila = []
        elif tag in ("td", "th") and self._fila is not None:
            self._celda = []
        elif tag == "div" and not self._capturando:
            estilo = dict(attrs).get("style") or ""
            if "border-left:4px solid" in estilo and "font-weight:bold" in estilo:
                self._capturando = True
                self._buf = []

    def handle_data(self, data: str) -> None:
        if self._celda is not None:
            self._celda.append(data)
        elif self._capturando:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._celda is not None and self._fila is not None:
            self._fila.append(re.sub(r"\s+", " ", "".join(self._celda)).strip())
            self._celda = None
        elif tag == "tr" and self._fila is not None and self._pila_tabla:
            if self._fila:
                self._pila_tabla[-1].append(self._fila)
            self._fila = None
        elif tag == "div" and self._capturando:
            self.seccion = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self._capturando = False
            self._buf = []
        elif tag == "table" and self._pila_tabla:
            self.tablas.append((self.seccion, self._pila_tabla.pop()))


def tablas_de_html(html: str) -> list[tuple[str, list[str], list[list[str]]]]:
    """Tablas del informe, con el título de la sección en la que están."""
    lector = _Lector()
    lector.feed(html)

    salida: list[tuple[str, list[str], list[list[str]]]] = []
    for i, (seccion, tabla) in enumerate(lector.tablas, start=1):
        if len(tabla) < 2:
            continue
        # las tablas que sólo sirven de maquetación (SVG dentro de tabla) no aportan cifras
        cuerpo = [f for f in tabla[1:] if any(c for c in f)]
        if not cuerpo:
            continue
        titulo = seccion or f"Tabla {i}"
        if sum(1 for t in salida if t[0] == titulo):
            titulo = f"{titulo} ({sum(1 for t in salida if t[0].startswith(titulo)) + 1})"
        salida.append((titulo, tabla[0], cuerpo))
    return salida


def _seguro(valor: str) -> str:
    """Neutraliza el valor para Excel/CSV: evita que un texto del ERP se ejecute como fórmula."""
    v = valor.strip()
    if v.startswith(_PELIGROSOS):
        return "'" + v
    return v


def _csv_de_tabla(titulo: str, cabeceras: list[str], filas: list[list[str]]) -> str:
    buf = io.StringIO()
    escritor = csv.writer(buf, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    escritor.writerow([_seguro(titulo)])
    escritor.writerow([_seguro(c) for c in cabeceras])
    for fila in filas:
        escritor.writerow([_seguro(str(c)) for c in fila])
    return buf.getvalue()


def _nombre_archivo(texto: str, *, maximo: int = 60) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    limpio = re.sub(r"[^A-Za-z0-9 _-]", "", sin_acentos).strip().replace(" ", "_")
    return (limpio or "tabla")[:maximo]


def a_excel(html: str, *, base: str = "informe") -> tuple[bytes, str, str]:
    """Devuelve (contenido, nombre de fichero, tipo MIME) listo para descargar.

    Un solo CSV si el informe tiene una tabla; si tiene varias, un ZIP con un CSV por tabla (así
    el cliente no pierde ninguna sección y puede abrir cada una en su hoja).
    """
    tablas = tablas_de_html(html)
    if not tablas:
        # al menos se entrega el texto del informe para no dejar al cliente sin nada
        return (html.encode("utf-8"), f"{base}.html", "text/html; charset=utf-8")

    if len(tablas) == 1:
        titulo, cabeceras, filas = tablas[0]
        texto = _csv_de_tabla(titulo, cabeceras, filas)
        # BOM para que Excel reconozca UTF-8 y los acentos salgan bien
        return ("\ufeff" + texto).encode("utf-8"), f"{base}.csv", "text/csv; charset=utf-8"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        usados: set[str] = set()
        for i, (titulo, cabeceras, filas) in enumerate(tablas, start=1):
            nombre = f"{i:02d}_{_nombre_archivo(titulo or f'tabla{i}')}.csv"
            while nombre in usados:
                nombre = f"{i:02d}_{_nombre_archivo(titulo)}_{i}.csv"
            usados.add(nombre)
            z.writestr(nombre, "\ufeff" + _csv_de_tabla(titulo, cabeceras, filas))
    return buf.getvalue(), f"{base}.zip", "application/zip"


def resumen(html: str) -> dict[str, Any]:
    """Qué se exportaría: lo usa el portal para decir cuántas tablas lleva el fichero."""
    tablas = tablas_de_html(html)
    return {"n_tablas": len(tablas), "tablas": [t[0] for t in tablas]}
