"""Sonda de la API apiCON: mide tiempos, comprueba paginación y detecta el truncado a 5000.

Uso:  .venv/bin/python scripts/probe_apicon.py [cod_empresa] [year]
No imprime credenciales ni importes: sólo métricas y recuentos.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[2]  # raíz del proyecto (…/nuevo), donde vive .env


def cargar_env(ruta: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not ruta.exists():
        raise SystemExit(f"Falta {ruta}")
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def main() -> None:
    env = cargar_env(RAIZ / ".env")
    empresa = sys.argv[1] if len(sys.argv) > 1 else env["APICON_EMPRESA_DEFECTO"]
    year = sys.argv[2] if len(sys.argv) > 2 else "2025"
    base = env["APICON_BASE"].rstrip("/")

    with httpx.Client(timeout=120.0) as c:
        t0 = time.perf_counter()
        r = c.post(
            f"{base}/token",
            data={
                "grant_type": "password",
                "username": env["APICON_USERNAME"],
                "password": env["APICON_PASSWORD"],
                "client_id": env["APICON_CLIENT_ID"],
                "client_secret": env["APICON_CLIENT_SECRET"],
                "cod_empresa": empresa,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        t_token = time.perf_counter() - t0
        print(f"POST /token -> HTTP {r.status_code} en {t_token:.2f}s")
        if r.status_code != 200:
            print("  cuerpo (recortado):", r.text[:300])
            return
        tok = r.json()
        print("  claves del token:", sorted(tok.keys()))
        print("  expira_en:", tok.get("expires_in"), "| .expires:", tok.get("expires"))
        access = tok.get("access_token") or tok.get("token")
        if not access:
            print("  SIN access_token:", json.dumps(tok)[:300])
            return

        cab = {"Authorization": f"Bearer {access}", "Accept": "application/json"}

        # 1) consulta tal cual la hacen los workflows
        url = f"{base}/api/apuntes/"
        params = {"$filter": f"Ejercicio eq '{year}'", "$top": env.get("APICON_TOP", "5000")}
        t0 = time.perf_counter()
        rr = c.get(url, params=params, headers=cab)
        t_get = time.perf_counter() - t0
        print(f"\nGET /api/apuntes/ $top={params['$top']} -> HTTP {rr.status_code} en {t_get:.2f}s, {len(rr.content)/1e6:.2f} MB")
        if rr.status_code != 200:
            print("  cuerpo (recortado):", rr.text[:300])
            return
        j = rr.json()
        datos = j.get("Datos") if isinstance(j, dict) else None
        print("  claves raíz:", sorted(j.keys()) if isinstance(j, dict) else type(j).__name__)
        if datos is None:
            print("  sin clave Datos:", json.dumps(j)[:300])
            return
        n_as = len(datos)
        n_lin = sum(len(a.get("Detalles") or []) for a in datos)
        print(f"  asientos={n_as}  lineas_de_detalle={n_lin}  TRUNCADO={n_as == int(params['$top'])}")
        if datos:
            a = datos[0]
            print("  claves asiento:", sorted(a.keys()))
            if a.get("Detalles"):
                print("  claves detalle:", sorted(a["Detalles"][0].keys()))
                print("  ejemplo detalle:", {k: ("<num>" if isinstance(v, (int, float)) else str(v)[:24]) for k, v in a["Detalles"][0].items()})

        # 2) ¿se puede contar exacto?
        for extra in ({"$count": "true"}, {"$inlinecount": "allpages"}):
            p2 = dict(params); p2["$top"] = "1"; p2.update(extra)
            r2 = c.get(url, params=p2, headers=cab)
            cuerpo = r2.text
            raiz_count = '"count"' in cuerpo[:200]
            print(f"\n  prueba {extra} -> HTTP {r2.status_code}; '@odata.count' presente={'@odata.count' in cuerpo}; 'count' en raiz={raiz_count}")

        # 3) ¿hay $skip / $orderby?
        p3 = {"$filter": f"Ejercicio eq '{year}'", "$top": "3", "$skip": "3", "$orderby": "Fecha"}
        r3 = c.get(url, params=p3, headers=cab)
        try:
            j3 = r3.json().get("Datos") or []
        except Exception:
            j3 = []
        print(f"\n  prueba $skip/$orderby -> HTTP {r3.status_code}, devueltos={len(j3)}")
        if datos and j3:
            f1 = json.dumps(datos[3].get("Fecha") if len(datos) > 3 else None)
            f2 = json.dumps(j3[0].get("Fecha"))
            print(f"  ¿$skip aplica? primera fecha sin skip={f1} con $skip=3 -> {f2} | parecen ordenados={datos == sorted(datos, key=lambda x: str(x.get('Fecha')))}")

        # 4) filtros por rango de fechas (más fino que el ejercicio)
        p4 = {"$filter": f"Fecha ge '2025-01-01' and Fecha le '2025-12-31'", "$top": "5"}
        r4 = c.get(url, params=p4, headers=cab)
        try:
            n4 = len(r4.json().get("Datos") or [])
        except Exception:
            n4 = -1
        print(f"  filtro por Fecha (ISO) -> HTTP {r4.status_code}, asientos={n4}")

        # 5) ejercicios disponibles para esta empresa
        for probe in ("2023", "2024", "2025", "2026"):
            pp = {"$filter": f"Ejercicio eq '{probe}'", "$top": "1"}
            rp = c.get(url, params=pp, headers=cab)
            try:
                n = len(rp.json().get("Datos") or [])
            except Exception:
                n = -1
            print(f"  ejercicio {probe}: HTTP {rp.status_code} asientos_1={n}")


if __name__ == "__main__":
    main()
