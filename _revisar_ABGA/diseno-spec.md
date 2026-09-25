# Sistema de diseño · Portal ABGA Consultores

> Extraído del artefacto de maqueta `Portal ABGA.dc.html` (Claude Design). Valores copiados literalmente del HTML/disposiciones originales. Se **ignora** el runtime (`support.js`, directivas `<sc-if>`, bindings `{{ }}`) y todo lo relativo a datos (RNG, empresa de muestra «Bodegas Vega Alta», ejercicio 2022, usuario «Carlos Vega · Cliente»). Esto es la **piel** del portal.

---

## 1. Tokens de color

### Fondo y superficies
| Rol | Valor |
|---|---|
| Fondo de página | `#f4f7fc` |
| Superficie (tarjetas) | `#ffffff` |
| Fondo sutil (tablas, zebra impar) | `#f9fbff` |
| Tinte de superficie (cabeceras de tabla, legendas activas) | `#e8f0fb` |

### Texto
| Rol | Valor |
|---|---|
| Texto principal | `#112233` |
| Texto suave (etiquetas, secundario, metadatos) | `#5b6b80` |
| Texto de cabecera / tab activa / marcas | `#0c3a6e` |
| Link/acento tenue sobre las gráficas (línea secundaria) | `#9fb3c8` |

### Bordes y líneas
| Rol | Valor |
|---|---|
| Borde (inputs, tarjetas, tablas) | `#d7e0ee` |
| Línea de rejilla de gráficas | `#e7edf6` |

### Acento (marca) y navegación
| Rol | Valor |
|---|---|
| Acento principal (botones, enlaces, tab activa, foco) | `#185FA5` |
| Acento oscuro (hover de botón/enlace) | `#123d6e` |
| Acento foco (outline de botón principal) | `#1a4b8c` |
| Navegación / cabecera / fondo de login | `#071e3d` |

### Semánticos
| Estado | Texto | Fondo |
|---|---|---|
| OK / positivo (variaciones al alza) | `#2e7d32` | `#e8f5e9` |
| Error / negativo (variaciones a la baja) | `#c62828` | `#fbeaea` |
| Aviso / ámbar (liquidez, advertencias) | `#b26a00` | `#fdf0e0` |
| Info / en curso (punto de aviso, caché, progreso) | `#185FA5` | — |

> Color de **variación en KPI**: verde `#2e7d32` si `>=0`, rojo `#c62828` si `<0`. La liquidez usa ámbar `#b26a00` en un rango intermedio.
> Puntos de la tarjeta de **avisos**: info `#185FA5`, ámbar `#b26a00`.
> **Chip de módulo**: interno acento `#071e3d` con texto blanco; cliente `#e8f0fb` con texto `#0c3a6e`.

---

## 2. Tipografía y jerarquía

- **Familia:** `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` · `font-variant-numeric: tabular-nums`.
- **Base del método (body):** 14px, color `#112233`, fondo `#f4f7fc`.

| Elemento | Tamaño | Peso | Detalle |
|---|---|---|---|
| Marca «ABGA Consultores» (cabecera) | 15px | 700 | `letter-spacing:.02em`, sobre `#071e3d` |
| Subtítulo «Portal financiero» | 13px | normal | opacidad `.85` |
| Separador punto «·» | — | — | opacidad `.4` |
| Nombre/rol usuario (`Carlos Vega · Cliente`) | 13px | normal | en cabecera |
| Kickert login «ABGA Consultores» | 12px | 600/700 | mayúsculas, `letter-spacing:.08em`, `#5b6b80` |
| Título login «Portal financiero» | 20px | 700 | `#112233` |
| Etiquetas de formulario | 12–13px | 600 | `#5b6b80`, margen inferior 4-6px |
| Título de tarjeta de gráfica / sección (`h3`) | 14px | 700 | `#112233` |
| Etiqueta KPI | 11px | 600 | mayúsculas, `letter-spacing:.04em`, `#5b6b80` |
| Valor KPI | 22px | 700 | `#112233` |
| Variación KPI | 12px | 600 | verde/rojo según signo |
| Título de módulo (`h3`) | 15px | 700 | `#112233` |
| Descripción de módulo | 13px | normal | `#5b6b80`, `line-height:1.4` |
| Visor de informe (`h2`) | 18px | 700 | `#112233` |
| Marca del informe (captions) | 11px | 600 | mayúsculas, `letter-spacing:.06em`, `#5b6b80` |
| Tabla de gráfica | 12px | 400 | celdas `6px 8px` |
| Tabla de datos | 13px | 400 | celdas `7-8px 10px` |

