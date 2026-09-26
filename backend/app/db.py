"""Usuarios, empresas, permisos y registro de ejecuciones.

Sustituye al login decorativo del portal antiguo: dos usuarios fijos en el bundle, sin
llamada al backend, donde cualquiera entraba con tal de escribir un código de empresa.
Aquí las contraseñas se guardan con scrypt y cada usuario sólo ve las empresas que tiene
asignadas; el rol `interno` (ABGA) ve todas y accede además a los informes de uso interno.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from . import bd, cache


def _fila_a_usuario(f: Any) -> dict[str, Any]:
    return {
        "email": f["email"], "nombre": f["nombre"], "rol": f["rol"],
        "activo": bool(f["activo"]), "creado": f["creado"],
        "empresas": empresas_de(f["email"]),
    }


# ---------- usuarios ----------

def crear_usuario(email: str, nombre: str, hash_password: str, rol: str = "cliente",
                  empresas: list[str] | None = None, activo: bool | None = None) -> None:
    """Crea el usuario o lo actualiza.

    Al actualizar **conserva `activo` y `creado`**: lo que no se puede es que reejecutar el alta de
    una base, o editar a alguien desde el panel, devuelva la vida a un usuario que ABGA había
    desactivado (ni que falsee su fecha de alta). Con `empresas=None` no toca los permisos.
    """
    email = email.lower().strip()
    previo = usuario_bruto(email)
    bd.upsert(
        "usuarios",
        ("email", "nombre", "password_hash", "rol", "activo", "creado"),
        ("email",),
        (email, nombre, hash_password, rol,
         1 if activo is None and previo is None else (int(bool(activo)) if activo is not None else previo["activo"]),
         previo["creado"] if previo else cache.ahora()),
    )
    if empresas is not None:
        cache.conectar().execute("DELETE FROM permisos WHERE email=?", (email,))
        cache.conectar().commit()
        for cod in empresas:
            bd.insertar_ignorando("permisos", ("email", "cod_empresa"), (email, str(cod)))


def cambiar_password(email: str, hash_password: str) -> None:
    con = cache.conectar()
    con.execute("UPDATE usuarios SET password_hash=? WHERE email=?", (hash_password, email.lower().strip()))
    con.commit()


def actualizar_usuario(email: str, *, nombre: str | None = None, rol: str | None = None,
                       activo: bool | None = None) -> bool:
    """Cambia solo los campos que se pasan. Devuelve False si el usuario no existe."""
    email = email.lower().strip()
    if usuario_bruto(email) is None:
        return False
    campos, valores = [], []
    if nombre is not None:
        campos.append("nombre=?"); valores.append(nombre)
    if rol is not None:
        campos.append("rol=?"); valores.append(rol)
    if activo is not None:
        campos.append("activo=?"); valores.append(1 if activo else 0)
    if not campos:
        return True
    con = cache.conectar()
    con.execute(f"UPDATE usuarios SET {', '.join(campos)} WHERE email=?", (*valores, email))
    con.commit()
    return True


def usuario(email: str) -> dict[str, Any] | None:
    f = cache.conectar().execute("SELECT * FROM usuarios WHERE email=?", (email.lower().strip(),)).fetchone()
    return _fila_a_usuario(f) if f else None


def hash_de(email: str) -> str | None:
    f = cache.conectar().execute("SELECT password_hash FROM usuarios WHERE email=?",
                                 (email.lower().strip(),)).fetchone()
    return f["password_hash"] if f else None


def listar_usuarios() -> list[dict[str, Any]]:
    filas = cache.conectar().execute("SELECT * FROM usuarios ORDER BY rol, email").fetchall()
    return [_fila_a_usuario(f) for f in filas]


def activar(email: str, activo: bool = True) -> None:
    con = cache.conectar()
    con.execute("UPDATE usuarios SET activo=? WHERE email=?", (1 if activo else 0, email.lower().strip()))
    con.commit()


# ---------- empresas ----------

def crear_empresa(cod: str, nombre: str, ejercicio_inicio: int | None = None, notas: str = "") -> None:
    bd.upsert(
        "empresas",
        ("cod_empresa", "nombre", "ejercicio_inicio", "notas"),
        ("cod_empresa",),
        (str(cod), nombre, ejercicio_inicio, notas),
    )


def empresa(cod: str) -> dict[str, Any] | None:
    f = cache.conectar().execute("SELECT * FROM empresas WHERE cod_empresa=?", (str(cod),)).fetchone()
    return dict(f) if f else None


def nombre_empresa(cod: str) -> str:
    e = empresa(cod)
    return e["nombre"] if e else f"Empresa {cod}"


def listar_empresas() -> list[dict[str, Any]]:
    filas = cache.conectar().execute("SELECT * FROM empresas ORDER BY nombre").fetchall()
    return [dict(f) for f in filas]


def empresas_con_datos() -> set[str]:
    """Códigos de empresa con algún ejercicio en la caché, en una sola consulta.

    El portal lo usa para saber qué empresa abrir al entrar: preguntándolo empresa por empresa eran
    cientos de peticiones con las 391 de la asesoría, y el panel parecía colgado.
    """
    filas = cache.conectar().execute("SELECT DISTINCT empresa FROM apuntes").fetchall()
    # Por nombre de columna, no por posición: en PostgreSQL las filas llegan como diccionario y
    # `f[0]` revienta (funcionaba en SQLite y fallaba en producción).
    return {str(f["empresa"]) for f in filas}


def empresas_de(email: str) -> list[str]:
    us = usuario_bruto(email)
    if us and us["rol"] in {"interno", "admin"}:
        return [e["cod_empresa"] for e in listar_empresas()]
    filas = cache.conectar().execute("SELECT cod_empresa FROM permisos WHERE email=? ORDER BY cod_empresa",
                                     (email.lower().strip(),)).fetchall()
    return [f["cod_empresa"] for f in filas]


def usuario_bruto(email: str) -> dict[str, Any] | None:
    f = cache.conectar().execute("SELECT * FROM usuarios WHERE email=?", (email.lower().strip(),)).fetchone()
    return dict(f) if f else None


def tiene_acceso(email: str, cod_empresa: str) -> bool:
    return str(cod_empresa) in {str(c) for c in empresas_de(email)}


def asignar_empresa(email: str, cod_empresa: str) -> None:
    bd.insertar_ignorando("permisos", ("email", "cod_empresa"),
                          (email.lower().strip(), str(cod_empresa)))


def revocar_empresa(email: str, cod_empresa: str) -> None:
    con = cache.conectar()
    con.execute("DELETE FROM permisos WHERE email=? AND cod_empresa=?",
                (email.lower().strip(), str(cod_empresa)))
    con.commit()


def _permisos_brutos(email: str) -> set[str]:
    """Las filas de `permisos`, sin el atajo de los internos (que ven todas las empresas)."""
    filas = cache.conectar().execute("SELECT cod_empresa FROM permisos WHERE email=?",
                                     (email.lower().strip(),)).fetchall()
    return {str(f["cod_empresa"]) for f in filas}


def definir_empresas(email: str, codigos: list[str]) -> dict[str, list[str]]:
    """Deja al usuario **exactamente** con esas empresas: da las que faltan y quita las que sobran.

    Es lo que necesita una pantalla de permisos: marcar y desmarcar, sin tener que acordarse de
    si ya estaba puesta.
    """
    email = email.lower().strip()
    antes = _permisos_brutos(email)
    ahora = {str(c) for c in codigos if str(c).strip()}
    for cod in ahora - antes:
        asignar_empresa(email, cod)
    for cod in antes - ahora:
        revocar_empresa(email, cod)
    return {"antes": sorted(antes), "ahora": sorted(ahora),
            "añadidas": sorted(ahora - antes), "quitadas": sorted(antes - ahora)}


def eliminar_usuario(email: str) -> bool:
    """Borra el usuario y sus permisos. Devuelve False si no existía."""
    email = email.lower().strip()
    if usuario_bruto(email) is None:
        return False
    con = cache.conectar()
    con.execute("DELETE FROM permisos WHERE email=?", (email,))
    con.execute("DELETE FROM usuarios WHERE email=?", (email,))
    con.commit()
    return True


# ---------- PIN de empresa (segundo factor del alta de clientes) ----------
#
# El código de empresa solo no vale como credencial: son cuatro dígitos y son adivinables, así que
# quien probara números vería la contabilidad de otro. El PIN se guarda hasheado (nunca en claro) y
# se entrega al cliente junto con el código.

def fijar_pin(cod_empresa: str, pin_hash: str) -> None:
    con = cache.conectar()
    con.execute("UPDATE empresas SET pin_hash=? WHERE cod_empresa=?",
                (pin_hash, str(cod_empresa).strip()))
    con.commit()


def pin_guardado(cod_empresa: str) -> str | None:
    e = empresa(cod_empresa)
    return e.get("pin_hash") if e else None


def tiene_pin(cod_empresa: str) -> bool:
    return bool(pin_guardado(cod_empresa))


# ---------- registro de ejecuciones ----------

def registrar_ejecucion(*, cod_empresa: str, ejercicio: int | None, modulos: str, origen: str,
                        email: str | None, segundos: float, estado: str, desde_cache: bool,
                        detalle: str = "", importes: dict[str, Any] | None = None) -> int:
    """El log que en el sistema antiguo existía en los 7 workflows pero estaba desconectado
    y nunca escribía nada."""
    return bd.insertar_devolviendo_id(
        "ejecuciones",
        ("instante", "cod_empresa", "ejercicio", "modulos", "origen", "email",
         "segundos", "estado", "desde_cache", "detalle", "importes"),
        (cache.ahora(), str(cod_empresa), ejercicio, modulos, origen, email or "",
         round(segundos, 2), estado, 1 if desde_cache else 0, detalle[:2000],
         cache.json.dumps(importes or {}, ensure_ascii=False)),
    )


def ejecuciones(*, cod_empresa: str | None = None, limite: int = 100) -> list[dict[str, Any]]:
    sql = "SELECT * FROM ejecuciones"
    args: tuple = ()
    if cod_empresa:
        sql += " WHERE cod_empresa=?"
        args = (str(cod_empresa),)
    sql += " ORDER BY id DESC LIMIT ?"
    args = args + (int(limite),)
    filas = cache.conectar().execute(sql, args).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        try:
            d["importes"] = cache.json.loads(d.get("importes") or "{}")
        except Exception:
            d["importes"] = {}
        salida.append(d)
    return salida


def resumen_ejecuciones(dias: int = 30) -> list[dict[str, Any]]:
    """El corte se calcula en Python y se compara como texto: los instantes se guardan en ISO
    con el mismo formato, así que el orden alfabético es el cronológico. De este modo la
    consulta es idéntica en SQLite y en PostgreSQL (comparar un TEXT con un timestamptz falla
    en PostgreSQL)."""
    desde = (datetime.now(timezone.utc) - timedelta(days=int(dias))).isoformat(timespec="seconds")
    filas = cache.conectar().execute(
        "SELECT cod_empresa, modulos, estado, COUNT(*) AS n, AVG(segundos) AS media_segundos,"
        " MAX(instante) AS ultima FROM ejecuciones"
        " WHERE instante >= ? GROUP BY cod_empresa, modulos, estado"
        " ORDER BY n DESC", (desde,)).fetchall()
    return [dict(f) for f in filas]
