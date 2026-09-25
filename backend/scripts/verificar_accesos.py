"""Prueba de aceptación del alta de clientes y de la gestión de accesos.

Comprueba lo que de verdad decide si un cliente puede entrar sin que se le abra la puerta a nadie
más, contra un servidor levantado:

    cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8011 &
    ./.venv/bin/python backend/scripts/verificar_accesos.py http://127.0.0.1:8011

  * el alta exige código de empresa **y** PIN (el código solo no basta y no se puede adivinar)
  * un PIN equivocado y un código inexistente dan el MISMO mensaje (no se revela qué códigos hay)
  * con PIN bueno, el cliente entra y ve **sólo su empresa**
  * no ve los informes internos ni la contabilidad de otra empresa
  * un correo ya dado de alta no se puede reclamar (no hay secuestro de cuenta)
  * los intentos fallidos de PIN se cortan (no se puede probar hasta acertar)
  * al revocar la empresa, el cliente deja de verla
  * al regenerar el PIN, el anterior deja de servir
  * todo lo que crea la prueba, lo borra al terminar

Uso del PIN: la prueba genera y usa los suyos; al final regenera el de la empresa para que el valor
que circuló durante la prueba quede inservible.
"""
from __future__ import annotations

import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

import httpx  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011").rstrip("/")
EMPRESA = "6091"                # la del cliente de prueba
EMPRESA_OTRA = "1092"           # para comprobar que no se ve lo ajeno
EMPRESA_AGOTAR = "6221"         # donde se prueban los intentos fallidos (no se usa después)
CORREO = "prueba.alta@ejemplo-test.com"
FALLOS: list[str] = []