---

## 3. Radios, sombras, espacios y densidad

### Radios
- `--radio-card` **6px** — tarjetas KPI y tarjetas de módulo.
- `--radio-control` **4px** — inputs, selects, botones, tarjetas de panel/contendores de gráficas, tabla contenedor, barras de aviso.
- `--radio-chip` **3px** — chips/badges (tipo de módulo, estado, ejercicios, parámetros).
- Puntos de aviso: `50%` (6px de diámetro).

### Sombras
- Tarjeta base: `0 1px 3px rgba(7,30,61,0.06)`.
- Tarjeta en hover: `0 6px 16px rgba(7,30,61,0.10)` (y `translateY(-2px)`).
- Tarjeta de login: `0 20px 60px rgba(7,30,61,0.35)`.
- `#e8f0fb` en hover de leyendas/botones de gráfica (`background:#e8f0fb`).

### Espaciado
- Cabecera: `min-height:56px`, padding `0 24px`, `flex` con `gap`.
- Contenedor: `max-width:1400px`, `margin:0 auto`, padding `20px 24px 56px`.
- Selectores Empresa/Ejercicio: fila `flex` con `gap:16px`, `align-items:flex-end`.
- Rejillas: KPI `gap:12px`; gráficas `gap:16px`; módulos `gap:14px`.
- Paddings de tarjeta: KPI `16px`; gráficas/paneles `16px`; visor de informe `20px`.
- `margin-bottom` de secciones: `16px` (avisos, tarjetas, tablas).

### Densidad (responsive)
- **Breakpoints:** móvil `<980px`, tablet `980–1299px`, escritorio `>=1300px`.
- **KPIs** `grid-template-columns`: 1 col (móvil) / 2 col (tablet) / 4 col (escritorio).
- **Gráficas** (`chartGridCols`): 1 col (móvil) / 2 col en adelante.
- **Módulos** (`modulosGridCols`): 1 col (móvil) / 2 col (tablet) / 3 col (escritorio).
- Cabecera con `flex-wrap` para apilar en móvil.

---

## 4. Componentes

### Barra superior
- Fondo `#071e3d`, texto blanco, `min-height:56px`, `padding:0 24px`, `flex` `space-between`, `flex-wrap:wrap`, `gap:8px`.
- Izquierda: marca **«ABGA Consultores»** (15px, 700) + punto `·` + subtítulo **«Portal financiero»** (13px, opacidad `.85`).
- Derecha: `usuario.nombre · rol` (13px) + botón **«Salir»**: transparente, `border:1px solid rgba(255,255,255,.35)`, `border-radius:4px`, `min-height:36px`, `padding:0 14px`; hover `background:rgba(255,255,255,0.1)`.

### Pestañas (Panel / Informes / Interno ABGA)
- Contenedor `background:#fff`, `border-bottom:1px solid #d7e0ee`, `padding:0 24px`, `display:flex`, `gap:4px`, scroll horizontal.
- Pestaña: `min-height:44px`, `padding:0 16px`, `background:transparent`, `border:none`, `border-bottom:2px solid`, `font-size:14px`, `font-weight:600`, cursor pointer, transición de borde/color `.2s ease`.
- **Activa:** `border-bottom-color:#185FA5`, color `#0c3a6e`. **Inactiva:** borde transparente, color `#5b6b80`. Hover text `#123d6e`.

