"""Configuración del backend ABGA.

El `.env` vive en la raíz del proyecto (fuera de git) y sólo guarda secretos y
parámetros de entorno; el resto de ajustes son constantes de este módulo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]


def _leer_env(ruta: Path) -> dict[str, str]:
    datos: dict[str, str] = {}
    if not ruta.exists():
        return datos
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        datos[clave.strip()] = valor.strip()
    return datos


@dataclass(frozen=True)
class Config:
    apicon_base: str
    apicon_username: str
    apicon_password: str
    apicon_client_id: str
    apicon_client_secret: str
    apicon_empresa_defecto: str
    apicon_top: int
    cache_db: Path
    database_url: str
    ttl_apuntes: int
    secret_key: str
    token_ttl_min: int
    # "" = login obligatorio (producción). 'cliente' o 'interno' = entra solo (previsualización)
    demo_auto_login: str = ""
    # Modo solo-caché: NUNCA se llama al ERP; se sirve de la caché ignorando el TTL. Es lo que
    # debe estar puesto en una demo o una previsualización, para no tocar el ERP en producción.
    solo_cache: bool = False
    # Caché caducada: se sirve la que hay y el ejercicio se refresca detrás, en segundo plano,
    # en vez de dejar la petición esperando al ERP (una lectura son cientos de consultas y tarda
    # minutos). `0` desactiva el refresco automático (la petición sigue sirviendo lo caducado).
    refresco_automatico: bool = True
    firma: str = "ABGA Consultores · farias@abgaconsultores.com · 913 788 740"
    # Ritmo hacia el ERP: el endpoint responde 429 si se le machaca.
    pausa_entre_peticiones: float = 1.5
    reintentos_429: int = 4
    espera_429_base: float = 8.0
    timeout_erp: float = 180.0
    ejercicios_disponibles: tuple[int, ...] = field(
        default_factory=lambda: tuple(range(2022, 2027))
    )


def origenes_cors() -> tuple[str, ...]:
    """Orígenes permitidos por CORS, de `CORS_ORIGENES` (lista separada por comas).

    **Vacío es lo correcto y es el defecto**: el panel se sirve desde el mismo origen que la API
    (`frontend/` lo monta esta misma aplicación), así que no hace falta CORS y abrirlo con
    credenciales sólo amplía la superficie. Sólo se rellena si algún día el frontal vive en otro
    dominio. No se admiten comodines: `*` con `allow_credentials` hace que el navegador acepte
    cualquier origen.
    """
    env = _leer_env(RAIZ_PROYECTO / ".env")
    for clave, valor in os.environ.items():
        if clave == "CORS_ORIGENES":
            env[clave] = valor
    crudo = (env.get("CORS_ORIGENES") or "").strip()
    if not crudo or crudo == "*":
        return ()
    return tuple(o.strip() for o in crudo.split(",") if o.strip())


LARGO_MINIMO_SECRET_KEY = 32


@lru_cache(maxsize=1)
def cargar_config(ruta_env: Path | None = None) -> Config:
    ruta = ruta_env or (RAIZ_PROYECTO / ".env")
    env = _leer_env(ruta)
    for clave, valor in os.environ.items():
        if clave.startswith("APICON_") or clave in {"SECRET_KEY", "CACHE_DB", "DATABASE_URL"}:
            env.setdefault(clave, valor)

    faltan = [
        c for c in ("APICON_USERNAME", "APICON_PASSWORD", "APICON_CLIENT_ID", "APICON_CLIENT_SECRET")
        if not env.get(c)
    ]
    if faltan:
        raise RuntimeError(f"Faltan credenciales en {ruta}: {', '.join(faltan)}")

    # La `SECRET_KEY` firma las cookies de sesión: si falta o es corta, se puede falsificar una
    # sesión. Antes tenía un valor por defecto («cambiar-esta-clave»), así que un despliegue mal
    # configurado arrancaba igual y con una clave que cualquiera puede leer en el repositorio.
    secret_key = (env.get("SECRET_KEY") or "").strip()
    if len(secret_key) < LARGO_MINIMO_SECRET_KEY:
        raise RuntimeError(
            f"SECRET_KEY falta o es demasiado corta en {ruta} ({len(secret_key)} caracteres, "
            f"mínimo {LARGO_MINIMO_SECRET_KEY}): con ella se firman las sesiones. Genera una con "
            f"«python3 -c \\\"import secrets; print(secrets.token_urlsafe(48))\\\"».")

    cache_db = Path(env.get("CACHE_DB", "./data/abga.sqlite3"))
    if not cache_db.is_absolute():
        cache_db = RAIZ_PROYECTO / cache_db
    cache_db.parent.mkdir(parents=True, exist_ok=True)

    # Refresco de la caché caducada (ver `Config.refresco_automatico`): por defecto sí, y se
    # apaga con REFRESCO_AUTOMATICO=0 en entornos donde no quieran leerse el ERP.
    apagado = {"0", "false", "no", "off"}
    refresco = env.get("REFRESCO_AUTOMATICO", "1").strip().lower() not in apagado

    return Config(
        apicon_base=env.get("APICON_BASE", "http://apicon.diezsoftware.com"),
        apicon_username=env["APICON_USERNAME"],
        apicon_password=env["APICON_PASSWORD"],
        apicon_client_id=env["APICON_CLIENT_ID"],
        apicon_client_secret=env["APICON_CLIENT_SECRET"],
        apicon_empresa_defecto=env.get("APICON_EMPRESA_DEFECTO", "6091"),
        apicon_top=int(env.get("APICON_TOP", "200")),
        cache_db=cache_db,
        database_url=env.get("DATABASE_URL", "").strip(),
        ttl_apuntes=int(env.get("CACHE_TTL_APUNTES", "43200")),
        secret_key=secret_key,
        token_ttl_min=int(env.get("TOKEN_TTL_MIN", "480")),
        demo_auto_login=env.get("DEMO_AUTO_LOGIN", "").strip().lower(),
        solo_cache=env.get("APICON_SOLO_CACHE", "").strip().lower() in {"1", "true", "si", "sí", "yes"},
        refresco_automatico=refresco,
    )
