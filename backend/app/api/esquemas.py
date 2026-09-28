"""Contratos de entrada y salida de la API.

Hasta la Fase 1 cada endpoint recibía `payload: dict = Body(...)`: la API no tenía contrato (el
OpenAPI sólo declaraba `ValidationError`), un año no numérico reventaba con 500 y las respuestas no
estaban descritas. Estos modelos son ese contrato, y son la única fuente de verdad: los tests
comprueban que el OpenAPI los publica.

Criterio al decidir qué se valida aquí y qué se valida en el caso de uso:

* **Formato y tipo** → aquí (Pydantic, responde **422** con el detalle). Un año que no es un número,
  un correo sin arroba o una lista de empresas que no es lista son errores de forma.
* **Presencia de un identificador de negocio** → en el caso de uso, que responde **400/404/403**.
  El número de empresa ausente, desconocido o sin permiso ya tenía esos códigos acordados con el
  portal y documentados; cambiarlos ahora rompería la pantalla sin ganar nada.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Rol = Literal["cliente", "interno", "admin"]


class _Peticion(BaseModel):
    """Base de las peticiones: sin campos de más (un campo mal escrito es un error, no un silencio)."""

    model_config = {"extra": "forbid"}


def _limpio(v: Any) -> Any:
    return v.strip() if isinstance(v, str) else v


# ---------------------------------------------------------------- sesión

class PeticionLogin(_Peticion):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    # Presencia comprobada en el caso de uso (400): es un identificador de negocio, no un formato.
    cod_empresa: str = Field(default="", max_length=20)

    _normalizar = field_validator("email", "password", "cod_empresa")(_limpio)


class PeticionRegistro(_Peticion):
    """Alta del cliente: crea sus credenciales y entra directo, con el PIN que da la asesoría."""

    email: str = Field(min_length=6, max_length=200)
    nombre: str = Field(default="", max_length=200)
    password: str = Field(min_length=10, max_length=200)
    cod_empresa: str = Field(default="", max_length=20)
    pin: str = Field(default="", max_length=40)

    _normalizar = field_validator("email", "nombre", "cod_empresa", "pin")(_limpio)


# ---------------------------------------------------------------- informes

class PeticionInforme(_Peticion):
    modulo: str = Field(min_length=1, max_length=60)
    cod_empresa: str = Field(default="", max_length=20)
    year: int = Field(ge=2000, le=2100)
    params: dict[str, Any] = Field(default_factory=dict)
    forzar: bool = False
    # Parámetros que el portal manda sueltos, en la raíz; se pliegan en `params` (compatibilidad).
    trimestre: int | None = Field(default=None, ge=1, le=4)
    umbral: int | None = None
    max_filas: int | None = Field(default=None, ge=1)

    _normalizar = field_validator("modulo", "cod_empresa")(_limpio)

    def parametros(self) -> dict[str, Any]:
        """`params` con los parámetros sueltos ya dentro (los sueltos ganan, como antes)."""
        combinados = dict(self.params)
        for clave in ("trimestre", "umbral", "max_filas"):
            valor = getattr(self, clave)
            if valor is not None:
                combinados[clave] = valor
        return combinados


class PeticionRefrescar(_Peticion):
    cod_empresa: str = Field(default="", max_length=20)
    year: int = Field(ge=2000, le=2100)
    modulos: list[str] | None = None
    forzar: bool = True

    _normalizar = field_validator("cod_empresa")(_limpio)


# ---------------------------------------------------------------- panel interno

class PeticionPin(_Peticion):
    cod_empresa: str = Field(min_length=1, max_length=20)

    _normalizar = field_validator("cod_empresa")(_limpio)


class PeticionUsuario(_Peticion):
    """Crea o edita un usuario. Sin contraseña, se genera y se enseña una sola vez."""

    email: str = Field(min_length=3, max_length=200)
    nombre: str = Field(default="", max_length=200)
    rol: Rol = "cliente"
    activo: bool | None = None
    password: str = Field(default="", max_length=200)
    empresas: list[str] | None = None

    _normalizar = field_validator("email", "nombre")(_limpio)

    @field_validator("empresas")
    @classmethod
    def _empresas_limpias(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else [str(c).strip() for c in v if str(c).strip()]


class PeticionEmpresasDeUsuario(_Peticion):
    email: str = Field(min_length=3, max_length=200)
    empresas: list[str] = Field(default_factory=list)

    _normalizar = field_validator("email")(_limpio)


class PeticionEliminarUsuario(_Peticion):
    email: str = Field(min_length=3, max_length=200)

    _normalizar = field_validator("email")(_limpio)


class PeticionEmpresa(_Peticion):
    cod_empresa: str = Field(min_length=1, max_length=20)
    nombre: str = Field(min_length=1, max_length=200)
    ejercicio_inicio: int | None = Field(default=None, ge=1900, le=2100)
    notas: str = ""

    _normalizar = field_validator("cod_empresa", "nombre")(_limpio)


class PeticionCache(_Peticion):
    cod_empresa: str = Field(min_length=1, max_length=20)
    year: int | None = Field(default=None, ge=2000, le=2100)

    _normalizar = field_validator("cod_empresa")(_limpio)


# ---------------------------------------------------------------- respuestas

class RespuestaOk(BaseModel):
    status: str = "ok"


class RespuestaError(BaseModel):
    """Formato único de error. El portal lee `error`; `codigo` es para la persona que depura."""

    status: str = "error"
    error: str
    codigo: str = "error"


class DetalleValidacion(BaseModel):
    campo: str
    mensaje: str


class RespuestaValidacion(RespuestaError):
    codigo: str = "entrada_invalida"
    detalle: list[DetalleValidacion] = Field(default_factory=list)


class RespuestaLogin(RespuestaOk):
    token: str
    usuario: dict[str, Any]
    cod_empresa: str
    empresa: str


class RespuestaYo(RespuestaOk):
    usuario: dict[str, Any]
    interno: bool


class RespuestaEmpresas(RespuestaOk):
    empresas: list[dict[str, Any]]


class RespuestaEmpresasBuscadas(RespuestaOk):
    total: int
    empresas: list[dict[str, Any]]


class RespuestaEliminado(RespuestaOk):
    eliminado: str


class RespuestaModulos(RespuestaOk):
    modulos: list[dict[str, Any]]
    ocultos: list[str] = Field(default_factory=list)
    menus: list[dict[str, Any]]
    pendientes: list[dict[str, Any]]
    ejercicios: list[int]


class RespuestaInforme(RespuestaOk):
    html: str | None = None
    data: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    avisos: list[str] | None = None


class RespuestaDashboard(RespuestaOk):
    data: dict[str, Any]
    meta: dict[str, Any]
    avisos: list[str] = Field(default_factory=list)


class RespuestaAnalisis(RespuestaOk):
    """El semáforo de «Análisis y alertas» en JSON: `data.hallazgos` trae las comprobaciones y
    `data.seleccion` las que pasan el filtro pedido."""

    data: dict[str, Any]
    meta: dict[str, Any]
    avisos: list[str] = Field(default_factory=list)


class RespuestaCartera(RespuestaOk):
    """Cartera de análisis del panel interno de ABGA (sólo caché, nunca el ERP)."""

    year: int
    filas: list[dict[str, Any]]
    fallos: list[dict[str, Any]]
    totales: dict[str, Any]
    desde: int
    limite: int
    segundos: float
    avisos: list[str] = Field(default_factory=list)


class PeticionUmbral(BaseModel):
    """Ajuste de un criterio de análisis para un cliente (`valor` vacío = volver al general)."""

    cod_empresa: str = Field(..., description="Empresa a la que se aplica el criterio")
    clave: str = Field(..., description="Criterio; la lista sale en GET /api/interno/umbrales")
    valor: float | None = Field(None, description="Valor nuevo; vacío para dejarlo en el general")


class RespuestaUmbrales(RespuestaOk):
    """Los criterios que se aplican a un cliente, con su unidad, su rango y su origen."""

    cod_empresa: str
    empresa: str
    umbrales: dict[str, Any]
    ajustados: list[str]
    n_ajustados: int


class RespuestaUmbralesAjustados(RespuestaOk):
    """Qué clientes tienen criterios propios (sólo los ajustes, para el panel interno)."""

    clientes: list[dict[str, Any]]
    n_clientes: int
    n_criterios: int
    criterios_disponibles: list[str]


class RespuestaTrabajo(RespuestaOk):
    trabajo: dict[str, Any]


class RespuestaUsuarios(RespuestaOk):
    usuarios: list[dict[str, Any]]


class RespuestaEjercicios(RespuestaOk):
    empresa: str
    cod_empresa: str
    ejercicios: list[dict[str, Any]]


class RespuestaCache(RespuestaOk):
    cache: list[dict[str, Any]]


class RespuestaSalud(RespuestaOk):
    version: str
    erp: str
    cache: dict[str, Any]
    proceso: dict[str, Any]
    modulos: list[dict[str, Any]]
    ejercicios: list[int]
    # Avisos sin atender (Fase 4): es lo que permite que una monitorización avise de que hay informes
    # saliendo incompletos o fallando. Va con valor por defecto para no romper a quien ya lo leía.
    avisos: dict[str, Any] = Field(default_factory=dict)


class RespuestaTrabajos(RespuestaOk):
    trabajos: list[dict[str, Any]]


class RespuestaResumenInterno(RespuestaOk):
    """El panel de ABGA: uso, caché, trabajos en curso y accesos."""

    ejecuciones: list[dict[str, Any]]
    por_estado: list[dict[str, Any]]
    cache: list[dict[str, Any]]
    trabajos: list[dict[str, Any]]
    empresas: list[dict[str, Any]]
    usuarios: list[dict[str, Any]]
    modulos: list[dict[str, Any]]


class RespuestaUsuario(RespuestaOk):
    """Alta o edición de un usuario.

    `email` y `rol` van en la raíz porque el panel los pinta tal cual: la versión que estaba viva
    devolvía sólo `usuario` y la pantalla mostraba «Usuario undefined creado (undefined)».
    """

    usuario: dict[str, Any]
    email: str
    rol: str
    password: str | None = None
    aviso: str | None = None
    cambio: dict[str, list[str]] | None = None


class RespuestaPin(RespuestaOk):
    cod_empresa: str
    nombre: str
    pin: str
    aviso: str


class RespuestaEmpresaCreada(RespuestaOk):
    empresa: dict[str, Any]


class RespuestaCacheBorrada(RespuestaOk):
    borrados: int
    cache: list[dict[str, Any]]


# ---------------------------------------------------------------- observabilidad (Fase 4)

class PeticionAviso(_Peticion):
    """Atender un aviso: sólo hace falta cuál."""

    id: int = Field(ge=1)


class RespuestaMetricas(RespuestaOk):
    """Uso y salud de la plataforma, desde la tabla `ejecuciones` que ya se escribía."""

    dias: int
    desde: str
    total: int
    por_estado: dict[str, int]
    errores: int
    informes_parciales: int
    desde_cache: dict[str, Any]
    segundos: dict[str, Any]
    por_modulo: list[dict[str, Any]]
    por_empresa: list[dict[str, Any]]
    avisos_pendientes: int
    avisos: list[dict[str, Any]]


class RespuestaAvisos(RespuestaOk):
    avisos: list[dict[str, Any]]


class RespuestaAvisoAtendido(RespuestaOk):
    id: int
    atendido_por: str
