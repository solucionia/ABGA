"""Pruebas de las migraciones versionadas: crear una base, poner al día una vieja y no perder nada.

Lo que defienden:

* una base **nueva** se construye aplicando migraciones y queda marcada en la última versión;
* una base **vieja** (sin la columna `pin_hash`, sin tabla de versiones) se pone al día **sin
  perder los datos** — es el caso de la base de producción;
* el **contrato** de `esquema.TABLAS` y lo que crean las migraciones coinciden exactamente: si
  alguien añade una tabla a mano en un sitio y no en el otro, esto se pone rojo;
* funciona en los **dos motores** (SQLite en desarrollo y pruebas, PostgreSQL en producción).
"""

from __future__ import annotations

import pathlib
import sqlite3
import subprocess
import sys
from collections.abc import Iterator

import pytest

from app import bd, esquema, migraciones
from tests.conftest import BACKEND, RAIZ

# Esquema de una base "vieja": sólo la tabla de empresas, tal y como era antes de `pin_hash`.
DDL_VIEJO = """
CREATE TABLE empresas (
    cod_empresa TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    ejercicio_inicio INTEGER,
    notas TEXT
);
"""


def _sqlite(tmp_path: pathlib.Path, nombre: str = "abga.sqlite") -> str:
    return f"sqlite:///{tmp_path / nombre}"


