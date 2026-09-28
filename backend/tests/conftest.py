"""Base común de la suite de pruebas.

Tres reglas que no se rompen, y no son cuestión de estilo:

1. **Ninguna prueba habla con el ERP.** Sería lento (200 s por ejercicio), gastaría cuota real y
   martillearía el ERP en producción de ABGA. Los tests que necesitan datos usan `fixtures/`
   (respuestas reales ya descargadas) o los datos sintéticos de `tests/sintetico.py`.
2. **Ninguna prueba escribe en la base de datos de desarrollo.** Cada una trabaja en un
   directorio temporal propio (`CACHE_DB` apuntando a `tmp_path`).
3. **La suite no necesita secretos.** El `.env` de pruebas se fabrica con credenciales ficticias,
   así que la CI corre sin el `.env` real (que no está en git) y sin datos del cliente.

Consecuencia buscada: `pytest` pasa en cualquier máquina recién clonada, y lo que necesita los
datos reales se marca con `@pytest.mark.datos_reales` y se omite cuando no están.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[2]   # raíz del proyecto (…/abga/nuevo)
FIXTURES = RAIZ / "fixtures"
BACKEND = RAIZ / "backend"

# Credenciales de mentira: el ERP está simulado, así que no hacen falta las reales.
ENTORNO_DE_PRUEBA: dict[str, str] = {
    "APICON_BASE": "http://erp.invalido.test",
    "APICON_USERNAME": "usuario-de-pruebas",
    "APICON_PASSWORD": "contrasena-de-pruebas",
    "APICON_CLIENT_ID": "cliente-de-pruebas",
    "APICON_CLIENT_SECRET": "secreto-de-pruebas",
    "APICON_EMPRESA_DEFECTO": "6091",
    "SECRET_KEY": "clave-de-firma-solo-para-pruebas-y-bien-larga",
    "TOKEN_TTL_MIN": "60",
    # El refresco automático de la caché caducada lanza hilos que leen al ERP: fuera de las
    # pruebas (que no lo necesitan) y encendido a propósito sólo en la que lo comprueba.
    "REFRESCO_AUTOMATICO": "0",
}

EMPRESA = "6091"
EMPRESA_AJENA = "1092"
ADMIN = "interno@abgaconsultores.com"
CLIENTE = "cliente@mbdommo.com"
CLAVE_ADMIN = "clave-admin-de-pruebas"
CLAVE_CLIENTE = "clave-cliente-de-pruebas"


# ---------------------------------------------------------------- fixtures reales del ERP

def cargar_fixture(year: int) -> list[dict[str, Any]] | None:
    """Asientos del fixture real de 6091 para ese ejercicio, o None si no está."""
    ruta = FIXTURES / f"apuntes_6091_{year}.json"
    if not ruta.exists():
        return None
    return json.loads(ruta.read_text(encoding="utf-8"))["asientos"]


@pytest.fixture(scope="session")
def asientos_reales() -> dict[int, list[dict[str, Any]]]:
    """Asientos reales por ejercicio. Omite la prueba si no hay fixtures (CI sin datos)."""
    disponibles = {y: a for y in (2023, 2024, 2025) if (a := cargar_fixture(y))}
    if not disponibles:
        pytest.skip("no hay fixtures reales (fixtures/ está fuera de git)")
    return disponibles


# ---------------------------------------------------------------- entorno aislado

@pytest.fixture
def entorno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Aísla la configuración: `.env` propio (sin secretos reales) y base de datos temporal.

    `cargar_config()` resuelve el `.env` contra `config.RAIZ_PROYECTO`, así que basta con apuntar
    esa constante a un directorio temporal. El `.env` de desarrollo nunca se lee desde los tests.
    """
    from app import bd, config

    escribir_env(tmp_path, **ENTORNO_DE_PRUEBA)
    monkeypatch.setattr(config, "RAIZ_PROYECTO", tmp_path)
    config.cargar_config.cache_clear()
    bd.reiniciar()
    try:
        yield tmp_path
    finally:
        config.cargar_config.cache_clear()
        bd.reiniciar()


def escribir_env(destino: Path, **claves: str) -> Path:
    """Escribe el `.env` de pruebas en `destino` (y vacía lo que no se indique)."""
    valores = dict(claves)
    valores.setdefault("CACHE_DB", str(Path(destino) / "abga-pruebas.sqlite3"))
    valores.setdefault("DATABASE_URL", "")   # vacío = SQLite
    ruta = Path(destino) / ".env"
    ruta.write_text("\n".join(f"{k}={v}" for k, v in valores.items()) + "\n", encoding="utf-8")
    return ruta


