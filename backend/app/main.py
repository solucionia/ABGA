"""API de la plataforma ABGA.

Sustituye a la función serverless `/api/webhook` del portal antiguo, que sólo reenviaba
`{modulo, cod_empresa, year}` a n8n. Aquí hay autenticación real, permisos por empresa,
datos agregados para los dashboards (en vez de 5.000 apuntes por respuesta), caché
consultable y registro de ejecuciones.

Arranque en desarrollo:
    ./.venv/bin/python -m uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from fastapi import Body, Cookie, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import apicon, auth, cache, db, exportar, modulos, servicio, trabajos
from .config import RAIZ_PROYECTO, cargar_config
from .ledger import fmt, fmt_pct

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("abga.api")

FRONTEND = RAIZ_PROYECTO / "frontend"

app = FastAPI(title="ABGA · plataforma de informes", version="1.0.0",
              description="Informes financieros y dashboards sobre el ERP apiCON de ABGA Consultores.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ---------- sesión ----------

def _token_de(request: Request, sesion: str | None = Cookie(default=None)) -> str | None:
    cabecera = request.headers.get("authorization") or ""
    if cabecera.lower().startswith("bearer "):
        return cabecera[7:].strip()
    return sesion


def _demo_usuario() -> dict[str, Any] | None:
    """Usuario con el que se entra automáticamente cuando DEMO_AUTO_LOGIN está activo."""
    cfg = cargar_config()
    if not cfg.demo_auto_login:
        return None
    email = ("admin@abgaconsultores.com" if cfg.demo_auto_login == "interno"
             else "cliente@mbdommo.com")
    us = db.usuario(email)
    return us if us and us["activo"] else None


def usuario_actual(request: Request, sesion: str | None = Cookie(default=None)) -> dict[str, Any]:
    datos = auth.leer_token(_token_de(request, sesion))
    if datos:
        us = db.usuario(datos["sub"])
        if us and us["activo"]:
            return us
    # modo demo (previsualización): sin sesión se entra con el usuario de demostración
    demo = _demo_usuario()
    if demo:
        return demo
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión no válida o caducada.")


def usuario_interno(us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    if not auth.es_interno(us):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Esta sección es de uso interno de ABGA.")
    return us


def _empresa_permitida(us: dict[str, Any], cod_empresa: str) -> str:
    cod = str(cod_empresa or "").strip()
    if not cod:
        raise HTTPException(status_code=400, detail="Falta el código de empresa.")
    if not db.tiene_acceso(us["email"], cod):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Tu usuario no tiene acceso a la empresa {cod}.")
    return cod


# ---------- sesión (endpoints) ----------

@app.post("/api/login")
def login(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Acceso al portal.

    El **número de empresa** forma parte del acceso, no es un filtro posterior: el cliente entra con
    su código y se abre directamente su panel. Se comprueba contra lo que ese usuario puede ver, de
    modo que un código no sirve para mirar los datos de otra empresa.
    """
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    cod_empresa = str(payload.get("cod_empresa") or "").strip()
    token, us, error = auth.autenticar(email, password)
    if not token:
        return JSONResponse({"status": "error", "error": error}, status_code=401)

    if not cod_empresa:
        return JSONResponse({"status": "error", "error": "Falta el número de empresa."}, status_code=400)

    todas = db.listar_empresas()
    if cod_empresa not in {e["cod_empresa"] for e in todas}:
        return JSONResponse(
            {"status": "error", "error": f"La empresa {cod_empresa} no está en la asesoría."},
            status_code=404,
        )
    if cod_empresa not in db.empresas_de(email):
        return JSONResponse(
            {"status": "error", "error": "Tu usuario no tiene acceso a esa empresa."},
            status_code=403,
        )

    nombre = next((e["nombre"] for e in todas if e["cod_empresa"] == cod_empresa), "")
    db.registrar_ejecucion(cod_empresa=cod_empresa, ejercicio=None, modulos="login", origen="portal",
                           email=email, segundos=0.0, estado="ok", desde_cache=False,
                           detalle=f"rol={us['rol']} · empresa={cod_empresa}")
    respuesta = JSONResponse({"status": "ok", "token": token, "usuario": us,
                              "cod_empresa": cod_empresa, "empresa": nombre})
    respuesta.set_cookie("sesion", token, httponly=True, samesite="lax", max_age=60 * 60 * 8)
    return respuesta


