"""Prueba de que la comprobación de copias funciona: se vuelca una base y se restaura.

Se marca `lento` porque levanta un PostgreSQL de verdad (el embebido de `pgserver`), y se omite si
ese paquete no está instalado (`pgserver` es opcional: está en `requirements-dev.txt` comentado
porque sólo hace falta para esta prueba y para `verificar_bd.py`).

Lo que se defiende:

* una copia buena **se restaura** y sus datos se leen con el código de la plataforma;
* una copia truncada **no pasa** — si no, la comprobación no comprobaría nada.

La prueba no toca ninguna base de producción: el destino es siempre un PostgreSQL temporal.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

import pytest

from tests.conftest import BACKEND, RAIZ

pgserver = pytest.importorskip("pgserver", reason="pgserver no está instalado (prueba lenta)")

pytestmark = pytest.mark.lento

VERIFICADOR = BACKEND / "scripts" / "verificar_copia.py"


@pytest.fixture(scope="module")
def volcado() -> pathlib.Path:
    """Crea una base con el esquema y datos de la plataforma, y la vuelca (esto es lo que hace Coolify)."""
    datos = tempfile.mkdtemp(prefix="abga-copia-test-")
    uri = pgserver.get_server(datos).get_uri()

    import os

    os.environ["DATABASE_URL"] = uri
    from app import bd, db
    from app.config import cargar_config

    cargar_config.cache_clear()
    bd.reiniciar()
    db.crear_empresa("6091", "MB Dommo, S.L.", 2017, "")
    db.crear_empresa("1092", "ABGA Consultores, S.L.", 2010, "")
    db.crear_usuario("interno@abgaconsultores.com", "Equipo ABGA", "hash", "interno",
                     empresas=["6091", "1092"])
    db.crear_usuario("cliente@mbdommo.com", "Cliente MB", "hash", "cliente", empresas=["6091"])
    for i in range(3):
        db.registrar_ejecucion(cod_empresa="6091", ejercicio=2025, modulos="pyg", origen="portal",
                               email="cliente@mbdommo.com", segundos=float(i), estado="ok",
                               desde_cache=False, detalle=f"prueba {i}")

    pg_dump = next(p for p in pathlib.Path(pgserver.__file__).parent.rglob("pg_dump")
                   if "bin" in p.parts)
    copia = pathlib.Path(tempfile.mkdtemp(prefix="abga-copia-fichero-")) / "abga.dump"
    r = subprocess.run([str(pg_dump), "--format=custom", "--no-owner", "--dbname", uri,
                        "--file", str(copia)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]

    import shutil

    shutil.rmtree(datos, ignore_errors=True)
    os.environ.pop("DATABASE_URL", None)
    cargar_config.cache_clear()
    bd.reiniciar()
    return copia


def _verificar(copia: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(VERIFICADOR), "--copia", str(copia)],
                          capture_output=True, text=True, timeout=600, cwd=str(RAIZ))


def test_una_copia_buena_se_restaura_y_se_lee(volcado: pathlib.Path) -> None:
    r = _verificar(volcado)
    assert r.returncode == 0, r.stdout[-1500:]
    assert "Copia válida" in r.stdout
    assert "listar_empresas funciona sobre lo restaurado" in r.stdout
    assert "el usuario interno está" in r.stdout


def test_una_copia_truncada_no_pasa(volcado: pathlib.Path, tmp_path: pathlib.Path) -> None:
    rota = tmp_path / "truncada.dump"
    rota.write_bytes(volcado.read_bytes()[:400] + b"basura" * 50)
    r = _verificar(rota)
    assert r.returncode != 0, "una copia ilegible no puede dar por buena la restauración"
    assert "NO es restaurable" in r.stdout


def test_una_copia_que_no_existe_se_dice_claro(tmp_path: pathlib.Path) -> None:
    r = _verificar(tmp_path / "no-existe.dump")
    assert r.returncode == 1
    assert "no existe" in r.stdout