@pytest.fixture(autouse=True)
def limpiar_estado_en_memoria() -> Iterator[None]:
    """Deja limpio el estado que las pruebas comparten a través del proceso.

    Desde la Fase 2 los intentos y los trabajos viven en la base de datos, y cada prueba usa la
    suya, así que aquí sólo queda la caché de importación de módulos (y se vacía porque una prueba
    que sustituye un módulo de informe no debe afectar a la siguiente).
    """
    from app import modulos

    modulos.limpiar_cache()
    yield


# ---------------------------------------------------------------- ERP simulado

class ErpSimulado:
    """Doble del cliente del ERP: devuelve datos sintéticos y cuenta las peticiones.

    Implementa la parte de `ClienteApicon` que usa la plataforma (`apuntes`). Guarda en la caché
    igual que el cliente real, para que el resto del sistema (cobertura, `desde_cache`,
    `/api/ejercicios`) se comporte como en producción. Si `llamadas` no sube, es que la caché hizo
    su trabajo: esa es la propiedad que comprueban varias pruebas.
    """

    def __init__(self) -> None:
        self.llamadas: list[tuple[str, int]] = []
        self.fallos: dict[tuple[str, int], Exception] = {}

    def apuntes(self, empresa: str, ejercicio: int, *, forzar: bool = False,
                ttl: int | None = None) -> dict[str, Any]:
        """Mismo contrato que el cliente real: primero la caché, y sólo si falla se «pide» al ERP."""
        from app import cache
        from tests.sintetico import anio

        if not forzar:
            guardado = cache.leer_apuntes(empresa, ejercicio, ttl)
            if guardado:
                return guardado

        self.llamadas.append((empresa, ejercicio))
        if (empresa, ejercicio) in self.fallos:
            raise self.fallos[(empresa, ejercicio)]
        asientos = anio(ejercicio)
        cache.guardar_apuntes(empresa, ejercicio, asientos,
                              resultados_totales=len(asientos),
                              cobertura=f"completa ({len(asientos)} asientos)",
                              segundos=0.01)
        return {
            "empresa": empresa, "year": ejercicio, "asientos": asientos,
            "n_asientos": len(asientos),
            "n_lineas": sum(len(a.get("Detalles") or []) for a in asientos),
            "resultados_totales": len(asientos),
            "cobertura": f"completa ({len(asientos)} asientos)",
            "segundos": 0.01, "desde_cache": False, "actualizado": cache.ahora(),
        }

    @property
    def n_llamadas(self) -> int:
        return len(self.llamadas)


@pytest.fixture
def erp_simulado(entorno: Path, monkeypatch: pytest.MonkeyPatch) -> ErpSimulado:
    """Sustituye el cliente del ERP por el doble. Sin red, determinista y rápido."""
    from app import apicon

    fake = ErpSimulado()
    monkeypatch.setattr(apicon, "_cliente", fake)
    return fake


# ---------------------------------------------------------------- portal montado

class Portal:
    """Cliente HTTP de la API con los dos usuarios del sistema ya creados."""

    def __init__(self, api: Any, erp: ErpSimulado) -> None:
        self.api = api
        self.erp = erp

    def entrar(self, email: str = CLIENTE, clave: str = CLAVE_CLIENTE,
               cod_empresa: str = EMPRESA) -> Any:
        return self.api.post("/api/login", json={"email": email, "password": clave,
                                                "cod_empresa": cod_empresa})

    def entrar_como_admin(self) -> Any:
        return self.entrar(ADMIN, CLAVE_ADMIN)

    def entrar_como_cliente(self) -> Any:
        return self.entrar(CLIENTE, CLAVE_CLIENTE)

    def informe(self, modulo: str, *, year: int = 2025, cod_empresa: str = EMPRESA,
                **extra: Any) -> Any:
        return self.api.post("/api/informe", json={"modulo": modulo, "cod_empresa": cod_empresa,
                                                   "year": year, **extra})


@pytest.fixture
def portal(erp_simulado: ErpSimulado) -> Iterator[Portal]:
    """API levantada en memoria, con dos empresas y dos usuarios (interno y cliente)."""
    from fastapi.testclient import TestClient

    from app import auth, db
    from app.main import app

    db.crear_empresa(EMPRESA, "MB Dommo, S.L.", 2017)
    db.crear_empresa(EMPRESA_AJENA, "ABGA Consultores, S.L.", 2010)
    db.crear_usuario(ADMIN, "Equipo ABGA", auth.hash_password(CLAVE_ADMIN), "interno",
                     empresas=[EMPRESA, EMPRESA_AJENA])
    db.crear_usuario(CLIENTE, "Cliente MB Dommo", auth.hash_password(CLAVE_CLIENTE), "cliente",
                     empresas=[EMPRESA])

    with TestClient(app) as cliente:
        yield Portal(cliente, erp_simulado)
