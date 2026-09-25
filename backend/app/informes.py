"""Maquetación de los informes.

Convenciones obligatorias del cliente (heredadas del sistema anterior, no negociables):
HTML puro empezando por `<div`, sin markdown ni bloques de código, CSS inline, Arial 13px
(11px en la Memoria), max-width 780px (800 en la Memoria), importes es-ES, cabeceras
`#1a4b8c` con texto blanco, negativos `#c62828`, positivos `#2e7d32`, filas alternas
`#fff`/`#f9fbff`.

Además se incorporan gráficas SVG en línea (sin JavaScript ni librerías) para que los
informes sean visuales también al imprimirlos.
"""
from __future__ import annotations

import html
from typing import Any, Iterable, Sequence

AZUL = "#1a4b8c"
AZUL_CLARO = "#e8f0fb"
NEGRO = "#123"
GRIS = "#f9fbff"
POSITIVO = "#2e7d32"
NEGATIVO = "#c62828"
AMBAR = "#b26a00"
BORDE = "#d7e0ee"

# reexportados desde ledger para que los módulos tengan un único punto de importación
from .ledger import fmt, fmt_pct, num  # noqa: E402,F401  (isort: skip)

ANCHO_CLIENTE = 780
ANCHO_MEMORIA = 800
FUENTE_CLIENTE = "13px"
FUENTE_MEMORIA = "11px"

PIE_CLIENTE = ("ABGA Consultores · farias@abgaconsultores.com · 913 788 740 · "
               "Calle Saturnino Calleja 6, 1ºC · 28002 Madrid")
PIE_INTERNO = "Generado automáticamente — Solo uso interno ABGA Consultores"


def esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def importe(n: Any, *, con_signo: bool = False, moneda: bool = True) -> str:
    """Importe es-ES con color: rojo si negativo, verde si positivo."""
    from .ledger import fmt

    if isinstance(n, bool) or not isinstance(n, (int, float)):
        return f'<span style="color:#666">{fmt(n)}</span>'
    color = NEGATIVO if n < 0 else (POSITIVO if n > 0 else "#333")
    texto = f"{n:+,.2f}" if con_signo else f"{n:,.2f}"
    texto = texto.replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".")
    if moneda:
        texto += " €"
    return f'<span style="color:{color};white-space:nowrap">{texto}</span>'


def color_num(n: Any) -> str:
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        return "#666"
    return NEGATIVO if n < 0 else (POSITIVO if n > 0 else "#333")


def envoltura(*, titulo: str, cuerpo: str, subtitulo: str = "", interno: bool = False,
              empresa: str = "", ejercicio: Any = "", extra_pie: str = "",
              meta: dict[str, Any] | None = None, ancho: int | None = None,
              fuente: str | None = None) -> str:
    """Devuelve el HTML completo del informe empezando por `<div`, como exige el contrato."""
    ancho = ancho or (ANCHO_MEMORIA if interno else ANCHO_CLIENTE)
    fuente = fuente or (FUENTE_MEMORIA if interno else FUENTE_CLIENTE)
    etiqueta = ('<span style="background:#c62828;color:#fff;font-size:11px;padding:2px 7px;'
                'border-radius:3px;letter-spacing:.6px;vertical-align:middle">[USO INTERNO]</span> '
                ) if interno else ""
    pie = PIE_INTERNO if interno else PIE_CLIENTE
    meta = meta or {}
    piezas_meta = []
    if empresa:
        piezas_meta.append(esc(empresa))
    if ejercicio:
        piezas_meta.append(f"Ejercicio {esc(ejercicio)}")
    for k, v in meta.items():
        piezas_meta.append(f"{esc(k)}: {esc(v)}")

    return (
        f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:{fuente};color:{NEGRO};'
        f'line-height:1.5;max-width:{ancho}px;margin:0 auto;background:#fff">'
        f'<div style="background:{AZUL};color:#fff;padding:14px 18px;border-radius:5px 5px 0 0">'
        f'<div style="font-size:17px;font-weight:bold;letter-spacing:.2px">{etiqueta}{esc(titulo)}</div>'
        + (f'<div style="font-size:12px;opacity:.92;margin-top:3px">{esc(subtitulo)}</div>' if subtitulo else "")
        + (f'<div style="font-size:11px;opacity:.85;margin-top:5px">{" · ".join(piezas_meta)}</div>'
           if piezas_meta else "")
        + '</div>'
        f'<div style="border:1px solid {BORDE};border-top:none;padding:16px 18px;border-radius:0 0 5px 5px">'
        f'{cuerpo}'
        f'</div>'
        f'<div style="text-align:center;font-size:11px;color:#5b6b80;padding:9px 0 2px">{esc(pie)}'
        + (f'<br>{esc(extra_pie)}' if extra_pie else "")
        + '</div></div>'
    )


