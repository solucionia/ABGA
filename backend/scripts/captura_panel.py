"""Captura el panel ABGA con datos reales, conduciendo el login por la UI.

Uso: /opt/scrapling/venv/bin/python backend/scripts/captura_panel.py
"""
import asyncio
import glob
import sys

from playwright.async_api import async_playwright

CHROMIUM = sorted(glob.glob("/opt/playwright-browsers/chromium-*/chrome-linux*/chrome"))[-1]
BASE = "http://127.0.0.1:8011"
SALIDA = sys.argv[1] if len(sys.argv) > 1 else "/tmp/abga_panel.png"


async def main() -> None:
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1440, "height": 1200})
        errores = []
        page.on("console", lambda m: errores.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: errores.append(f"[pageerror] {e}"))
        await page.goto(BASE + "/", wait_until="networkidle")

        # si el modo demo auto-entra, no hay pantalla de login visible que rellenar
        if await page.locator("#btn-entrar").is_visible():
            await page.fill("#login-email", "cliente@mbdommo.com")
            await page.fill("#login-password", "demo2025")
            await page.click("#btn-entrar")

        # espera el panel
        try:
            await page.wait_for_selector("#kpi-grid .kpi", timeout=90000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)
        await page.screenshot(path=SALIDA, full_page=True)

        n_kpi = await page.locator("#kpi-grid .kpi").count()
        n_svg = await page.locator(".grafica rect, .grafica polyline").count()
        titulo = await page.locator("#cabecera-usuario").text_content()
        print(f"KPIs renderizados: {n_kpi}")
        print(f"Elementos de gráfica (rect/polyline): {n_svg}")
        print(f"Usuario: {titulo}")
        print(f"Consola (errores/avisos): {len(errores)}")
        for e in errores[:8]:
            print("   ", e)
        print(f"Captura: {SALIDA}")
        await b.close()


asyncio.run(main())