### Selectores Empresa / Ejercicio
- Etiqueta arriba (12px, `#5b6b80`), `select` debajo: `min-height:44px`, `border:1px solid #d7e0ee`, `border-radius:4px`, `font-size:14px`, `background:#fff`, foco `outline:2px solid #185FA5`. Anchura mínima Empresa `240px`, Ejercicio `120px`.

### Tarjeta de avisos
- `background:#fff`, `border:1px solid #d7e0ee`, `border-radius:4px`, `padding:10px 16px`, `margin-bottom:16px`.
- Cada aviso: `flex` `baseline`, `gap:8px`, `font-size:13px`, `color:#112233`, `padding:4px 0`. Punto: `width:6px;height:6px;border-radius:50%`, azul `#185FA5` o ámbar `#b26a00`.

### Tarjetas KPI
- `background:#fff`, `border:1px solid #d7e0ee`, `border-radius:6px`, `padding:16px`, `box-shadow:0 1px 3px rgba(7,30,61,0.06)`, animación entrada `fadeInUp`, transición transform/sombra `.2s ease`.
- Hover: `translateY(-2px)` + sombra `0 6px 16px rgba(7,30,61,0.10)`.
- Estructura: etiqueta (11px mayúsculas `#5b6b80`) → valor (22px 700) → variación (12px 600, verde/rojo).

### Contenedores de gráficas
- `background:#fff`, `border:1px solid #d7e0ee`, `border-radius:4px`, `padding:16px`, `margin-bottom:16px`.
- Cabecera: `flex` `space-between`, título `h3` 14px 700 + leyenda.
- Leyenda: `12px`, `#5b6b80`, swatch `10x10px`, `border-radius:2px`, `margin-left:14px`.
- Botón «Ver datos»: `min-height:30px`, `padding:0 10px`, `background:#f4f7fc`, `border:1px solid #d7e0ee`, `border-radius:4px`, `font-size:11px`, `color:#0c3a6e`, volumen `margin-left:8px`, hover `#e8f0fb`.
- Panel de datos (expandido): contenedor `overflow-x:auto`, `background:#f9fbff`, `border-radius:4px`.

### Tablas
- **Tabla de gráfica (datos expandidos):** `12px`, `border-collapse:collapse`, `width:100%`. `th`: `padding:6px 8px`, `background:#e8f0fb`, `color:#0c3a6e` (a menudo mayúsculas). `td`: `padding:6px 8px`, `border-bottom:1px solid #d7e0ee`, alineación numérica `right`.
- **Tabla de datos general** (terceros, cierre, ejecuciones, caché, usuarios, empresas): `13px`. `th`: `padding:8px 10px`, `background:#e8f0fb`, `color:#0c3a6e`, `white-space:nowrap`, cursiva de orden en cabeceras. `td`: `padding:7px 10px`, `border-bottom:1px solid #d7e0ee`, numéricas `right`.
- **Zebra:** fila impar `#f9fbff`, par `#ffffff`.
- **Chip de estado** en celdas: `font-size:11px`, `font-weight:600`, `padding:2px 8px`, `border-radius:3px`, con fondo/texto semánticos.

### Tarjetas de módulos (Informes)
- `background:#fff`, `border:1px solid #d7e0ee`, `border-radius:6px`, `padding:16px`, `cursor:pointer`, `display:flex`, `flex-direction:column`, `gap:10px`, `role="button"`.
- Hover: `border-color:#185FA5`, sombra `0 6px 16px rgba(7,30,61,0.10)`, `translateY(-2px)`.
- Chip de tipo (11px 600, `padding:3px 8px`, `border-radius:3px`), título `h3` 15px, descripción 13px `#5b6b80`, chips de metadatos (11px, `#5b6b80`, `background:#f4f7fc`, `border:1px solid #d7e0ee`, `border-radius:3px`).

