"""Sonda de los endpoints de apiCON que no se habían probado.

Los conocemos por las colecciones de Postman que mandó ABGA (`apiCON - K1970.postman_collection
.json`). Hasta ahora el proyecto sólo usaba `/token` y `/api/apuntes/`, y daba por hecho que no
existían endpoints agregados. Aquí se comprueba, endpoint a endpoint, cuáles responden, cuántos
elementos devuelven y con qué forma, para decidir qué se puede aprovechar (sobre todo
`/api/clientes/` y `/api/proveedores/`, que darían el nombre de los terceros: en los apuntes el
campo `Tercero` viene vacío).

Es de SOLO LECTURA y va espaciado, porque es el ERP de producción de ABGA.

    ./.venv/bin/python backend/scripts/probe_endpoints_api.py [cod_empresa] [ejercicio]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import apicon  # noqa: E402

SONDEOS: list[tuple[str, str, dict]] = [
    ("subcuentas (grupo 3)", "/api/subcuentas/",
     {"$filter": "Grupo eq 3", "$select": "Codigo,Descripcion"}),
    ("subcuentas (subgrupo 43)", "/api/subcuentas/", {"$filter": "Subgrupo eq 43"}),
    ("clientes", "/api/clientes/", {"$orderby": "Codigo desc"}),
    ("proveedores", "/api/proveedores/", {"$orderby": "Codigo desc"}),
    ("facturas", "/api/facturas/", {"$orderby": "Fecha desc"}),
    ("facturasestimaciones/recibidas", "/api/facturasestimaciones/recibidas/", {}),
]


def _resumen(cuerpo: bytes) -> str:
    try:
        d = json.loads(cuerpo)
    except Exception:
        return f"no es JSON ({len(cuerpo)} bytes): {cuerpo[:120]!r}"
    if isinstance(d, dict):
        claves = list(d.keys())
        elementos = None
        for k in ("Datos", "data", "resultado", "Resultado", "items"):
            if isinstance(d.get(k), list):
                elementos = d[k]
                break
        total = d.get("ResultadosTotales") or d.get("total")
        texto = f"claves={claves}"
        if total is not None:
            texto += f" · ResultadosTotales={total}"
        if elementos is not None:
            texto += f" · elementos={len(elementos)}"
            if elementos:
                primero = elementos[0]
                if isinstance(primero, dict):
                    texto += f"\n      campos: {sorted(primero.keys())}"
                    texto += f"\n      muestra: {json.dumps(primero, ensure_ascii=False)[:260]}"
        elif isinstance(d, list):
            texto += f" · elementos={len(d)}"
        return texto
    return f"lista con {len(d)} elementos · muestra: {json.dumps(d[:1], ensure_ascii=False)[:200]}"


def main() -> int:
    empresa = sys.argv[1] if len(sys.argv) > 1 else "6221"
    ejercicio = sys.argv[2] if len(sys.argv) > 2 else "2025"
    cli = apicon.cliente()
    print(f"sondando apiCON para la empresa {empresa} (ejercicio {ejercicio})\n")

    for etiqueta, ruta, params in SONDEOS:
        p = dict(params)
        if "$filter" in p and etiqueta == "facturas":
            p["$filter"] = f"Ejercicio eq '{ejercicio}'"
        try:
            r = cli._pedir("GET", ruta, params=p, headers=cli._cab(empresa))
            print(f"--- {etiqueta}: HTTP {r.status_code}  ({ruta})")
            print(f"      {_resumen(r.content)}")
        except Exception as e:
            print(f"--- {etiqueta}: FALLO {type(e).__name__}: {str(e)[:140]}")
        time.sleep(3)  # el ERP responde 429 si se le machaca

    print("\nfin de la sonda")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
