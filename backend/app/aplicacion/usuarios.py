"""Casos de uso de la administración de accesos: usuarios, permisos por empresa y PIN.

Reciben datos normales (cadenas, booleanos, listas), no modelos HTTP: la capa de aplicación no
depende de la de transporte. El router traduce el esquema Pydantic a estos argumentos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import auth, db
from ..errores import Conflicto, EntradaInvalida, NoEncontrado
from .sesion import pin_valido  # noqa: F401  (reexportado: lo usan los tests y el panel)

LARGO_MINIMO_PASSWORD = 10
ROLES_VALIDOS = ("cliente", "interno", "admin")


@dataclass
class ResultadoUsuario:
    """Lo que se enseña tras crear o editar un usuario.

    `email` y `rol` van en la raíz porque el panel los pinta directamente (`banner-usuario`): la
    versión que estaba viva devolvía sólo `usuario`, así que la pantalla mostraba «Usuario
    undefined creado (undefined)».
    """

    usuario: dict[str, Any]
    password: str = ""
    aviso: str = ""
    cambio: dict[str, list[str]] = field(default_factory=dict)


def listar() -> list[dict[str, Any]]:
    return db.listar_usuarios()


def guardar(*, email: str, nombre: str = "", rol: str = "cliente", activo: bool | None = None,
            password: str = "", empresas: list[str] | None = None,
            actor: str) -> ResultadoUsuario:
    """Crea o edita un usuario. Sin contraseña, se genera y se enseña una sola vez."""
    email = email.strip().lower()
    if "@" not in email:
        raise EntradaInvalida("Falta un correo válido.")
    if rol not in ROLES_VALIDOS:
        raise EntradaInvalida(f"Rol no válido: {', '.join(ROLES_VALIDOS)}.")
    if password and len(password) < LARGO_MINIMO_PASSWORD:
        raise EntradaInvalida(f"La contraseña debe tener al menos {LARGO_MINIMO_PASSWORD} caracteres.")

    previo = db.usuario_bruto(email)
    nombre = (nombre or "").strip() or (previo["nombre"] if previo else email)
    generada = ""
    if not password and previo is None:
        generada = auth.password_generada()
        password = generada

    # Permisos: el código de empresa se comprueba aquí, no en el login. Un código inventado deja una
    # cuenta que no puede entrar en ninguna parte, y una cuenta de cliente sin empresa no sirve para
    # nada (el acceso exige el número). Al EDITAR, lo que se pasa se AÑADE: quitar es cosa de
    # `asignar_empresas`, que es la llamada explícita de la pantalla de permisos.
    codigos: list[str] | None = None
    if empresas is not None:
        codigos = [str(c).strip() for c in empresas if str(c).strip()]
    if previo is None and rol == "cliente" and not codigos:
        raise EntradaInvalida("Una cuenta de cliente necesita al menos un número de empresa: "
                              "sin él no puede entrar.")
    if codigos:
        conocidas = {str(e["cod_empresa"]) for e in db.listar_empresas()}
        desconocidos = [c for c in codigos if c not in conocidas]
        if desconocidos:
            raise EntradaInvalida("No está en la asesoría el código de empresa: "
                                  + ", ".join(desconocidos) + ".")
    if codigos is not None and previo is not None:
        codigos = sorted({*db.permisos_de(email), *codigos})

    if previo is None:
        db.crear_usuario(email, nombre, auth.hash_password(password), rol, empresas=codigos)
    else:
        db.actualizar_usuario(email, nombre=nombre, rol=rol, activo=activo)
        if password:
            db.cambiar_password(email, auth.hash_password(password))

    # Los permisos se escriben ANTES de mirar el usuario: si no, la respuesta devuelve los de
    # antes y el panel enseña una lista de empresas que no es la que acaba de guardar.
    cambio: dict[str, list[str]] = {}
    if empresas is not None:
        cambio = db.definir_empresas(email, codigos or [])

    resultado = ResultadoUsuario(
        usuario=db.usuario(email) or {},
        password=generada,
        cambio=cambio,
        aviso="Contraseña generada; no se vuelve a mostrar. Dale las credenciales al cliente."
              if generada else "",
    )

    db.registrar_ejecucion(cod_empresa="", ejercicio=None, modulos="alta_cliente", origen="interno",
                           email=actor, segundos=0.0, estado="ok", desde_cache=False,
                           detalle=f"{'alta' if previo is None else 'edición'} de {email} rol={rol}")
    return resultado


def asignar_empresas(*, email: str, empresas: list[str], actor: str) -> ResultadoUsuario:
    """Deja al usuario exactamente con esas empresas (marcar y desmarcar)."""
    email = email.strip().lower()
    if db.usuario_bruto(email) is None:
        raise NoEncontrado("No existe ese usuario.")
    cambio = db.definir_empresas(email, [str(c) for c in empresas])
    db.registrar_ejecucion(cod_empresa="", ejercicio=None, modulos="permisos", origen="interno",
                           email=actor, segundos=0.0, estado="ok", desde_cache=False,
                           detalle=f"{email}: +{len(cambio['añadidas'])} -{len(cambio['quitadas'])}")
    return ResultadoUsuario(usuario=db.usuario(email) or {}, cambio=cambio)


def eliminar(*, email: str, actor: str) -> None:
    email = email.strip().lower()
    if email == actor:
        raise EntradaInvalida("No puedes eliminar tu propio usuario.")
    if not db.eliminar_usuario(email):
        raise NoEncontrado("No existe ese usuario.")
    db.registrar_ejecucion(cod_empresa="", ejercicio=None, modulos="baja_usuario", origen="interno",
                           email=actor, segundos=0.0, estado="ok", desde_cache=False,
                           detalle=f"usuario eliminado: {email}")


def generar_pin(cod_empresa: str, actor: str) -> dict[str, Any]:
    """Genera o regenera el PIN de una empresa. Sólo se enseña una vez: no se guarda en claro."""
    cod = (cod_empresa or "").strip()
    empresa = db.empresa(cod)
    if empresa is None:
        raise NoEncontrado("No existe esa empresa.")
    pin = auth.pin_generado()
    db.fijar_pin(cod, auth.hash_password(pin))
    db.registrar_ejecucion(cod_empresa=cod, ejercicio=None, modulos="pin_empresa", origen="interno",
                           email=actor, segundos=0.0, estado="ok", desde_cache=False,
                           detalle="PIN generado")
    return {"cod_empresa": cod, "nombre": empresa["nombre"], "pin": pin,
            "aviso": "Este PIN no se vuelve a mostrar: cópialo y dáselo al cliente junto con el código."}


def crear_empresa(*, cod_empresa: str, nombre: str, ejercicio_inicio: int | None = None,
                  notas: str = "", actor: str) -> dict[str, Any]:
    cod = (cod_empresa or "").strip()
    if db.empresa(cod) is not None:
        raise Conflicto(f"La empresa {cod} ya existe en la asesoría.")
    db.crear_empresa(cod, nombre.strip(), ejercicio_inicio, notas or "")
    db.registrar_ejecucion(cod_empresa=cod, ejercicio=None, modulos="alta_empresa", origen="interno",
                           email=actor, segundos=0.0, estado="ok", desde_cache=False,
                           detalle=f"empresa creada: {nombre}")
    return db.empresa(cod) or {}
