"""Trae un ejercicio completo, ya con la semántica correcta de paginación.

Descubrimiento de las sondas anteriores:
  * `$top`  = tamaño de página (máximo real 200)
  * `$skip` = NÚMERO DE PÁGINA (1-indexado), no desplazamiento de filas
  * la envoltura trae `ResultadosTotales`, que es el total real del ejercicio
Por eso los workflows (que pedían `$top=5000` una sola vez) sólo veían 200 asientos.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import cargar_config  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
RAW = RAIZ / "fixtures" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
cfg = cargar_config()
BASE = cfg.apicon_base.rstrip("/")
EMPRESA = sys.argv[1] if len(sys.argv) > 1 else "6091"
YEARS = [int(a) for a in (sys.argv[2:] or ["2025"])]
PAUSA = 3.0
PAGINA = 200

cli = httpx.Client(timeout=180.0)


def get(params: dict, cab: dict, nota: str) -> httpx.Response:
    time.sleep(PAUSA)
    t0 = time.perf_counter()
    r = cli.get(f"{BASE}/api/apuntes/", params=params, headers=cab)
    print(f"[{r.status_code}] {nota} -> {time.perf_counter() - t0:.2f}s {len(r.content)/1e6:.2f}MB")
    return r


def main() -> None:
    tok = cli.post(
        f"{BASE}/token",
        data={"grant_type": "password", "username": cfg.apicon_username, "password": cfg.apicon_password,
              "client_id": cfg.apicon_client_id, "client_secret": cfg.apicon_client_secret,
              "cod_empresa": EMPRESA},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    cab = {"Authorization": f"Bearer {tok.json()['access_token']}", "Accept": "application/json"}
    print(f"token ok · empresa {EMPRESA}\n")

    for year in YEARS:
        print(f"=== ejercicio {year} ===")
        filtro = f"Ejercicio eq '{year}'"
        p1 = get({"$filter": filtro, "$top": str(PAGINA), "$skip": "1"}, cab, "pág 1")
        if p1.status_code != 200:
            print("   no se pudo leer:", p1.text[:200])
            continue
        j1 = p1.json()
        total = int(j1.get("ResultadosTotales") or 0)
        n_pag = (total + PAGINA - 1) // PAGINA
        print(f"   ResultadosTotales={total} -> {n_pag} páginas")

        asientos: dict[str, dict] = {}

        def clave(a: dict) -> str:
            return f"{a.get('Ejercicio')}|{a.get('Serie')}|{a.get('Documento')}|{a.get('Fecha')}|{a.get('Debe')}|{a.get('Haber')}"

        for a in j1.get("Datos") or []:
            asientos[clave(a)] = a
        (RAW / f"pag1_{EMPRESA}_{year}.json").write_bytes(p1.content)
        print(f"   pág 1: {len(j1.get('Datos') or [])} asientos, acumulado {len(asientos)}")

        for pag in range(2, n_pag + 1):
            r = get({"$filter": filtro, "$top": str(PAGINA), "$skip": str(pag)}, cab, f"pág {pag}")
            if r.status_code != 200:
                print("   corte en la página", pag, r.text[:160])
                break
            jj = r.json()
            datos = jj.get("Datos") or []
            nuevos = 0
            for a in datos:
                k = clave(a)
                if k not in asientos:
                    nuevos += 1
                asientos[k] = a
            print(f"   pág {pag} (PaginaActual={jj.get('PaginaActual')}): {len(datos)} asientos, "
                  f"nuevos {nuevos}, acumulado {len(asientos)}")
            (RAW / f"pag{pag}_{EMPRESA}_{year}.json").write_bytes(r.content)

        lista = sorted(asientos.values(), key=lambda a: (str(a.get("Fecha")), str(a.get("Documento"))))
        lineas = sum(len(a.get("Detalles") or []) for a in lista)
        cobertura = "completa" if len(lista) >= total else f"incompleta ({len(lista)}/{total})"
        destino = RAIZ / "fixtures" / f"apuntes_{EMPRESA}_{year}.json"
        destino.write_text(json.dumps({"empresa": EMPRESA, "year": year,
                                       "resultados_totales_declarados": total,
                                       "asientos": lista}, ensure_ascii=False), encoding="utf-8")
        print(f"   COBERTURA {cobertura}: {len(lista)} asientos, {lineas} líneas, "
              f"{destino.stat().st_size/1e6:.2f} MB -> {destino.name}\n")

    print("listo. swagger guardado:", (RAW / "swagger.json").exists())


if __name__ == "__main__":
    main()
