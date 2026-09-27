"""Criterios de análisis por cliente: consultarlos, ajustarlos y volver al general.

Los umbrales del catálogo valen para casi toda la cartera, pero no para todos: una empresa estacional
no aguanta el mismo saldo viejo que una industrial. Aquí vive lo que ABGA puede cambiar cliente a
cliente, con la validación en un solo sitio —el rango que declara el propio módulo— para que ninguna
pantalla pueda guardar, por ejemplo, un 300% de concentración.

Sólo se guarda lo que se aparta del general. Un ajuste entra en la siguiente ejecución del informe y
queda publicado en él (`origen: empresa`) para poder discutir un rojo con el cliente.
"""

from __future__ import annotations

from typing import Any

from .. import db
from ..errores import EntradaInvalida, NoEncontrado
from ..modulos import analisis


def _empresa(cod_empresa: str) -> dict[str, Any]:
    empresa = db.empresa(cod_empresa)
    if not empresa:
        raise NoEncontrado(f"No hay ninguna empresa con el código {cod_empresa}.")
    return empresa


def estado(cod_empresa: str) -> dict[str, Any]:
    """Los criterios que se aplican a esa empresa, con su unidad, su rango y su origen."""
    empresa = _empresa(cod_empresa)
    ajustes = db.umbrales_de(cod_empresa)
    return {
        "cod_empresa": str(empresa["cod_empresa"]),
        "empresa": empresa["nombre"],
        "umbrales": analisis.umbrales(ajustes),
        "ajustados": sorted(ajustes),
        "n_ajustados": len(ajustes),
    }


def _numero_valido(clave: str, valor: Any) -> float:
    """El valor que se puede guardar para ese criterio, o un 400 diciendo por qué no."""
    esquema = analisis.ESQUEMA_UMBRALES.get(str(clave))
    if not esquema:
        raise EntradaInvalida(
            f"«{clave}» no es un criterio ajustable. Los que hay: "
            f"{', '.join(analisis.ESQUEMA_UMBRALES)}.")
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise EntradaInvalida(f"«{clave}» tiene que ser un número (llegó {valor!r}).") from None
    if not esquema["min"] <= numero <= esquema["max"]:
        raise EntradaInvalida(
            f"«{clave}» se sale del rango admitido: entre {esquema['min']} y {esquema['max']} "
            f"{esquema['unidad']}.")
    if esquema.get("entero") and numero != int(numero):
        raise EntradaInvalida(f"«{clave}» se mide en {esquema['unidad']} enteros: {numero} no vale.")
    return float(int(numero)) if esquema.get("entero") else numero


def fijar(cod_empresa: str, clave: str, valor: Any = None, actor: str = "") -> dict[str, Any]:
    """Ajusta un criterio. Con `valor` vacío lo devuelve al general. Devuelve el estado nuevo.

    Se valida antes de tocar nada: si el valor no vale, la empresa se queda como estaba.
    """
    _empresa(cod_empresa)
    if str(clave) not in analisis.ESQUEMA_UMBRALES:
        raise EntradaInvalida(
            f"«{clave}» no es un criterio ajustable. Los que hay: "
            f"{', '.join(analisis.ESQUEMA_UMBRALES)}.")
    if valor in (None, ""):
        db.quitar_umbral(cod_empresa, clave)
    else:
        db.fijar_umbral(cod_empresa, clave, _numero_valido(clave, valor), actor=actor)
    return estado(cod_empresa)


def ajustados() -> dict[str, Any]:
    """Qué clientes tienen criterios propios, con la comparación contra el general.

    Es lo que necesita el panel interno para revisar de un vistazo si un criterio se ha ido de las
    manos o si hay que replantearlo para todos (si media cartera lo tiene cambiado, el general está
    mal y lo que sobra son los ajustes).
    """
    filas = db.umbrales_ajustados()
    por_empresa: dict[str, dict[str, Any]] = {}
    for fila in filas:
        entrada = por_empresa.setdefault(str(fila["cod_empresa"]), {
            "cod_empresa": str(fila["cod_empresa"]),
            "empresa": db.nombre_empresa(fila["cod_empresa"]),
            "criterios": {},
        })
        entrada["criterios"][str(fila["clave"])] = {
            "valor": float(fila["valor"]),
            "general": analisis.UMBRALES_POR_DEFECTO.get(str(fila["clave"])),
            "unidad": analisis.ESQUEMA_UMBRALES.get(str(fila["clave"]), {}).get("unidad", ""),
            "actualizado": fila["actualizado"],
            "por": fila["actualizado_por"],
        }
    return {"clientes": sorted(por_empresa.values(), key=lambda e: e["empresa"]),
            "n_clientes": len(por_empresa), "n_criterios": len(filas),
            "criterios_disponibles": list(analisis.ESQUEMA_UMBRALES)}
