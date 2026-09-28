"""Recorre las diez pantallas del hub en el navegador y dice, pantalla a pantalla, qué pasó.

Sesión abierta una sola vez por la API desde la propia página (la cookie la guarda el navegador).
Para cada pantalla: la abre desde el menú, espera a que la capa de datos termine, guarda captura y
recoge los errores de consola, los `NaN`/`undefined` que se hayan colado en el texto y un recorte de
lo pintado. Sirve para comprobar, de una pasada, que los diez traductores están cableados.

    /opt/scrapling/venv/bin/python backend/scripts/recorrer_hub.py [cliente|interno] [base_url]
"""

import asyncio
import contextlib
import glob
import json
import pathlib
import re
import sys

from playwright.async_api import async_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[2]
CHROMIUM = sorted(glob.glob("/opt/playwright-browsers/chromium-*/chrome-linux*/chrome"))[-1]
ROL = sys.argv[1] if len(sys.argv) > 1 else "interno"
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8011"
IMAGENES = (RAIZ.parents[2] / "cache" / "images").resolve()  # profiles/abga/cache/images  # profiles/abga/cache/images

PANTALLAS = [
    "Inicio", "Envíos a clientes", "Informe financiero", "Cuentas anuales",
    "Proyecciones", "Conciliación de mayores", "Duplicados de facturas",
    "Impuestos", "Clientes", "Ajustes",
]


def credenciales(rol: str) -> tuple[str, str]:
    if rol == "cliente":
        return "cliente@mbdommo.com", "demo2025"
    env = dict(linea.split("=", 1) for linea in (RAIZ / ".env").read_text().splitlines()
               if "=" in linea and not linea.startswith("#"))
    return "admin@abgaconsultores.com", env["ADMIN_BOOTSTRAP_PASSWORD"].strip()


def recorta(texto: str, n: int = 260) -> str:
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto[:n] + ("…" if len(texto) > n else "")


async def main() -> None:
    email, clave = credenciales(ROL)
    informe = []
    async with async_playwright() as p:
        navegador = await p.chromium.launch(executable_path=CHROMIUM, headless=True,
                                            args=["--no-sandbox"])
        contexto = await navegador.new_context(viewport={"width": 1600, "height": 1100})
        pagina = await contexto.new_page()
        errores: list[str] = []
        fallos: list[str] = []
        pagina.on("console", lambda m: errores.append(f"[{m.type}] {m.text}")
                  if m.type in ("error", "warning") else None)
        pagina.on("pageerror", lambda e: errores.append(f"[pageerror] {e}"))
        # Toda petición con 4xx/5xx deja su URL: sin ella un 404 es inlocalizable.
        pagina.on("response", lambda r: fallos.append(f"{r.status} {r.url}") if r.status >= 400 else None)

        await pagina.goto(BASE + "/", wait_until="domcontentloaded")
        sesion = await pagina.evaluate(
            """async ([email, password]) => {
                 const r = await fetch('/api/login', {method:'POST', credentials:'same-origin',
                   headers:{'Content-Type':'application/json'},
                   body: JSON.stringify({email, password, cod_empresa:'6091'})});
                 const j = await r.json().catch(() => ({}));
                 return {estado: r.status, rol: j.usuario && j.usuario.rol};
               }""", [email, clave])
        informe.append(f"sesión {ROL}: HTTP {sesion['estado']} · rol {sesion['rol']}")

        await pagina.goto(BASE + "/hub/", wait_until="domcontentloaded")
        with contextlib.suppress(Exception):
            await pagina.wait_for_function("() => !document.getElementById('abga-aviso')",
                                           timeout=25000)
        await pagina.wait_for_timeout(2000)

        for i, pantalla in enumerate(PANTALLAS, 1):
            del errores[:]
            del fallos[:]
            # Clic por el PRIMER nodo de texto del elemento: «Clientes» no debe caer en
            # «Envíos a clientes» (con get_by_text en subcadena pasaba) y «Duplicados de facturas»
            # lleva su contador como nodo de texto hermano.
            abierto = await pagina.evaluate(
                r"""(nom) => {
                     const norm = s => (s || '').replace(/\s+/g, ' ').trim();
                     const cands = [...document.querySelectorAll('button, [role=button], div, span')];
                     let el = cands.find(e => {
                       const n = [...e.childNodes].find(x => x.nodeType === 3 && x.textContent.trim());
                       return n && norm(n.textContent) === nom;
                     });
                     if (!el) el = cands.find(e => norm(e.textContent) === nom);
                     if (!el) return 'no';
                     el.click();
                     return 'si';
                   }""", pantalla)
            if abierto != "si":
                informe.append(f"✗ {pantalla}: no se pudo abrir desde el menú")
                continue
            await pagina.wait_for_timeout(1000)
            with contextlib.suppress(Exception):
                await pagina.wait_for_function("() => !document.getElementById('abga-aviso')",
                                               timeout=25000)
            await pagina.wait_for_timeout(1500)

            marca = re.sub(r"[^a-z0-9]+", "-", pantalla.lower()).strip("-")
            ruta = IMAGENES / f"hub_{i:02d}_{marca}.png"
            await pagina.screenshot(path=str(ruta), full_page=True)

            estado = await pagina.evaluate(
                """() => {
                     const s = (window.ABGA && window.ABGA.estado) || {};
                     const t = document.body.innerText;
                     const m = window.ABGA && window.ABGA.datos ? window.ABGA.datos() : null;
                     const conteos = m ? Object.fromEntries(Object.entries(m)
                       .map(([k, v]) => [k, Array.isArray(v) ? v.length
                         : (v && typeof v === 'object' ? Object.keys(v).length : String(v))])) : null;
                     const hoja = [...document.querySelectorAll('style')].map(s => s.textContent).join('');
                     return {
                       pantalla: (document.querySelector('[data-screen-label].sc-screen')
                                  || document.body).innerText.split('\\n')[0] || '',
                       aviso: (document.getElementById('abga-aviso') || {}).innerText || null,
                       registros: conteos,
                       state: {tareas: (s.tareas || []).length, dups: (s.dups || []).length,
                               feed: (s.feed || []).length, infPer: !!(s.infPer || {}).length,
                               impFilas: (s.impFilas || []).length,
                               caNotas: (s.caNotas || []).length,
                               proyDatos: !!s.proyDatos, concResumen: !!s.concResumen,
                               cliFila: !!s.cliFila, ajDespacho: !!s.ajDespacho},
                       malos: (t.match(/\\bNaN\\b|undefined/g) || []).length,
                       errores: (t.match(/\\[object Object\\]|Error:/g) || []).length,
                       texto: t.slice(0, 400)
                     };
                   }""")
            mapa = {
                "pantalla": pantalla,
                "captura": str(ruta),
                "aviso": estado["aviso"],
                "state": estado["state"],
                "registros": estado["registros"],
                "NaN/undefined": estado["malos"],
                "errores_en_pantalla": estado["errores"],
                "consola": [e for e in errores if "favicon" not in e][:10],
                "peticiones_fallidas": fallos[:8],
                "texto": recorta(estado["texto"]),
            }
            informe.append(json.dumps(mapa, ensure_ascii=False))
            print(json.dumps(mapa, ensure_ascii=False), flush=True)

        await navegador.close()
    print("\n".join(informe))


if __name__ == "__main__":
    asyncio.run(main())
