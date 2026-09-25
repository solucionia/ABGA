"""Carga el listado de clientes de ABGA (Excel) en la tabla `empresas`.

El Excel lo manda Iván y trae: Código, NIF, Nombre, Fecha Alta, Laboral, Contabilidad
(General / Módulos / Directa), Obligaciones y Facturación. Se lee sin dependencias externas
(el .xlsx es un zip con XML).

    ./.venv/bin/python backend/scripts/importar_empresas.py "/ruta/Listado clientes.xlsx"

Es idempotente: vuelve a cargar sin duplicar. No toca el ERP ni la caché de apuntes.
"""
from __future__ import annotations

import datetime
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import db  # noqa: E402

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _texto(hoja: ET.Element, c: ET.Element, sst: list[str]) -> str:
    tipo = c.get("t")
    if tipo == "inlineStr":
        return "".join(t.text or "" for t in c.iter(f"{NS}t")).strip()
    v = c.find(f"{NS}v")
    if v is None or v.text is None:
        return ""
    if tipo == "s":
        i = int(v.text)
        return sst[i].strip() if 0 <= i < len(sst) else ""
    return v.text.strip()


def _anio_de_fecha(valor: str) -> int | None:
    """Año de alta a partir de lo que trae la celda.

    OJO: en este Excel la fecha viene como **número de serie de Excel** (43047 = 2017-11-07), no
    como texto. Tomar los cuatro primeros dígitos de 43047 da 4304, que no es un año: el año de
    alta quedaba mal en las 391 empresas.
    """
    v = (valor or "").strip()
    if not v:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", v):          # ya viene en ISO
        return int(v[:4])
    numero = v.replace(",", ".")
    if re.match(r"^\d+(\.\d+)?$", numero):           # serie de Excel
        serial = float(numero)
        if serial > 1000:                            # descarta años sueltos escritos como número
            base = datetime.date(1899, 12, 30)       # origen de fechas de Excel
            return (base + datetime.timedelta(days=serial)).year
        if 1900 <= serial <= 2100:
            return int(serial)
    m = re.search(r"(19|20)\d{2}", v)
    return int(m.group(0)) if m else None


def leer(ruta: Path) -> list[dict[str, str]]:
    z = zipfile.ZipFile(ruta)
    sst: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{NS}si"):
            sst.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    hoja = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))

    filas: list[dict[str, str]] = []
    cabeceras: list[str] = []
    for fila in hoja.iter(f"{NS}row"):
        celdas = {}
        for c in fila.findall(f"{NS}c"):
            letra = re.match(r"([A-Z]+)", c.get("r", "") or "")
            if letra:
                celdas[letra.group(1)] = _texto(hoja, c, sst)
        valores = [celdas.get(l, "") for l in ("A", "B", "C", "D", "E", "F", "G", "H")]
        if not any(valores):
            continue
        if valores[0] == "Código":
            cabeceras = valores
            continue
        if not valores[0].isdigit() or len(valores[0]) < 3:
            continue  # títulos, filas de adorno o códigos basura
        filas.append(dict(zip(cabeceras or
                              ["Código", "NIF", "Nombre", "Fecha Alta", "Laboral", "Contabilidad",
                               "Obligaciones", "Facturación"], valores)))
    return filas


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("uso: importar_empresas.py <Listado clientes.xlsx>")
    ruta = Path(sys.argv[1])
    filas = leer(ruta)
    print(f"filas leídas: {len(filas)}")

    nuevas = actualizadas = 0
    for f in filas:
        cod = f["Código"].strip()
        nombre = (f.get("Nombre") or "").strip() or f"Empresa {cod}"
        alta = _anio_de_fecha(f.get("Fecha Alta") or "")
        notas = " · ".join(x for x in (
            f"NIF {f.get('NIF','').strip()}" if f.get("NIF") else "",
            f"contabilidad {f.get('Contabilidad','').strip()}" if f.get("Contabilidad") else "",
            "laboral" if (f.get("Laboral") or "").strip() == "*" else "",
            "obligaciones" if (f.get("Obligaciones") or "").strip() == "*" else "",
            f"facturación {f.get('Facturación','').strip()}" if f.get("Facturación") else "",
        ) if x)
        existia = db.empresa(cod) is not None
        db.crear_empresa(cod, nombre, alta, notas)
        if existia:
            actualizadas += 1
        else:
            nuevas += 1

    print(f"empresas nuevas: {nuevas}  ·  actualizadas: {actualizadas}")
    total = db.listar_empresas()
    print(f"empresas en la plataforma: {len(total)}")

    # la empresa que Iván marcó en azul (verificado en el Excel: relleno FF00B0F0)
    marcada = [e for e in total if e["cod_empresa"] == "6221"]
    for e in marcada:
        print(f"\nmarcada en azul por Iván -> {e['cod_empresa']} {e['nombre']}  ({e['notas']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
