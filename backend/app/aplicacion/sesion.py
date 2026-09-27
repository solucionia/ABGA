"""Casos de uso de sesión: entrar, darse de alta como cliente y el PIN de la asesoría.

Estaban dentro del router: consultaban la base, decidían, respondían y ponían la cookie, todo
mezclado. Aquí está la decisión; la cookie la pone el router.

Reglas que **no** se pueden romper al tocar esto (vienen de defectos reales del sistema anterior):

1. La contraseña se valida **antes** que el número de empresa: así el código no sirve para sondear
   qué empresas existen sin credenciales.
2. Se distingue 400 (falta el código), 404 (esa empresa no está en la asesoría) y 403 (el usuario
   no tiene acceso a ella). Sin el código en el login, el portal abría la primera empresa con datos
   y el cliente veía otra contabilidad.
3. En el alta, el mensaje para «código inexistente» y para «PIN equivocado» es **el mismo**: a un
   desconocido no se le confirma qué códigos de empresa existen.
4. El PIN se guarda hasheado y se enseña una sola vez, al generarlo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import auth, db
from ..config import cargar_config
from ..errores import Conflicto, EntradaInvalida, LimiteAlcanzado, NoAutenticado, NoEncontrado, SinPermiso

SEGUNDOS_DE_SESION = 8 * 60 * 60        # la cookie dura la jornada laboral

INTENTOS_PIN_MAX = 8                    # fallos con el PIN de una empresa…
INTENTOS_LOGIN_MAX = 10                 # …y fallos de contraseña de un usuario…
VENTANA_INTENTOS = 900.0                # …dentro de 15 minutos
MISMO_ERROR_DE_ALTA = "Código de empresa o PIN incorrectos."

# El contador de intentos vive en la base de datos (`app/db.py`), no en memoria del proceso: antes
# era un diccionario, así que un reinicio lo borraba y con dos procesos el límite valía el doble.


@dataclass
class Sesion:
    token: str
    usuario: dict[str, Any]
    cod_empresa: str
    empresa: str


def intentos_recientes(clave: str) -> int:
    """Intentos fallidos recientes con esa clave (`pin:<empresa>` o `login:<correo>`)."""
    return db.contar_intentos(clave, VENTANA_INTENTOS)


def _anotar_intento(clave: str) -> None:
    db.registrar_intento(clave)


def _olvidar_intentos(clave: str) -> None:
    db.limpiar_intentos(clave)


# ---------------------------------------------------------------- quién es el usuario

def es_interno(us: dict[str, Any] | None) -> bool:
    """¿Es del equipo de ABGA?"""
    return auth.es_interno(us)


def usuario_de_token(token: str | None) -> dict[str, Any] | None:
    """Usuario al que pertenece ese token, si sigue activo. Los permisos se leen en cada petición,
    así que revocar el acceso tiene efecto inmediato sin esperar a que caduque la sesión."""
    datos = auth.leer_token(token)
    if not datos:
        return None
    us = db.usuario(datos["sub"])
    return us if us and us["activo"] else None


def usuario_de_demostracion() -> dict[str, Any] | None:
    """Usuario con el que se entra sin sesión cuando `DEMO_AUTO_LOGIN` está puesto.

    Ojo: con esa variable activa y un puerto abierto, cualquiera que dé con la dirección entra como
    ese usuario y ve el listado entero de empresas. Sólo se usa en previsualizaciones.
    """
    cfg = cargar_config()
    if not cfg.demo_auto_login:
        return None
    email = ("admin@abgaconsultores.com" if cfg.demo_auto_login == "interno"
             else "cliente@mbdommo.com")
    us = db.usuario(email)
    return us if us and us["activo"] else None


def tiene_acceso(email: str, cod_empresa: str) -> bool:
    return db.tiene_acceso(email, cod_empresa)


def pin_valido(cod_empresa: str, pin: str) -> bool:
    """Sin PIN puesto nunca vale: una empresa sin PIN no se puede reclamar."""
    return bool(pin) and auth.verificar_password(pin, db.pin_guardado(cod_empresa))


def _nombre_empresa(cod_empresa: str) -> str:
    return next((e["nombre"] for e in db.listar_empresas() if e["cod_empresa"] == cod_empresa), "")


def entrar(email: str, password: str, cod_empresa: str) -> Sesion:
    """Acceso al portal. El número de empresa forma parte del acceso, no es un filtro posterior."""
    email = (email or "").strip().lower()
    cod_empresa = (cod_empresa or "").strip()
    clave = f"login:{email}"

    # Límite de intentos de contraseña. Antes no había ninguno: se podía probar el diccionario
    # entero contra una cuenta sin que nada lo frenara. Se comprueba antes de autenticar, y cuenta
    # igual si el correo no existe (así no sirve para averiguar qué cuentas hay).
    if intentos_recientes(clave) >= INTENTOS_LOGIN_MAX:
        raise LimiteAlcanzado(
            "Demasiados intentos con esa cuenta. Espera unos minutos o pídenos una contraseña nueva.")

    token, us, error = auth.autenticar(email, password)
    if not token or us is None:
        _anotar_intento(clave)
        db.registrar_ejecucion(cod_empresa=cod_empresa, ejercicio=None, modulos="login",
                               origen="portal", email=email, segundos=0.0, estado="denegado",
                               desde_cache=False, detalle="contraseña incorrecta")
        raise NoAutenticado(error or "Usuario o contraseña incorrectos.")

    if not cod_empresa:
        raise EntradaInvalida("Falta el número de empresa.")
    if cod_empresa not in {e["cod_empresa"] for e in db.listar_empresas()}:
        raise NoEncontrado(f"La empresa {cod_empresa} no está en la asesoría.")
    if cod_empresa not in db.empresas_de(email):
        raise SinPermiso("Tu usuario no tiene acceso a esa empresa.")

    _olvidar_intentos(clave)
    nombre = _nombre_empresa(cod_empresa)
    db.registrar_ejecucion(cod_empresa=cod_empresa, ejercicio=None, modulos="login", origen="portal",
                           email=email, segundos=0.0, estado="ok", desde_cache=False,
                           detalle=f"rol={us['rol']} · empresa={cod_empresa}")
    return Sesion(token=token, usuario=us, cod_empresa=cod_empresa, empresa=nombre)


def alta_cliente(email: str, nombre: str, password: str, cod_empresa: str, pin: str) -> Sesion:
    """Autorregistro del cliente: crea la cuenta con su código de empresa y el PIN de la asesoría."""
    email, cod_empresa, pin = email.strip().lower(), (cod_empresa or "").strip(), (pin or "").strip()

    if db.usuario_bruto(email) is not None:
        # Una cuenta existente no se pisa nunca: si no, cualquiera reclama el correo de un cliente
        # ya dado de alta y se queda con su acceso.
        raise Conflicto("Ya existe una cuenta con ese correo. Inicia sesión, o pídenos ayuda.")
    clave_pin = f"pin:{cod_empresa}"
    if intentos_recientes(clave_pin) >= INTENTOS_PIN_MAX:
        raise LimiteAlcanzado("Demasiados intentos con ese código. Inténtalo dentro de un rato.")

    empresa = db.empresa(cod_empresa)
    if empresa is None or not pin_valido(cod_empresa, pin):
        _anotar_intento(clave_pin)
        db.registrar_ejecucion(cod_empresa=cod_empresa, ejercicio=None, modulos="alta_cliente",
                               origen="registro", email=email, segundos=0.0, estado="denegado",
                               desde_cache=False, detalle="código o PIN incorrectos")
        raise SinPermiso(MISMO_ERROR_DE_ALTA)

    db.crear_usuario(email, (nombre or "").strip() or email.split("@")[0],
                     auth.hash_password(password), "cliente", empresas=[cod_empresa])
    db.registrar_ejecucion(cod_empresa=cod_empresa, ejercicio=None, modulos="alta_cliente",
                           origen="registro", email=email, segundos=0.0, estado="ok",
                           desde_cache=False, detalle="alta por autorregistro")
    _olvidar_intentos(clave_pin)
    usuario = db.usuario(email) or {}
    return Sesion(token=auth.crear_token(email, usuario.get("rol", "cliente")), usuario=usuario,
                  cod_empresa=cod_empresa, empresa=empresa.get("nombre", ""))
