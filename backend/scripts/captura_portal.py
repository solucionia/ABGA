"""Captura una pestaña del portal para revisarla a ojo.

    /opt/scrapling/venv/bin/python backend/scripts/captura_portal.py [pestana] [salida]

`pestana` es panel | informes | interno (por defecto, informes).

OJO al automatizar el portal: hay que esperar a que el panel termine de pintarse (los KPIs)
ANTES de pulsar una pestaña. Si se pulsa antes, el portal repinta el panel y revierte la
pestaña que habíamos abierto.
"""
import asyncio
import glob
import sys

from playwright.async_api import async_playwright

CHROMIUM = sorted(glob.glob("/opt/playwright-browsers/chromium-*/chrome-linux*/chrome"))[-1]
BASE = "http://127.0.0.1:8011"


async def main() -> None:
    pestana = sys.argv[1] if len(sys.argv) > 1 else "informes"
    salida = sys.argv[2] if len(sys.argv) > 2 else f"/tmp/abga_{pestana}.png"

    async with async_playwright() as p:
        navegador = await p.chromium.launch(executable_path=CHROMIUM, headless=True,
                                            args=["--no-sandbox"])
        page = await navegador.new_page(viewport={"width": 1440, "height": 1750})
        await page.goto(BASE + "/", wait_until="networkidle")
        await page.wait_for_selector("#kpi-grid .kpi", timeout=90000)   # el panel está listo
        await page.wait_for_timeout(2000)
        await page.click(f"#tab-{pestana}")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=salida, full_page=(pestana != "informes"))

        estado = await page.evaluate("""(() => [...document.querySelectorAll('.vista')]
            .map(v => `${v.id}=${getComputedStyle(v).display}`).join(' '))()""")
        print(f"vistas: {estado}")
        print(f"tarjetas: {await page.locator('#listado-modulos .modulo').count()} "
              f"· grupos: {await page.locator('#listado-modulos > div').count()}")
        print(f"captura: {salida}")
        await navegador.close()


if __name__ == "__main__":
    asyncio.run(main())
