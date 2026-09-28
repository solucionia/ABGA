"""Captura el hub con datos reales y comprueba que la capa de datos ha entrado.

Entra por la API desde la propia página (así la cookie de sesión la guarda el navegador, sin
teclear credenciales en ningún formulario), abre el hub, espera a que termine de cargar y deja una
captura. Además informa de lo que de verdad se ha pintado: los indicadores, los avisos, cuántos
registros han llegado en cada lista y qué ha dicho la consola.

    /opt/scrapling/venv/bin/python backend/scripts/captura_hub.py <cliente|interno> [pantalla] [salida]

El usuario de demostración es el del `init_db.py`; el interno lee la contraseña del `.env` y no la
imprime nunca.
"""
import asyncio
import contextlib
import glob
import json
import pathlib
import sys

from playwright.async_api import async_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[2]
CHROMIUM = sorted(glob.glob("/opt/playwright-browsers/chromium-*/chrome-linux*/chrome"))[-1]
BASE = sys.argv[4] if len(sys.argv) > 4 else "http://127.0.0.1:8011"
ROL = sys.argv[1] if len(sys.argv) > 1 else "interno"
PANTALLA = sys.argv[2] if len(sys.argv) > 2 else ""
SALIDA = sys.argv[3] if len(sys.argv) > 3 else "/tmp/abga_hub.png"


def credenciales(rol: str) -> tuple[str, str]:
    if rol == "cliente":
        return "cliente@mbdommo.com", "demo2025"
    env = dict(linea.split("=", 1) for linea in (RAIZ / ".env").read_text().splitlines()
               if "=" in linea and not linea.startswith("#"))
    return "admin@abgaconsultores.com", env["ADMIN_BOOTSTRAP_PASSWORD"].strip()


async def main() -> None:
    email, clave = credenciales(ROL)
    async with async_playwright() as p:
        navegador = await p.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        contexto = await navegador.new_context(viewport={"width": 1600, "height": 1100})
        pagina = await contexto.new_page()
        consola: list[str] = []
        pagina.on("console", lambda m: consola.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
        pagina.on("pageerror", lambda e: consola.append(f"[pageerror] {e}"))

        # La sesión se abre desde la propia página: la cookie (HttpOnly) la guarda el navegador.
        await pagina.goto(BASE + "/", wait_until="domcontentloaded")
        entrada = await pagina.evaluate(
            """async ([email, password]) => {
                 const r = await fetch('/api/login', {method:'POST', credentials:'same-origin',
                   headers:{'Content-Type':'application/json'},
                   body: JSON.stringify({email, password, cod_empresa:'6091'})});
                 const j = await r.json();
                 return {estado: r.status, rol: j.usuario && j.usuario.rol};
               }""", [email, clave])
        print(f"sesión {ROL}: HTTP {entrada['estado']} · rol {entrada['rol']}")

        await pagina.goto(BASE + "/hub/", wait_until="domcontentloaded")
        with contextlib.suppress(Exception):
            await pagina.wait_for_function("() => !document.getElementById('abga-aviso')", timeout=180000)
        if PANTALLA:
            with contextlib.suppress(Exception):
                await pagina.get_by_text(PANTALLA, exact=False).first.click()
                await pagina.wait_for_timeout(1200)
                with contextlib.suppress(Exception):
                    await pagina.wait_for_function("() => !document.getElementById('abga-aviso')", timeout=180000)
        await pagina.wait_for_timeout(2500)
        await pagina.screenshot(path=SALIDA, full_page=True)

        datos = await pagina.evaluate(
            """() => {
                 const m = window.ABGA && window.ABGA.datos();
                 const t = s => (document.body.innerText.match(s) || [''])[0];
                 const aviso = document.getElementById('abga-aviso');
                 return {
                   listo: window.ABGA ? window.ABGA.estado.listo : false,
                   usuario: window.ABGA ? window.ABGA.estado.usuario && window.ABGA.estado.usuario.email : null,
                   interno: window.ABGA ? window.ABGA.estado.interno : null,
                   ejercicio: window.ABGA ? window.ABGA.estado.ejercicio : null,
                   empresas: window.ABGA ? window.ABGA.estado.empresas.length : 0,
                   empresa: window.ABGA ? window.ABGA.estado.empresa : null,
                   ttl: window.ABGA ? window.ABGA.estado.ttl : null,
                   cacheDeLaEmpresa: window.ABGA ? window.ABGA.estado.cache[window.ABGA.estado.empresa] : null,
                   tamanos: m ? Object.fromEntries(Object.entries(m).map(([k, v]) => [k, Array.isArray(v) ? v.length : (v && typeof v === 'object' ? Object.keys(v).length : String(v))])) : null,
                   kpis: [...document.querySelectorAll('*')].filter(e => e.children.length === 0 && /^\\d/.test(e.textContent || '') && (e.textContent || '').length < 14).slice(0, 12).map(e => e.textContent.trim()),
                   avisoPendiente: aviso ? aviso.textContent : null,
                   titulo: document.title
                 };
               }""")
        print(json.dumps(datos, ensure_ascii=False)[:2600])
        print("\nconsola:", *consola[-14:], sep="\n  ")
        print("\ncaptura:", SALIDA)
        await navegador.close()


asyncio.run(main())