def seccion(titulo: str, cuerpo: str, *, nota: str = "") -> str:
    return (
        f'<div style="margin:16px 0 6px"><div style="background:{AZUL_CLARO};border-left:4px solid {AZUL};'
        f'padding:7px 11px;font-weight:bold;color:{AZUL};font-size:13px">{esc(titulo)}</div>'
        + (f'<div style="font-size:11px;color:#5b6b80;padding:4px 11px 0">{esc(nota)}</div>' if nota else "")
        + f'</div>{cuerpo}'
    )


def tabla(cabeceras: Sequence[str], filas: Iterable[Sequence[Any]], *, alinear: str = "right",
          totales: Sequence[Any] | None = None, anchos: Sequence[str] | None = None,
          primera_izquierda: bool = True) -> str:
    """Tabla con filas alternas y totales opcionales. Las celdas admiten HTML ya formateado."""
    anchos = anchos or []
    th = "".join(
        f'<th style="padding:6px 8px;border-bottom:2px solid {AZUL};background:#fff;color:{AZUL};'
        f'font-size:12px;text-align:{("left" if (i == 0 and primera_izquierda) else alinear)}'
        + (f';width:{anchos[i]}' if i < len(anchos) else "")
        + f'">{esc(c)}</th>'
        for i, c in enumerate(cabeceras)
    )
    cuerpo = []
    for i, fila in enumerate(filas):
        fondo = "#fff" if i % 2 == 0 else GRIS
        celdas = "".join(
            f'<td style="padding:5px 8px;border-bottom:1px solid #eef2f8;background:{fondo};'
            f'text-align:{("left" if (j == 0 and primera_izquierda) else alinear) if alinear else "left"};'
            f'{"" if i == 0 and primera_izquierda else ""}">'
            + (str(v) if isinstance(v, str) and v.startswith("<") else esc(v))
            + '</td>'
            for j, v in enumerate(fila)
        )
        cuerpo.append(f"<tr>{celdas}</tr>")
    if totales is not None:
        celdas = "".join(
            f'<td style="padding:6px 8px;border-top:2px solid {AZUL};background:{AZUL_CLARO};'
            f'font-weight:bold;text-align:{("left" if (j == 0 and primera_izquierda) else alinear)}">'
            + (str(v) if isinstance(v, str) and v.startswith("<") else esc(v))
            + '</td>'
            for j, v in enumerate(totales)
        )
        cuerpo.append(f"<tr>{celdas}</tr>")
    return (f'<table style="width:100%;border-collapse:collapse;margin:4px 0 2px;'
            f'font-size:12px"><thead><tr>{th}</tr></thead><tbody>{"".join(cuerpo)}</tbody></table>')


def kpis(items: Sequence[tuple[str, str]], *, columnas: int = 4) -> str:
    """Rejilla de tarjetas KPI. `items` = [(etiqueta, valor_ya_formateado_o_html)]."""
    ancho = f"{100 / max(1, columnas):.4f}%"
    filas: list[str] = []
    pendientes: list[str] = []
    for et, v in items:
        pendientes.append(
            f'<td style="width:{ancho};padding:4px;vertical-align:top">'
            f'<div style="border:1px solid {BORDE};border-left:4px solid {AZUL};border-radius:4px;'
            f'padding:9px 11px;background:#fff">'
            f'<div style="font-size:10.5px;color:#5b6b80;text-transform:uppercase;letter-spacing:.4px">{esc(et)}</div>'
            f'<div style="font-size:16px;font-weight:bold;color:{NEGRO};margin-top:3px">'
            + (v if isinstance(v, str) and v.startswith("<") else esc(v))
            + '</div></div></td>'
        )
        if len(pendientes) == columnas:
            filas.append(f"<tr>{''.join(pendientes)}</tr>")
            pendientes = []
    if pendientes:
        filas.append(f"<tr>{''.join(pendientes)}</tr>")
    return f'<table style="width:100%;border-collapse:separate;border-spacing:0;margin:6px 0">{"".join(filas)}</table>'


