"""Captura el informe `analisis` a PNG para revisarlo a ojo.

    /opt/scrapling/venv/bin/python backend/scripts/captura_analisis.py [año] [alto] [salida]

Necesita Playwright (está en el venv de scrapling, no en el del proyecto) y el Chromium
compartido de /opt/playwright-browsers.
"""
import asyncio
import glob
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import modulos  # noqa: E402
from app.ledger import lineas_de_asientos  # noqa: E402

CHROMIUM = sorted(glob.glob("/opt/playwright-browsers/chromium-*/chrome-linux*/chrome"))[-1]


def lineas(year: int):
    ruta = RAIZ / "fixtures" / f"apuntes_6091_{year}.json"
    return lineas_de_asientos(json.load(ruta.open(encoding="utf-8"))["asientos"])


async def main() -> None:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    alto = int(sys.argv[2]) if len(sys.argv) > 2 else 1750
    salida = sys.argv[3] if len(sys.argv) > 3 else f"/tmp/analisis_{year}.png"

    ctx = {"empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": year,
           "year_anterior": year - 1, "nombre_mes": "septiembre", "trimestre": 3, "email": ""}
    modulo = modulos.obtener("analisis")
    datos = modulo.calcular({year: lineas(year), year - 1: lineas(year - 1)}, ctx)
    html = modulo.informe_html(datos, ctx)
    pagina = ("<!doctype html><html lang='es'><meta charset='utf-8'>"
              "<body style='margin:0;background:#eef2f8;padding:22px'>" + html + "</body></html>")

    async with async_playwright() as p:
        navegador = await p.chromium.launch(executable_path=CHROMIUM, headless=True,
                                            args=["--no-sandbox"])
        page = await navegador.new_page(viewport={"width": 860, "height": 1400}, device_scale_factor=2)
        await page.set_content(pagina)
        await page.screenshot(path=salida, clip={"x": 0, "y": 0, "width": 860, "height": alto})
        await navegador.close()
    print(f"captura: {salida}")


if __name__ == "__main__":
    asyncio.run(main())