@app.post("/api/logout")
def logout() -> JSONResponse:
    r = JSONResponse({"status": "ok"})
    r.delete_cookie("sesion")
    return r


# ---------- alta de clientes y gestión de accesos ----------
#
# Modelo acordado con ABGA: el cliente crea sus credenciales y entra con su CÓDIGO DE EMPRESA más un
# PIN que le entrega la asesoría. El código solo NO vale como credencial (son cuatro dígitos y son
# adivinables: quien probara números vería la contabilidad de otro), así que el PIN se guarda
# hasheado y sólo se enseña una vez, al generarlo.

_INTENTOS_PIN: dict[str, list[float]] = {}
_PIN_MAX_INTENTOS = 8
_PIN_VENTANA = 900.0        # segundos: 8 fallos por empresa cada 15 minutos


def _respuesta_error(mensaje: str, codigo: int) -> JSONResponse:
    return JSONResponse({"status": "error", "error": mensaje}, status_code=codigo)


def _intentos_recientes(cod: str) -> int:
    ahora = time.time()
    vivos = [t for t in _INTENTOS_PIN.get(cod, []) if ahora - t < _PIN_VENTANA]
    _INTENTOS_PIN[cod] = vivos
    return len(vivos)


def _comprobar_pin(cod: str, pin: str) -> bool:
    """Sin PIN puesto nunca vale: una empresa sin PIN no se puede reclamar."""
    return bool(pin) and auth.verificar_password(pin, db.pin_guardado(cod))


def _sesion(email: str, rol: str, empresas: list[str], *, empresa: dict[str, Any] | None = None) -> JSONResponse:
    """Deja dentro al usuario recién dado de alta, igual que el login (cookie httpOnly)."""
    token = auth.crear_token(email, rol, empresas)
    cuerpo: dict[str, Any] = {"status": "ok", "token": token, "usuario": db.usuario(email)}
    if empresa:
        cuerpo["empresa"] = {"cod_empresa": empresa["cod_empresa"], "nombre": empresa["nombre"]}
    r = JSONResponse(cuerpo)
    r.set_cookie("sesion", token, httponly=True, samesite="lax", max_age=60 * 60 * 8)
    return r