def _tablas(ruta: pathlib.Path) -> set[str]:
    con = sqlite3.connect(ruta)
    try:
        return {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def _columnas(ruta: pathlib.Path, tabla: str) -> set[str]:
    con = sqlite3.connect(ruta)
    try:
        return {f[1] for f in con.execute(f"PRAGMA table_info({tabla})")}
    finally:
        con.close()


@pytest.fixture
def base(entorno: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[pathlib.Path]:
    """Base migrada en un directorio temporal, aislada del entorno real."""
    destino = entorno / "abga.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{destino}")
    bd.reiniciar()
    yield destino
    bd.reiniciar()


def test_una_base_nueva_se_construye_con_las_migraciones(base: pathlib.Path) -> None:
    bd.conectar()
    tablas = _tablas(base)
    assert set(esquema.TABLAS) <= tablas
    assert migraciones.version() == migraciones.cabecera()


def test_el_contrato_de_tablas_coincide_con_lo_que_crean_las_migraciones(base: pathlib.Path) -> None:
    bd.conectar()
    creadas = _tablas(base) - {"alembic_version", "sqlite_sequence"}
    assert creadas == set(esquema.TABLAS), (
        "las migraciones y `esquema.TABLAS` se han separado: "
        f"sólo en las migraciones {sorted(creadas - set(esquema.TABLAS))}, "
        f"sólo en el contrato {sorted(set(esquema.TABLAS) - creadas)}"
    )


def test_una_base_vieja_se_pone_al_dia_sin_perder_datos(base: pathlib.Path, monkeypatch) -> None:
    # Base tal y como estaba antes de la Fase 3: sin `pin_hash` y sin tabla de versiones.
    con = sqlite3.connect(base)
    con.executescript(DDL_VIEJO)
    con.execute("INSERT INTO empresas (cod_empresa, nombre, ejercicio_inicio, notas) "
                "VALUES ('6091', 'MB Dommo, S.L.', 2017, 'dato que no se puede perder')")
    con.commit()
    con.close()
    assert "pin_hash" not in _columnas(base, "empresas")

    bd.conectar()

    assert "pin_hash" in _columnas(base, "empresas"), "la columna añadida no llegó a la base vieja"
    assert migraciones.version() == migraciones.cabecera()
    con = sqlite3.connect(base)
    try:
        fila = con.execute("SELECT nombre, notas FROM empresas WHERE cod_empresa='6091'").fetchone()
        assert fila == ("MB Dommo, S.L.", "dato que no se puede perder")
    finally:
        con.close()


def test_migrar_dos_veces_no_hace_nada_la_segunda(base: pathlib.Path) -> None:
    bd.conectar()
    primera = migraciones.version()

    bd.reiniciar()      # obliga a volver a pasar por las migraciones
    bd.conectar()
    migraciones.aplicar()

    assert migraciones.version() == primera == migraciones.cabecera()


def test_el_script_dice_la_verdad_sobre_la_base(base: pathlib.Path) -> None:
    r = subprocess.run([sys.executable, str(BACKEND / "scripts" / "migrar.py")],
                       capture_output=True, text=True, cwd=str(RAIZ),
                       env={"PATH": "/usr/bin:/bin", "DATABASE_URL": f"sqlite:///{base}",
                            "HOME": str(pathlib.Path.home())})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "la base está al día" in r.stdout
    cabecera = migraciones.cabecera()
    assert cabecera and cabecera in r.stdout


@pytest.mark.lento
def test_las_migraciones_se_aplican_a_una_copia_de_produccion(tmp_path: pathlib.Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """El camino del despliegue: poner al día una base que ya está en producción.

    Se omite si no se le pasa una copia (`COPIA_PRODUCCION=/ruta/copia.dmp`), que es lo normal: la
    copia lleva datos del cliente y no vive en el repositorio. Con ella, se restaura en un PostgreSQL
    temporal y se comprueba que migrar **no pierde ni un dato** y deja la base marcada en la última
    versión. Se hace así y no con una base de laboratorio porque lo que se prueba es que la base de
    ABGA se pueda actualizar sin sustos.
    """
    import os
    import shutil

    ruta_copia = os.environ.get("COPIA_PRODUCCION", "")
    if not ruta_copia or not pathlib.Path(ruta_copia).exists():
        pytest.skip("sin copia de producción: pasar COPIA_PRODUCCION=/ruta/copia.dmp")
    pgserver = pytest.importorskip("pgserver", reason="pgserver no está instalado")

    from app import db

    uri = pgserver.get_server(str(tmp_path / "pg")).get_uri()
    destino = bd.con_otra_base(uri, "abga_restaurada")
    pg_restore = next(p for p in pathlib.Path(pgserver.__file__).parent.rglob("pg_restore")
                      if "bin" in p.parts)
    psql = next(p for p in pathlib.Path(pgserver.__file__).parent.rglob("psql") if "bin" in p.parts)
    subprocess.run([str(psql), uri, "-c", 'CREATE DATABASE "abga_restaurada"'], check=True,
                   capture_output=True, text=True)
    r = subprocess.run([str(pg_restore), "--dbname", destino, "--no-owner", "--no-privileges",
                        str(ruta_copia)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]

    monkeypatch.setenv("DATABASE_URL", destino)
    bd.reiniciar()
    try:
        # Los recuentos de antes se hacen con SQL puro a propósito: llamar al código de la
        # aplicación migraría la base sin querer (conectar() pone al día las migraciones) y entonces
        # la prueba ya no mediría nada.
        import psycopg

        def contar(tabla: str) -> int:
            con = psycopg.connect(destino)
            try:
                with con.cursor() as cur:
                    cur.execute(f"SELECT count(*) FROM {tabla}")  # noqa: S608 (nombres fijos)
                    fila = cur.fetchone()
                    assert fila is not None
                    return int(fila[0])
            finally:
                con.close()

        tablas = ("empresas", "usuarios", "permisos", "ejecuciones")
        antes = {t: contar(t) for t in tablas}
        assert antes["empresas"] > 100, "la copia no parece la de producción"
        # La copia vale si viene de **antes** de la última migración: puede ser de antes de las
        # migraciones versionadas (`None`, el caso de una base antigua) o de una versión anterior
        # (el caso real de cada despliegue). Una copia ya al día no mediría nada, y eso se avisa en
        # vez de darla por buena. Coolify guarda copias diarias y semanales: hay donde elegir.
        version_copia = migraciones.version()
        assert version_copia != migraciones.cabecera(), (
            f"la copia ya está en la última versión ({version_copia}): no queda nada por migrar. "
            "Pásale una copia anterior a la última migración.")

        bd.conectar()   # aquí es donde se ponen al día las migraciones

        assert migraciones.version() == migraciones.cabecera()
        assert {t: contar(t) for t in tablas} == antes, "migrar cambió los datos de la copia"
        assert len(db.listar_empresas()) == antes["empresas"], "la app no ve lo mismo tras migrar"
        assert len(db.listar_usuarios()) == antes["usuarios"]
        con = bd.conectar()
        columnas = {fila["column_name"] for fila in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='empresas'").fetchall()}
        assert "pin_hash" in columnas
        # Y el contrato completo: migrar una base de producción deja todas las tablas del esquema
        # (incluida `umbrales_empresa`, de la 0003) y no sólo las que ya estaban.
        presentes = {fila["table_name"] for fila in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public'").fetchall()}
        assert set(esquema.TABLAS) <= presentes, (
            f"tras migrar faltan tablas: {sorted(set(esquema.TABLAS) - presentes)}")
    finally:
        bd.reiniciar()
        shutil.rmtree(tmp_path / "pg", ignore_errors=True)


@pytest.mark.lento
def test_las_migraciones_funcionan_en_postgres(tmp_path: pathlib.Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """El motor de producción. Se marca `lento` porque levanta un PostgreSQL de verdad."""
    pgserver = pytest.importorskip("pgserver", reason="pgserver no está instalado")
    datos = tmp_path / "pg"
    uri = pgserver.get_server(str(datos)).get_uri()
    monkeypatch.setenv("DATABASE_URL", uri)
    bd.reiniciar()
    try:
        con = bd.conectar()
        # Por nombre de columna: en PostgreSQL las filas llegan como diccionarios y en SQLite como
        # `Row`, y las dos admiten `fila["columna"]`.
        filas = con.execute("SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema='public'").fetchall()
        tablas = {fila["table_name"] for fila in filas}
        assert set(esquema.TABLAS) <= tablas
        assert migraciones.version() == migraciones.cabecera()
        columnas = {fila["column_name"] for fila in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='empresas'").fetchall()}
        assert "pin_hash" in columnas
        # El autoincremental tiene que funcionar de verdad en PostgreSQL: se inserta sin dar el id.
        con.execute("INSERT INTO ejecuciones (instante, cod_empresa, modulos, origen, estado) "
                    "VALUES (?, ?, ?, ?, ?)", ("2026-01-01T00:00:00", "6091", "pyg", "portal", "ok"))
        con.commit()
        filas = con.execute("SELECT id FROM ejecuciones").fetchall()
        assert filas and filas[0]["id"] >= 1, "la clave autoincremental no funciona en PostgreSQL"
    finally:
        bd.reiniciar()
