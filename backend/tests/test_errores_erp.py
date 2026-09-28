"""Lo que se ve cuando apiCON se niega a servir una empresa.

El error tiene que decir el motivo: «HTTP 400» a secas deja a ABGA creyendo que la plataforma
está rota, cuando en realidad apiCON explica en el cuerpo que a esas empresas —Contabilidad de
Estimaciones/Autónomos— no las sirve este contrato.
"""
from __future__ import annotations

import httpx

from app.apicon import _fallo_erp

MENSAJE_ESTIMACIONES = ("Está intentando utilizar un endpoint de Contabilidad de Estándar/"
                        "Sociedades para una empresa Estimaciones/Autónomos")
MENSAJE_PAGO_USO = ("Error al comprobar en pago por uso si la empresa tiene Contabilidad "
                    "Estandard/Sociedades o de Estimaciones/Autonomos")


def test_el_motivo_de_apicon_se_ve_en_el_error() -> None:
    r = httpx.Response(400, json={"Message": MENSAJE_ESTIMACIONES})
    texto = _fallo_erp(r, 2025)
    assert "HTTP 400" in texto and "2025" in texto
    assert "Estimaciones/Autónomos" in texto
    assert "Diez Software" in texto, "hay que decir de quién es el bloqueo"


def test_el_fallo_de_pago_por_uso_también_se_ve() -> None:
    r = httpx.Response(500, json={"Message": "An error has occurred.",
                                  "ExceptionMessage": MENSAJE_PAGO_USO})
    texto = _fallo_erp(r, 2022)
    assert "HTTP 500" in texto and "pago por uso" in texto


def test_sin_cuerpo_se_queda_con_el_codigo() -> None:
    r = httpx.Response(503)
    assert _fallo_erp(r, 2024) == "El ERP devolvió HTTP 503 al pedir los apuntes de 2024."


def test_el_cuerpo_se_acorta_y_no_llega_a_explotar_el_aviso() -> None:
    r = httpx.Response(400, json={"Message": "x " * 500})
    texto = _fallo_erp(r, 2025)
    assert len(texto) < 320
