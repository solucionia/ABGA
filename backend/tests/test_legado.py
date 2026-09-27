"""Puente con los verificadores antiguos (`backend/scripts/verificar_*.py`).

Son arneses con `print` y una lista `FALLOS`: no tienen nombres de prueba, ni `-k`, ni cobertura,
y en la CI no se ejecutaban nunca. Mientras se migran a `tests/` (ya están hechos el núcleo, los
módulos y la API), esta prueba los lanza como proceso y exige que salgan en verde: así un refactor
no puede dejarlos caer sin que se note.

Los que hoy salen en rojo por **expectativas desactualizadas del propio arnés** (no por un defecto
del producto) se marcan aparte con el motivo medido. Están anotados en `ARQUITECTURA.md` como
trabajo de la Fase 1; cuando se reparen, quitar el `xfail`.

Uso:  ./.venv/bin/python -m pytest -m "datos_reales and lento"
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from tests.conftest import RAIZ

pytestmark = [pytest.mark.datos_reales, pytest.mark.lento]

SCRIPTS = RAIZ / "backend" / "scripts"

# Verificadores que necesitan sólo los fixtures (ni ERP, ni servidor, ni PostgreSQL).
EN_VERDE = [
    "verificar_nucleo.py",
    "verificar_modulos.py",
    "verificar_trio_financiero.py",
    "verificar_sumas_saldos.py",
    "verificar_libro_iva.py",
    "verificar_libro_retenciones.py",
    "verificar_fiscal.py",
    "verificar_memoria.py",
    "verificar_analisis.py",
    "verificar_conciliacion.py",
    "verificar_autodespro.py",
    "verificar_proyecciones.py",
]

# Fuera de esta lista, y por qué: necesitan ERP, servidor o PostgreSQL levantados.
#   verificar_bd.py / verificar_despliegue.py  → PostgreSQL embebido (pgserver)
#   verificar_accesos.py                       → servidor uvicorn en marcha
#   e2e_api.py / generar_mock.py               → servidor uvicorn en marcha

# Ya no queda ninguno en rojo: los tres que lo estaban (conciliación, autodespro y proyecciones)
# fallaban por expectativas caducadas del propio arnés y se repararon en la Fase 1. Se deja la lista
# —vacía— para que el mecanismo siga existiendo si vuelve a hacer falta.
PENDIENTES_DE_REPARAR: dict[str, str] = {}


def _ejecutar(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPTS / script)],
                          capture_output=True, text=True, timeout=900, cwd=str(RAIZ))


@pytest.mark.parametrize("script", EN_VERDE)
def test_el_verificador_antiguo_sigue_en_verde(script: str, asientos_reales: dict) -> None:
    r = _ejecutar(script)
    ultimas = "\n".join((r.stdout + r.stderr).strip().splitlines()[-12:])
    assert r.returncode == 0, f"{script} ha dejado de pasar:\n{ultimas}"


@pytest.mark.parametrize("script,motivo", sorted(PENDIENTES_DE_REPARAR.items()) or [
    pytest.param("", "", marks=pytest.mark.skip(reason="no hay verificadores pendientes de reparar")),
])
@pytest.mark.xfail(reason="expectativas desactualizadas del arnés (el producto no falla)", strict=False)
def test_el_verificador_desactualizado_se_ve_pero_no_bloquea(script: str, motivo: str,
                                                             asientos_reales: dict) -> None:
    r = _ejecutar(script)
    ultimas = "\n".join((r.stdout + r.stderr).strip().splitlines()[-12:])
    assert r.returncode == 0, f"{script}: {motivo}\n{ultimas}"


def test_no_se_versionan_secretos() -> None:
    """`verificar_secretos.py` cruza el `.env` con los ficheros seguidos por git.

    Con `.env` (si existe) y sin él: en la CI no hay `.env`, y el script sigue comprobando que no
    haya credenciales versionadas.
    """
    r = _ejecutar("verificar_secretos.py")
    assert r.returncode == 0, f"posible fuga de secretos:\n{r.stdout}\n{r.stderr}"
