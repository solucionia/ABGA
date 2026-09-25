"""Autenticación real: contraseñas con scrypt y tokens firmados (HMAC-SHA256).

Sin dependencias externas: `hashlib.scrypt` para las claves y `hmac`+`base64` para el
token de sesión, con el mismo formato `payload.firma` en base64url.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db
from .config import cargar_config

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


# ---------- contraseñas ----------

def hash_password(password: str) -> str:
    sal = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=sal, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${sal.hex()}${dk.hex()}"


def verificar_password(password: str, guardado: str | None) -> bool:
    if not guardado:
        return False
    try:
        _, n, r, p, sal_hex, dk_hex = guardado.split("$")
        dk = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(sal_hex),
                            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(dk_hex)))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def pin_generado(longitud: int = 10) -> str:
    """PIN de empresa: se lo damos al cliente junto con el código y es su segundo factor.

    Alfabeto sin caracteres que se confunden al dictarlo por teléfono (0/O, 1/I/L) y sin minúsculas:
    un PIN se lee en voz alta y se teclea en el móvil.
    """
    alfabeto = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alfabeto) for _ in range(longitud))


def password_generada(longitud: int = 14) -> str:
    alfabeto = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!#%$"
    return "".join(secrets.choice(alfabeto) for _ in range(longitud))


# ---------- token de sesión ----------

def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode().rstrip("=")


def _de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def crear_token(email: str, rol: str, empresas: list[str], *, minutos: int | None = None) -> str:
    cfg = cargar_config()
    minutos = minutos or cfg.token_ttl_min
    payload = {
        "sub": email, "rol": rol, "emp": empresas,
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=minutos)).timestamp()),
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    cuerpo = _b64(json.dumps(payload, separators=(",", ":")).encode())
    firma = hmac.new(cfg.secret_key.encode(), cuerpo.encode(), hashlib.sha256).digest()
    return f"{cuerpo}.{_b64(firma)}"


def leer_token(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    cuerpo, firma = token.split(".", 1)
    esperada = hmac.new(cargar_config().secret_key.encode(), cuerpo.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(_de_b64(firma), esperada):
            return None
        datos = json.loads(_de_b64(cuerpo))
    except Exception:
        return None
    if int(datos.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        return None
    return datos


# ---------- acceso ----------

def autenticar(email: str, password: str) -> tuple[str | None, dict[str, Any] | None, str]:
    """Devuelve (token, usuario, error). El error es el mensaje para la pantalla."""
    email = (email or "").strip().lower()
    us = db.usuario(email)
    if not us:
        return None, None, "Usuario o contraseña incorrectos."
    if not us["activo"]:
        return None, None, "Este usuario está desactivado."
    if not verificar_password(password, db.hash_de(email)):
        return None, None, "Usuario o contraseña incorrectos."
    token = crear_token(email, us["rol"], us["empresas"])
    return token, us, ""


def es_interno(us: dict[str, Any] | None) -> bool:
    return bool(us) and us.get("rol") in {"interno", "admin"}


def puede_ver_modulo(us: dict[str, Any] | None, interno: bool) -> bool:
    return es_interno(us) if interno else bool(us)