@app.post("/api/registro")
def registro(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    """Alta del cliente: crea su cuenta y entra directo en su panel."""
    email = (payload.get("email") or "").strip().lower()
    nombre = (payload.get("nombre") or "").strip()
    password = payload.get("password") or ""
    cod = str(payload.get("cod_empresa") or "").strip()
    pin = str(payload.get("pin") or "").strip()

    if "@" not in email or len(email) < 6:
        return _respuesta_error("El correo no parece válido.", 400)
    if len(password) < 10:
        return _respuesta_error("La contraseña debe tener al menos 10 caracteres.", 400)
    if db.usuario_bruto(email) is not None:
        # Una cuenta que ya existe no se pisa nunca: si no, cualquiera podría reclamar el correo de
        # un cliente ya dado de alta y quedarse con su acceso.
        return _respuesta_error("Ya existe una cuenta con ese correo. Inicia sesión, o pídenos ayuda.", 409)
    if _intentos_recientes(cod) >= _PIN_MAX_INTENTOS:
        return _respuesta_error("Demasiados intentos con ese código. Inténtalo dentro de un rato.", 429)

    empresa = db.empresa(cod)
    if empresa is None or not _comprobar_pin(cod, pin):
        _INTENTOS_PIN.setdefault(cod, []).append(time.time())
        db.registrar_ejecucion(cod_empresa=cod, ejercicio=None, modulos="alta_cliente",
                               origen="registro", email=email, segundos=0.0, estado="denegado",
                               desde_cache=False, detalle="código o PIN incorrectos")
        # Mismo mensaje para código inexistente y para PIN equivocado: a un desconocido no se le
        # confirma qué códigos de empresa existen.
        return _respuesta_error("Código de empresa o PIN incorrectos.", 403)

    db.crear_usuario(email, nombre or email.split("@")[0], auth.hash_password(password), "cliente",
                     empresas=[cod])
    db.registrar_ejecucion(cod_empresa=cod, ejercicio=None, modulos="alta_cliente", origen="registro",
                           email=email, segundos=0.0, estado="ok", desde_cache=False,
                           detalle="alta por autorregistro")
    return _sesion(email, "cliente", [cod], empresa=empresa)


@app.get("/api/interno/empresas")
def interno_empresas(q: str = Query(""), limite: int = Query(40),
                     us: dict[str, Any] = Depends(usuario_interno)) -> dict[str, Any]:
    """Buscador de empresas para el panel: 391 clientes no caben en un desplegable."""
    texto = q.strip().lower()
    empresas = db.listar_empresas()
    if texto:
        empresas = [e for e in empresas
                    if texto in str(e["cod_empresa"]).lower() or texto in (e["nombre"] or "").lower()]
    return {"status": "ok", "total": len(empresas), "empresas": empresas[:max(1, min(limite, 200))]}


@app.post("/api/interno/pin")
def interno_pin(payload: dict[str, Any] = Body(...),
                us: dict[str, Any] = Depends(usuario_interno)) -> JSONResponse:
    """Genera o regenera el PIN de una empresa. Se enseña una sola vez: no se guarda en claro."""
    cod = str(payload.get("cod_empresa") or "").strip()
    empresa = db.empresa(cod)
    if empresa is None:
        return _respuesta_error("No existe esa empresa.", 404)
    pin = auth.pin_generado()
    db.fijar_pin(cod, auth.hash_password(pin))
    db.registrar_ejecucion(cod_empresa=cod, ejercicio=None, modulos="pin_empresa", origen="interno",
                           email=us["email"], segundos=0.0, estado="ok", desde_cache=False,
                           detalle="PIN generado")
    return JSONResponse({"status": "ok", "cod_empresa": cod, "nombre": empresa["nombre"], "pin": pin,
                         "aviso": "Este PIN no se vuelve a mostrar: cópialo y dáselo al cliente junto con el código."})


@app.get("/api/interno/usuarios")
def interno_usuarios(us: dict[str, Any] = Depends(usuario_interno)) -> dict[str, Any]:
    return {"status": "ok", "usuarios": db.listar_usuarios()}


@app.post("/api/interno/usuarios")
def interno_guardar_usuario(payload: dict[str, Any] = Body(...),
                            us: dict[str, Any] = Depends(usuario_interno)) -> JSONResponse:
    """Crea o edita un usuario desde ABGA. Sin contraseña, se genera y se enseña una vez."""
    email = (payload.get("email") or "").strip().lower()
    if "@" not in email:
        return _respuesta_error("Falta un correo válido.", 400)
    rol = str(payload.get("rol") or "cliente").strip()
    if rol not in {"cliente", "interno", "admin"}:
        return _respuesta_error("Rol no válido: cliente, interno o admin.", 400)
    previo = db.usuario_bruto(email)
    nombre = (payload.get("nombre") or "").strip() or (previo["nombre"] if previo else email)
    activo = payload.get("activo")
    activo = None if activo is None else bool(activo)
    password = payload.get("password") or ""
    generada = ""
    if password and len(password) < 10:
        return _respuesta_error("La contraseña debe tener al menos 10 caracteres.", 400)
    if not password and previo is None:
        generada = auth.password_generada()
        password = generada

    if previo is None:
        db.crear_usuario(email, nombre, auth.hash_password(password), rol,
                         empresas=[str(c) for c in (payload.get("empresas") or [])])
    else:
        db.actualizar_usuario(email, nombre=nombre, rol=rol, activo=activo)
        if password:
            db.cambiar_password(email, auth.hash_password(password))
    if "empresas" in payload:
        db.definir_empresas(email, [str(c) for c in (payload.get("empresas") or [])])

    db.registrar_ejecucion(cod_empresa="", ejercicio=None, modulos="alta_cliente", origen="interno",
                           email=us["email"], segundos=0.0, estado="ok", desde_cache=False,
                           detalle=f"{'alta' if previo is None else 'edición'} de {email} rol={rol}")
    salida: dict[str, Any] = {"status": "ok", "usuario": db.usuario(email)}
    if generada:
        salida["password"] = generada
        salida["aviso"] = "Contraseña generada; no se vuelve a mostrar. Dale las credenciales al cliente."
    return JSONResponse(salida)


@app.post("/api/interno/usuarios/empresas")
def interno_asignar(payload: dict[str, Any] = Body(...),
                    us: dict[str, Any] = Depends(usuario_interno)) -> JSONResponse:
    """Deja al usuario exactamente con esas empresas (marcar y desmarcar)."""
    email = (payload.get("email") or "").strip().lower()
    if db.usuario_bruto(email) is None:
        return _respuesta_error("No existe ese usuario.", 404)
    cambio = db.definir_empresas(email, [str(c) for c in (payload.get("empresas") or [])])
    db.registrar_ejecucion(cod_empresa="", ejercicio=None, modulos="permisos", origen="interno",
                           email=us["email"], segundos=0.0, estado="ok", desde_cache=False,
                           detalle=f"{email}: +{len(cambio['añadidas'])} -{len(cambio['quitadas'])}")
    return JSONResponse({"status": "ok", "cambio": cambio, "usuario": db.usuario(email)})


@app.post("/api/interno/usuarios/eliminar")
def interno_eliminar(payload: dict[str, Any] = Body(...),
                     us: dict[str, Any] = Depends(usuario_interno)) -> JSONResponse:
    email = (payload.get("email") or "").strip().lower()
    if email == us["email"]:
        return _respuesta_error("No puedes eliminar tu propio usuario.", 400)
    if not db.eliminar_usuario(email):
        return _respuesta_error("No existe ese usuario.", 404)
    db.registrar_ejecucion(cod_empresa="", ejercicio=None, modulos="baja_usuario", origen="interno",
                           email=us["email"], segundos=0.0, estado="ok", desde_cache=False,
                           detalle=f"usuario eliminado: {email}")
    return JSONResponse({"status": "ok", "eliminado": email})


@app.get("/api/yo")
def yo(us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    return {"status": "ok", "usuario": us, "interno": auth.es_interno(us)}


@app.get("/api/empresas")
def empresas(us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    permitidas = {str(c) for c in us["empresas"]}
    lista = [e for e in db.listar_empresas() if e["cod_empresa"] in permitidas]
    if not lista and permitidas:  # empresas sin ficha creada todavía
        lista = [{"cod_empresa": c, "nombre": f"Empresa {c}", "ejercicio_inicio": None} for c in sorted(permitidas)]
    return {"status": "ok", "empresas": lista}


@app.get("/api/modulos")
def lista_modulos(us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    interno = auth.es_interno(us)
    salida = []
    for d in modulos.listar_todos():
        if not d.disponible:
            continue
        if d.interno and not interno:
            continue
        salida.append({
            "nombre": d.nombre, "titulo": d.titulo, "interno": d.interno,
            "menu": d.menu, "ejercicios": d.desplazamientos, "parametros": d.parametros,
        })
    return {"status": "ok", "modulos": salida,
            "menus": [{"clave": c, "titulo": t} for c, t in modulos.MENUS],
            "pendientes": [{"clave": c, "titulo": t, "menu": m} for c, t, m in modulos.PENDIENTES],
            "ejercicios": list(cargar_config().ejercicios_disponibles)}


# ---------- datos ----------

@app.get("/api/dashboard")
def dashboard(cod_empresa: str = Query(...), year: int = Query(...),
              forzar: bool = Query(False), us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    cod = _empresa_permitida(us, cod_empresa)
    try:
        r = servicio.datos_dashboard(cod, year, forzar=forzar)
    except apicon.ErrorErp as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=502)
    if r.get("status") != "ok":
        return JSONResponse(r, status_code=400)
    r["avisos"] = r["data"].get("avisos") or []
    return r


@app.post("/api/informe")
def informe(payload: dict[str, Any] = Body(...),
            us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    nombre = payload.get("modulo") or ""
    d = modulos.obtener(nombre)
    if not d.disponible:
        return JSONResponse({"status": "error", "error": d.error or "módulo desconocido"}, status_code=404)
    if d.interno and not auth.es_interno(us):
        return JSONResponse({"status": "error", "error": "Informe de uso interno de ABGA."}, status_code=403)
    cod = _empresa_permitida(us, payload.get("cod_empresa"))
    year = int(payload.get("year") or 0)
    params = dict(payload.get("params") or {})
    for k in ("trimestre", "umbral", "max_filas"):
        if k in payload:
            params[k] = payload[k]
    r = servicio.ejecutar(nombre, cod_empresa=cod, year=year, params=params, email=us["email"],
                          origen="portal", forzar=bool(payload.get("forzar")))
    if r.status != "ok":
        return JSONResponse(r.como_json(), status_code=502 if "ERP" in (r.error or "") else 400)
    return r.como_json()


@app.post("/api/informe/exportar")
def exportar_informe(payload: dict[str, Any] = Body(...),
                     us: dict[str, Any] = Depends(usuario_actual)) -> Response:
    """Descarga del informe para trabajarlo fuera del portal (Excel/CSV).

    Se exportan las tablas del propio informe, así que lo que se descarga el cliente es
    exactamente lo que está viendo. El PDF lo hace el navegador al imprimir, para no meter un
    motor de PDF en el servidor.
    """
    nombre = payload.get("modulo") or ""
    d = modulos.obtener(nombre)
    if not d.disponible:
        return JSONResponse({"status": "error", "error": d.error or "módulo desconocido"}, status_code=404)
    if d.interno and not auth.es_interno(us):
        return JSONResponse({"status": "error", "error": "Informe de uso interno de ABGA."}, status_code=403)
    cod = _empresa_permitida(us, payload.get("cod_empresa"))
    year = int(payload.get("year") or 0)

    r = servicio.ejecutar(nombre, cod_empresa=cod, year=year, params=dict(payload.get("params") or {}),
                          email=us["email"], origen="exportar")
    if r.status != "ok":
        return JSONResponse(r.como_json(), status_code=502 if "ERP" in (r.error or "") else 400)

    contenido, fichero, mime = exportar.a_excel(r.html, base=f"{nombre}_{cod}_{year}")
    return Response(content=contenido, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{fichero}"',
                             "X-Tablas": str(exportar.resumen(r.html)["n_tablas"])})


@app.post("/api/refrescar")
def refrescar(payload: dict[str, Any] = Body(...),
              us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    """Lanza la lectura del ejercicio en segundo plano (progreso en /api/trabajos/{id})."""
    cod = _empresa_permitida(us, payload.get("cod_empresa"))
    year = int(payload.get("year") or 0)
    t = trabajos.lanzar_carga(cod, year, modulos_pedidos=payload.get("modulos"),
                              forzar=bool(payload.get("forzar", True)), email=us["email"])
    return {"status": "ok", "trabajo": t.como_json()}


@app.get("/api/trabajos/{tid}")
def estado_trabajo(tid: str, us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    t = trabajos.obtener(tid)
    if not t:
        return JSONResponse({"status": "error", "error": "Trabajo no encontrado"}, status_code=404)
    return {"status": "ok", "trabajo": t.como_json()}


@app.get("/api/trabajos")
def lista_trabajos(us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    return {"status": "ok", "trabajos": trabajos.listar()}


# ---------- panel interno de ABGA ----------

@app.get("/api/interno/resumen")
def resumen_interno(cod_empresa: str | None = Query(None),
                    us: dict[str, Any] = Depends(usuario_interno)) -> dict[str, Any]:
    return {
        "status": "ok",
        "ejecuciones": db.ejecuciones(cod_empresa=cod_empresa, limite=60),
        "por_estado": db.resumen_ejecuciones(30),
        "cache": cache.info_cache(cod_empresa),
        "trabajos": trabajos.listar(10),
        "empresas": db.listar_empresas(),
        "usuarios": db.listar_usuarios(),
        "modulos": [{"nombre": d.nombre, "titulo": d.titulo, "interno": d.interno,
                     "disponible": d.disponible, "error": d.error} for d in modulos.listar_todos()],
    }


@app.post("/api/interno/cache")
def gestionar_cache(payload: dict[str, Any] = Body(...),
                    us: dict[str, Any] = Depends(usuario_interno)) -> dict[str, Any]:
    cod = str(payload.get("cod_empresa") or "")
    if not cod:
        raise HTTPException(status_code=400, detail="Falta cod_empresa")
    year = payload.get("year")
    borrados = cache.invalidar(cod, int(year) if year else None)
    db.registrar_ejecucion(cod_empresa=cod, ejercicio=int(year) if year else None,
                           modulos="invalidar_cache", origen="interno", email=us["email"],
                           segundos=0.0, estado="ok", desde_cache=False,
                           detalle=f"{borrados} ejercicios borrados de la caché")
    return {"status": "ok", "borrados": borrados, "cache": cache.info_cache(cod)}


@app.post("/api/interno/usuarios")
def crear_usuario(payload: dict[str, Any] = Body(...),
                  us: dict[str, Any] = Depends(usuario_interno)) -> dict[str, Any]:
    email = (payload.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email no válido")
    password = payload.get("password") or auth.password_generada()
    rol = payload.get("rol") or "cliente"
    if rol not in {"cliente", "interno", "admin"}:
        raise HTTPException(status_code=400, detail="Rol no válido")
    db.crear_usuario(email, payload.get("nombre") or email, auth.hash_password(password), rol,
                     empresas=[str(c) for c in (payload.get("empresas") or [])])
    return {"status": "ok", "email": email, "password": password, "rol": rol,
            "empresas": db.empresas_de(email)}


@app.post("/api/interno/empresas")
def crear_empresa(payload: dict[str, Any] = Body(...),
                  us: dict[str, Any] = Depends(usuario_interno)) -> dict[str, Any]:
    cod = str(payload.get("cod_empresa") or "").strip()
    nombre = (payload.get("nombre") or "").strip()
    if not cod or not nombre:
        raise HTTPException(status_code=400, detail="Hacen falta código y nombre")
    db.crear_empresa(cod, nombre, payload.get("ejercicio_inicio"), payload.get("notas") or "")
    return {"status": "ok", "empresa": db.empresa(cod)}


# ---------- diagnóstico ----------

@app.get("/api/ejercicios")
def ejercicios_disponibles(cod_empresa: str = Query(...),
                           us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    """Ejercicios de la empresa y cuáles tienen datos ya cargados.

    El portal lo usa para abrir por el último ejercicio **con datos** en lugar del año en curso
    (que a mitad de año aparece vacío y llena la pantalla de avisos que no vienen a cuento).
    """
    cod = _empresa_permitida(us, cod_empresa)
    cfg = cargar_config()
    en_cache = {int(c["ejercicio"]): c for c in cache.info_cache(cod)}
    lista = []
    for y in sorted(cfg.ejercicios_disponibles, reverse=True):
        c = en_cache.get(y)
        lista.append({
            "year": y,
            "en_cache": c is not None,
            "n_asientos": c["n_asientos"] if c else None,
            "cobertura": c["cobertura"] if c else None,
            "tiene_datos": (c["n_asientos"] > 0) if c else None,
            "actualizado": c["actualizado"] if c else None,
        })
    return {"status": "ok", "empresa": db.nombre_empresa(cod), "cod_empresa": cod, "ejercicios": lista}


@app.get("/api/salud")
def salud() -> dict[str, Any]:
    cfg = cargar_config()
    return {
        "status": "ok",
        "version": app.version,
        "erp": cfg.apicon_base,
        "cache": {"ficheros": str(cfg.cache_db.name), "ttl_apuntes": cfg.ttl_apuntes},
        "modulos": [{"nombre": d.nombre, "disponible": d.disponible, "error": d.error}
                    for d in modulos.listar_todos()],
        "ejercicios": list(cfg.ejercicios_disponibles),
    }


@app.get("/api/cache")
def estado_cache(cod_empresa: str | None = Query(None),
                 us: dict[str, Any] = Depends(usuario_actual)) -> dict[str, Any]:
    cod = cod_empresa
    if cod is not None:
        _empresa_permitida(us, cod)
    return {"status": "ok", "cache": cache.info_cache(cod)}


@app.get("/", response_class=HTMLResponse)
def raiz() -> HTMLResponse:
    return HTMLResponse((FRONTEND / "index.html").read_text(encoding="utf-8"))


@app.exception_handler(apicon.ErrorErp)
def error_erp(_: Request, exc: apicon.ErrorErp) -> JSONResponse:
    return JSONResponse({"status": "error", "error": str(exc)}, status_code=502)


if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
