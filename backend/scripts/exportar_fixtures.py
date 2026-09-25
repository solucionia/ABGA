"""Exporta la caché a `fixtures/` para poder verificar sin tocar el ERP.

Uso: ./.venv/bin/python backend/scripts/exportar_fixtures.py [cod_empresa ...]

Los fixtures resultantes son respuestas reales del ERP (mismo contenido que la caché), pero
están fuera de git: contienen datos del cliente.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import cache  # noqa: E402

DESTINO = RAIZ / "fixtures"


def main() -> None:
    empresas = [a for a in sys.argv[1:] if not a.startswith("-")]
    DESTINO.mkdir(exist_ok=True)
    entradas = cache.info_cache()
    if empresas:
        entradas = [e for e in entradas if e["empresa"] in empresas]
    for e in entradas:
        guardado = cache.leer_apuntes(e["empresa"], e["ejercicio"], ttl=-1)
        if not guardado:
            continue
        ruta = DESTINO / f"apuntes_{e['empresa']}_{e['ejercicio']}.json"
        ruta.write_text(json.dumps({
            "empresa": e["empresa"], "year": e["ejercicio"],
            "resultados_totales_declarados": e["resultados_totales"],
            "cobertura": e["cobertura"],
            "asientos": guardado["asientos"],
        }, ensure_ascii=False), encoding="utf-8")
        print(f"{ruta.name}: {e['n_asientos']} asientos, {e['n_lineas']} líneas, "
              f"{ruta.stat().st_size / 1e6:.2f} MB · {e['cobertura']}")


if __name__ == "__main__":
    main()