def aviso(texto: str, *, tipo: str = "info", titulo: str = "") -> str:
    colores = {"info": (AZUL_CLARO, AZUL), "alerta": ("#fff4e5", AMBAR), "error": ("#fdecea", NEGATIVO),
               "ok": ("#e9f6ec", POSITIVO)}
    fondo, borde = colores.get(tipo, colores["info"])
    return (f'<div style="background:{fondo};border-left:4px solid {borde};padding:8px 11px;'
            f'border-radius:3px;margin:8px 0;font-size:12px">'
            + (f'<b style="color:{borde}">{esc(titulo)}</b><br>' if titulo else "")
            + f'{esc(texto)}</div>')


def barras_svg(categorias: Sequence[str], series: Sequence[dict[str, Any]], *,
               alto: int = 190, ancho: int = 700, formato=None, titulo: str = "") -> str:
    """Gráfico de barras agrupadas en SVG en línea.

    series = [{"nombre": "Ingresos", "color": "#1a4b8c", "valores": [...], "formato": "importe"}, ...]
    """
    n = len(categorias)
    if not n or not series:
        return ""
    margen_izq, margen_der, margen_sup, margen_inf = 6, 6, 22, 30
    ancho_util = ancho - margen_izq - margen_der
    alto_util = alto - margen_sup - margen_inf
    maximo = max([0.0] + [abs(v) for s in series for v in s.get("valores", [])])
    if maximo <= 0:
        maximo = 1.0
    ancho_grupo = ancho_util / n
    ancho_barra = max(3.0, (ancho_grupo * 0.66) / len(series))
    partes = [f'<svg viewBox="0 0 {ancho} {alto}" width="100%" height="{alto}" '
              f'style="display:block;overflow:visible" role="img" aria-label="{esc(titulo or "gráfico")}">']
    for i in range(5):
        y = margen_sup + alto_util * i / 4
        partes.append(f'<line x1="{margen_izq}" y1="{y:.1f}" x2="{ancho - margen_der}" y2="{y:.1f}" '
                      f'stroke="#eef2f8" stroke-width="1"/>')
    for ci, cat in enumerate(categorias):
        x0 = margen_izq + ci * ancho_grupo + (ancho_grupo - ancho_barra * len(series)) / 2
        for si, s in enumerate(series):
            v = s.get("valores", [])[ci] if ci < len(s.get("valores", [])) else 0
            h = abs(float(v)) / maximo * alto_util
            x = x0 + si * ancho_barra
            y = margen_sup + alto_util - h
            color = s.get("color", AZUL)
            partes.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(1.0, ancho_barra - 1.5):.1f}" '
                          f'height="{max(0.0, h):.1f}" fill="{color}" rx="1.5"><title>{esc(cat)} · '
                          f'{esc(s.get("nombre", ""))}: {esc(formato(v) if formato else f"{v:,.2f}")}</title></rect>')
        partes.append(f'<text x="{margen_izq + ci * ancho_grupo + ancho_grupo / 2:.1f}" '
                      f'y="{alto - 10}" font-size="10.5" fill="#5b6b80" text-anchor="middle" '
                      f'font-family="Arial,Helvetica,sans-serif">{esc(cat)}</text>')
    leyenda_x = margen_izq
    for s in series:
        partes.append(f'<rect x="{leyenda_x}" y="{margen_sup - 16}" width="9" height="9" '
                      f'fill="{s.get("color", AZUL)}" rx="1.5"/>')
        partes.append(f'<text x="{leyenda_x + 13}" y="{margen_sup - 7.5}" font-size="11" fill="#3c4a5c" '
                      f'font-family="Arial,Helvetica,sans-serif">{esc(s.get("nombre", ""))}</text>')
        leyenda_x += 30 + 6.2 * len(str(s.get("nombre", "")))
    partes.append("</svg>")
    return "".join(partes)