### Visor de informe
- `background:#fff`, `border:1px solid #d7e0ee`, `border-radius:4px`, `padding:20px`.
- Cabecera: `flex` `space-between`, `border-bottom:1px solid #d7e0ee`, `padding-bottom:14px`, `margin-bottom:14px`. Chip de tipo + `h2` 18px. Botones: **Actualizar** (principal), **Imprimir** y **Cerrar** (secundarios).
- Parámetros: `flex` `gap:16px`, etiqueta 12px `#5b6b80`, `select`/`input` `min-height:40px`, `min-width:160-200px`, `border:1px solid #d7e0ee`, `border-radius:4px`, `font-size:13px`, foco `outline:2px solid #185FA5`.
- Loading (spinner): `28x28px` círculo, `border:3px solid #d7e0ee`, `border-top-color:#185FA5`, animación `spin .8s linear infinite`, texto `#5b6b80`.

### Botones
- **Principal:** `background:#185FA5`, texto blanco, `border:none`, `border-radius:4px`, `font-weight:600`, `min-height:40px` (login 44px), `padding:0 14-16px`; hover `background:#123d6e`; foco `outline:2px solid #1a4b8c; outline-offset:2px`.
- **Secundario:** `background:#fff`, `border:1px solid #d7e0ee`, `border-radius:4px`, `font-size:13px`, `min-height:36-40px`, `padding:0 14px`; hover `background:#f4f7fc`.
- **De gráfica / compacto:** ver Contenedores de gráficas.

### Formularios
- **Login:** tarjeta centrada — `max-width:400px`, `background:#fff`, `border-radius:6px`, `padding:40px 36px`, sombra `0 20px 60px rgba(7,30,61,0.35)`, sobre fondo `#071e3d` (`min-height:100vh`, `flex` centrado).
  - Kickert «ABGA Consultores» (12px mayúsculas `#5b6b80`), `h1` «Portal financiero» 20px.
  - Inputs: `min-height:44px`, `padding:0 12px`, `border:1px solid #d7e0ee`, `border-radius:4px`, `font-size:14px`, foco `outline:2px solid #185FA5; outline-offset:1px; border-color:#185FA5`.
  - Botón «Entrar» principal a ancho completo (`min-height:44px`).
  - Aviso: `margin:20px 0 0`, `font-size:12px`, `#5b6b80`.
  - Separador + «Modo de demostración» (11px mayúsculas `#5b6b80`) con dos botones de selector de rol («Cliente», «Interno ABGA»): activo `background:#185FA5` texto blanco; inactivo `background:#fff` texto `#0c3a6e`; `border:1px solid #185FA5`, `border-radius:4px`, `min-height:40px`.
- **Alta empresa / usuario (Interno):** filas `flex` `gap:8px` `flex-wrap`, `align-items:flex-end`. Etiqueta 12px `#5b6b80`; inputs/selects `min-height:40px`, `border:1px solid #d7e0ee`, `border-radius:4px`, `font-size:13px`, foco `outline:2px solid #185FA5`. Botón **Crear empresa / Crear usuario** principal.
  - Banner de éxito: `background:#e8f0fb`, `border:1px solid #185FA5`, `border-radius:4px`, `padding:10px 14px`, texto `#0c3a6e`; botón **Cerrar** pequeño con borde `#185FA5`.

### Otros detalles
- Enlaces: `a` → `#185FA5`, hover `#123d6e`; `::selection` → `background:#185FA5; color:#fff`.
- **Motion:** `fadeInUp` (`opacity:0; translateY(8px) → opacity:1; translateY(0)`), `spin`, `pulse`. Respetar `prefers-reduced-motion: reduce` → `transition-duration:0.001ms !important; animation-duration:0.001ms !important`.
- **Barras de progreso (trabajos):** pista `#e8f0fb` `height:8px` `border-radius:3px`; relleno color semántico con ancho variable, transición `width .4s ease`.