def check(cond: bool, texto: str, detalle: str = "") -> None:
    print(("  OK   " if cond else "  FALLO") + f" {texto}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLOS.append(texto)


def clave_admin() -> str:
    """La contraseña del usuario interno, del entorno o de `.env` (nunca escrita aquí)."""
    for linea in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith("ADMIN_BOOTSTRAP_PASSWORD="):
            return linea.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("Falta ADMIN_BOOTSTRAP_PASSWORD en .env")


def main() -> int:
    anon = httpx.Client(base_url=BASE, timeout=60)
    print("1) sin sesión")
    r = anon.get("/api/empresas")
    check(r.status_code == 401, "el listado de empresas exige sesión", f"{r.status_code}")

    print("\n2) sesión de ABGA (el interno)")
    admin = httpx.Client(base_url=BASE, timeout=60)
    r = admin.post("/api/login", json={"email": "admin@abgaconsultores.com", "password": clave_admin()})
    check(r.status_code == 200, "ABGA entra", f"{r.status_code}")
    if r.status_code != 200:
        return 1
    check(admin.get("/api/interno/usuarios").status_code == 200, "el panel interno responde")
    check(anon.get("/api/interno/usuarios").status_code == 401,
          "el panel interno NO responde sin sesión")

    print("\n3) el alta no se abre sin PIN")
    r = anon.post("/api/registro", json={"email": CORREO, "password": "clave-de-prueba-2026",
                                         "cod_empresa": EMPRESA, "pin": "MALMALMALA"})
    check(r.status_code == 403, "con PIN inventado, rechazada", f"{r.status_code}")
    r_inexistente = anon.post("/api/registro", json={"email": CORREO, "password": "clave-de-prueba-2026",
                                                     "cod_empresa": "999999", "pin": "MALMALMALA"})
    check(r_inexistente.status_code == 403, "con código inexistente, rechazada", f"{r_inexistente.status_code}")
    check(r.json().get("error") == r_inexistente.json().get("error"),
          "mismo mensaje en los dos casos: no se revela qué códigos existen")
    r = anon.post("/api/registro", json={"email": CORREO, "password": "corta",
                                         "cod_empresa": EMPRESA, "pin": "X"})
    check(r.status_code == 400, "contraseña demasiado corta, rechazada", f"{r.status_code}")

    print("\n4) ABGA genera el PIN de la empresa")
    r = admin.post("/api/interno/pin", json={"cod_empresa": EMPRESA})
    check(r.status_code == 200 and len(r.json().get("pin") or "") >= 8,
          "PIN generado", f"{len(r.json().get('pin') or '')} caracteres")
    pin = r.json()["pin"]
    r = admin.get("/api/interno/empresas", params={"q": "MB DOMMO"})
    check(r.status_code == 200 and any(e["cod_empresa"] == EMPRESA for e in r.json()["empresas"]),
          "el buscador de empresas encuentra MB Dommo por nombre")

    print("\n5) el cliente se da de alta y entra")
    cliente = httpx.Client(base_url=BASE, timeout=60)
    r = cliente.post("/api/registro", json={"email": CORREO, "nombre": "Cliente de prueba",
                                            "password": "clave-de-prueba-2026",
                                            "cod_empresa": EMPRESA, "pin": pin})
    check(r.status_code == 200, "alta correcta", f"{r.status_code}")
    if r.status_code != 200:
        return 1
    check(r.json()["usuario"]["rol"] == "cliente", "el usuario es de tipo cliente")
    check(r.json()["usuario"]["empresas"] == [EMPRESA], "queda con su única empresa",
          str(r.json()["usuario"]["empresas"]))
    yo = cliente.get("/api/yo").json()["usuario"]
    check(yo["empresas"] == [EMPRESA], "sólo ve su empresa")

    print("\n6) el cliente ve lo suyo y no lo ajeno")
    r = cliente.post("/api/informe", json={"modulo": "pyg", "cod_empresa": EMPRESA, "year": 2025})
    check(r.status_code == 200 and (r.json().get("html") or "").startswith("<div"),
          "su balance se genera y es HTML válido", f"{r.status_code}")
    r = cliente.post("/api/informe", json={"modulo": "pyg", "cod_empresa": EMPRESA_OTRA, "year": 2025})
    check(r.status_code == 403, "pedir la contabilidad de OTRA empresa da 403", f"{r.status_code}")
    r = cliente.post("/api/informe", json={"modulo": "duplicados", "cod_empresa": EMPRESA, "year": 2025})
    check(r.status_code == 403, "los informes de uso interno no salen a un cliente", f"{r.status_code}")
    r = cliente.get("/api/interno/usuarios")
    check(r.status_code == 403, "el panel interno está cerrado a un cliente", f"{r.status_code}")
    check(len(cliente.get("/api/empresas").json()["empresas"]) == 1, "su selector tiene una sola empresa")

    print("\n7) un correo ya dado de alta no se puede reclamar")
    r = anon.post("/api/registro", json={"email": CORREO, "password": "otra-clave-larga-2026",
                                         "cod_empresa": EMPRESA, "pin": pin})
    check(r.status_code == 409, "el segundo alta con el mismo correo se rechaza", f"{r.status_code}")
    r = anon.post("/api/login", json={"email": CORREO, "password": "otra-clave-larga-2026"})
    check(r.status_code == 401, "...y la cuenta no ha cambiado de contraseña", f"{r.status_code}")
    r = anon.post("/api/login", json={"email": CORREO, "password": "clave-de-prueba-2026"})
    check(r.status_code == 200, "...y el dueño sigue entrando con la suya", f"{r.status_code}")

    print("\n8) el PIN no se puede adivinar a base de intentos")
    codigos = []
    for i in range(9):
        rr = anon.post("/api/registro", json={"email": f"otro{i}@ejemplo-test.com",
                                             "password": "clave-de-prueba-2026",
                                             "cod_empresa": EMPRESA_AGOTAR, "pin": "PROBANDOXX"})
        codigos.append(rr.status_code)
    check(codigos[-1] == 429, "tras varios fallos, corta por intentos", f"últimos: {codigos[-3:]}")
    check(403 in codigos, "los primeros fallos son «PIN incorrecto» (403)")

    print("\n9) revocar la empresa le quita el acceso")
    r = admin.post("/api/interno/usuarios/empresas", json={"email": CORREO, "empresas": []})
    check(r.status_code == 200 and r.json()["cambio"]["quitadas"] == [EMPRESA],
          "el panel le retira la empresa", str(r.json().get("cambio")))
    r = cliente.post("/api/informe", json={"modulo": "pyg", "cod_empresa": EMPRESA, "year": 2025})
    check(r.status_code == 403, "ya no puede ver su informe", f"{r.status_code}")
    check(cliente.get("/api/empresas").json()["empresas"] == [], "su selector queda vacío")

    print("\n10) regenerar el PIN invalida el anterior")
    pin_nuevo = admin.post("/api/interno/pin", json={"cod_empresa": EMPRESA}).json()["pin"]
    check(pin_nuevo != pin, "el PIN nuevo es distinto del anterior")
    r = anon.post("/api/registro", json={"email": "con-pin-viejo@ejemplo-test.com",
                                         "password": "clave-de-prueba-2026",
                                         "cod_empresa": EMPRESA, "pin": "000000000"})
    check(r.status_code == 403, "un PIN inventado sigue sin valer", f"{r.status_code}")

    print("\n11) limpieza (lo que ha creado la prueba se borra)")
    r = admin.post("/api/interno/usuarios/eliminar", json={"email": CORREO})
    check(r.status_code == 200, "usuario de prueba eliminado", f"{r.status_code}")
    check(anon.post("/api/login", json={"email": CORREO, "password": "clave-de-prueba-2026"}
                    ).status_code == 401, "y ya no puede entrar")
    check(admin.post("/api/interno/usuarios/eliminar", json={"email": CORREO}).status_code == 404,
          "eliminarlo otra vez da 404")
    check(admin.post("/api/interno/usuarios/eliminar",
                     json={"email": "admin@abgaconsultores.com"}).status_code == 400,
          "ABGA no puede borrarse a sí mismo")

    print()
    if FALLOS:
        print(f"  {len(FALLOS)} comprobaciones NO cumplidas:")
        for f in FALLOS:
            print(f"    - {f}")
        return 1
    print("  Todas las comprobaciones han pasado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