def lineas_svg(categorias: Sequence[str], series: Sequence[dict[str, Any]], *,
               alto: int = 190, ancho: int = 700, titulo: str = "") -> str:
    """Evolución en líneas con puntos, en SVG (para comparativas interanuales)."""
    n = len(categorias)
    if n < 2 or not series:
        return ""
    margen_izq, margen_der, margen_sup, margen_inf = 8, 8, 22, 28
    ancho_util = ancho - margen_izq - margen_der
    alto_util = alto - margen_sup - margen_inf
    valores = [float(v) for s in series for v in s.get("valores", [])]
    maximo, minimo = max([0.0] + valores), min([0.0] + valores)
    rango = (maximo - minimo) or 1.0

    def yy(v: float) -> float:
        return margen_sup + alto_util - (float(v) - minimo) / rango * alto_util

    partes = [f'<svg viewBox="0 0 {ancho} {alto}" width="100%" height="{alto}" '
              f'style="display:block;overflow:visible" role="img" aria-label="{esc(titulo or "evolución")}">']
    if minimo < 0:
        partes.append(f'<line x1="{margen_izq}" y1="{yy(0):.1f}" x2="{ancho - margen_der}" y2="{yy(0):.1f}" '
                      f'stroke="#c9d4e4" stroke-width="1" stroke-dasharray="3,3"/>')
    for si, s in enumerate(series):
        vals = [float(v) for v in s.get("valores", [])]
        puntos = " ".join(f"{margen_izq + i * ancho_util / (n - 1):.1f},{yy(v):.1f}" for i, v in enumerate(vals))
        color = s.get("color", AZUL)
        partes.append(f'<polyline points="{puntos}" fill="none" stroke="{color}" stroke-width="2.2" '
                      f'stroke-linejoin="round"/>')
        for i, v in enumerate(vals):
            x = margen_izq + i * ancho_util / (n - 1)
            partes.append(f'<circle cx="{x:.1f}" cy="{yy(v):.1f}" r="3" fill="#fff" stroke="{color}" '
                          f'stroke-width="2"><title>{esc(categorias[i])}: {v:,.2f}</title></circle>')
    for i, cat in enumerate(categorias):
        partes.append(f'<text x="{margen_izq + i * ancho_util / (n - 1):.1f}" y="{alto - 9}" font-size="10.5" '
                      f'fill="#5b6b80" text-anchor="middle" font-family="Arial,Helvetica,sans-serif">{esc(cat)}</text>')
    leyenda_x = margen_izq
    for s in series:
        partes.append(f'<rect x="{leyenda_x}" y="{margen_sup - 16}" width="9" height="9" fill="{s.get("color", AZUL)}" rx="1.5"/>')
        partes.append(f'<text x="{leyenda_x + 13}" y="{margen_sup - 7.5}" font-size="11" fill="#3c4a5c" '
                      f'font-family="Arial,Helvetica,sans-serif">{esc(s.get("nombre", ""))}</text>')
        leyenda_x += 30 + 6.2 * len(str(s.get("nombre", "")))
    partes.append("</svg>")
    return "".join(partes)


def barra_pct(pct: float, *, etiqueta: str = "", color: str = AZUL) -> str:
    pct = max(0.0, min(100.0, float(pct or 0)))
    return (f'<div style="margin:3px 0">'
            + (f'<div style="font-size:11px;color:#5b6b80">{esc(etiqueta)}</div>' if etiqueta else "")
            + f'<div style="background:#eef2f8;border-radius:3px;height:9px;overflow:hidden">'
            f'<div style="width:{pct:.1f}%;height:100%;background:{color}"></div></div>'
            f'<div style="font-size:11px;color:#5b6b80;text-align:right">{pct:.1f}%</div></div>')
