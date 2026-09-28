"""Saca la forma REAL de cada respuesta de la API de la plataforma.

Es lo que necesita la capa de datos del hub para traducir: no cómo se llama el campo, sino qué
hay dentro de verdad y de qué tipo. Va contra la plataforma en local, con la sesión del usuario
interno, y **sólo lee lo que ya está en la caché** (si un ejercicio no está cacheado, no se le pide
nada al ERP: se salta).

    ./.venv/bin/python backend/scripts/probe_api_hub.py [puerto]
"""

import json
import pathlib
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

RAIZ = pathlib.Path(__file__).resolve().parents[2]
PUERTO = sys.argv[1] if len(sys.argv) > 1 else "8011"
BASE = f"http://127.0.0.1:{PUERTO}"

BUZON = CookieJar()
ABRIR = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(BUZON))


def leer_env() -> dict:
    datos = {}
    for linea in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in linea and not linea.strip().startswith("#"):
            k, v = linea.split("=", 1)
            datos[k.strip()] = v.strip()
    return datos


def api(ruta: str, cuerpo: dict | None = None) -> object:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(BASE + ruta, data=datos,
                                     headers={"Content-Type": "application/json"} if datos else {})
    try:
        with ABRIR.open(peticion, timeout=240) as respuesta:
            texto = respuesta.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as fallo:
        texto = fallo.read().decode("utf-8", "replace")
        return {"__error_http": fallo.code, "__cuerpo": texto[:200]}
    try:
        return json.loads(texto)
    except Exception:
        return {"__no_json": texto[:200]}


def forma(valor, prof=0, maximo=2) -> str:
    if isinstance(valor, dict):
        if prof >= maximo:
            return "{" + ", ".join(list(valor)[:10]) + "}"
        return "{" + ", ".join(f"{k}: {forma(v, prof + 1, maximo)}" for k, v in list(valor.items())[:26]) + "}"
    if isinstance(valor, list):
        return f"[{len(valor)}]" + (" de " + forma(valor[0], prof + 1, maximo) if valor else "")
    if isinstance(valor, bool):
        return "bool"
    if isinstance(valor, (int, float)):
        return type(valor).__name__
    if valor is None:
        return "None"
    return f"str({str(valor)[:34]})"


def mostrar(titulo: str, valor) -> None:
    print(f"\n### {titulo}\n{forma(valor)}")


env = leer_env()
EMPRESA_SESION = sys.argv[2] if len(sys.argv) > 2 else "6091"
entrada = api("/api/login", {"email": "admin@abgaconsultores.com",
                            "password": env.get("ADMIN_BOOTSTRAP_PASSWORD", ""),
                            "cod_empresa": EMPRESA_SESION})
print("sesión:", "ok" if isinstance(entrada, dict) and "usuario" in entrada else entrada)

mostrar("/api/yo", api("/api/yo"))
mostrar("/api/modulos", api("/api/modulos"))
mostrar("/api/interno/resumen", api("/api/interno/resumen"))
mostrar("/api/interno/metricas?dias=14", api("/api/interno/metricas?dias=14"))
mostrar("/api/interno/avisos", api("/api/interno/avisos"))
mostrar("/api/interno/usuarios", api("/api/interno/usuarios"))

empresas = api("/api/empresas")
mostrar("/api/empresas", empresas)
lista = empresas.get("empresas", []) if isinstance(empresas, dict) else []
print(f"\nempresas: {len(lista)}")

cache = api("/api/cache")
mostrar("/api/cache", cache)
cacheadas = []
if isinstance(cache, dict):
    for clave, valor in list(cache.items())[:40]:
        if isinstance(valor, list):
            cacheadas.append((clave, [str(x) for x in valor][:6]))
for clave, valor in cacheadas[:14]:
    print(f"  cache {clave}: {valor}")

# Sólo se prueban ejercicios que ya están en la caché: nada de despertar al ERP.
# Sólo se prueba lo que YA está en la caché: pedir un ejercicio frío es despertar al ERP.
cacheadas = [(str(c.get("empresa")), int(c.get("ejercicio")))
             for c in (cache.get("cache", []) if isinstance(cache, dict) else [])]
print(f"\ncombinaciones en caché: {len(cacheadas)}")
objetivo = None
if len(sys.argv) > 3:
    objetivo = (sys.argv[2], int(sys.argv[3]), "")
else:
    for cod, annio in sorted(cacheadas, key=lambda x: -x[1]):
        annos = api(f"/api/ejercicios?cod_empresa={cod}")
        mostrar(f"/api/ejercicios?cod_empresa={cod}", annos)
        nombre = next((e.get("nombre", "") for e in lista if e.get("cod_empresa") == cod), "")
        if any(isinstance(a, dict) and a.get("year") == annio and a.get("en_cache") for a in (annos.get("ejercicios") or [])):
            objetivo = (cod, annio, nombre)
            break
if not objetivo:
    print("no hay ningún ejercicio en caché: no se piden informes")
    raise SystemExit(0)

cod, year, nombre = objetivo
print(f"\n--- probando informes de {cod} · {year} ({nombre})")
mostrar(f"/api/dashboard?cod_empresa={cod}&year={year}", api(f"/api/dashboard?cod_empresa={cod}&year={year}"))
mostrar(f"/api/analisis?cod_empresa={cod}&year={year}", api(f"/api/analisis?cod_empresa={cod}&year={year}"))
mostrar(f"/api/interno/cartera?year={year}", api(f"/api/interno/cartera?year={year}"))
mostrar(f"/api/interno/umbrales?cod_empresa={cod}", api(f"/api/interno/umbrales?cod_empresa={cod}"))

for modulo in ("pyg", "balance", "memoria", "conciliacion", "duplicados", "fiscal", "proyecciones", "libro_iva"):
    respuesta = api("/api/informe", {"modulo": modulo, "cod_empresa": cod, "year": year})
    if isinstance(respuesta, dict) and "__error_http" in respuesta:
        print(f"\n### informe {modulo} → {respuesta['__error_http']} {respuesta['__cuerpo'][:120]}")
        continue
    datos = respuesta.get("data", {}) if isinstance(respuesta, dict) else {}  # type: ignore[union-attr]
    meta = respuesta.get("meta", {}) if isinstance(respuesta, dict) else {}  # type: ignore[union-attr]
    documento = respuesta.get("html", "") if isinstance(respuesta, dict) else ""
    print(f"\n### informe {modulo}  (html {len(documento)} car)  meta={forma(meta, 0, 1)}")
    print(forma(datos, 0, 2))
