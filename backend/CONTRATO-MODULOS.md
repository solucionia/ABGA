# Contrato de los módulos de informe — backend ABGA

Documento de trabajo para quien implemente un módulo nuevo. Se lee junto a `app/ledger.py`,
`app/informes.py` y `app/modulos/pyg.py` (este último es el ejemplo de referencia).

## Estructura del backend

```
backend/app/
├── config.py      # .env, credenciales, TTL, ritmo hacia el ERP
├── apicon.py      # cliente del ERP: token cacheado, paginación, reintentos 429
├── cache.py       # SQLite: apuntes por (empresa, ejercicio), tokens, usuarios, ejecuciones
├── ledger.py      # primitivas contables: Linea, saldos, prefijos, series
├── informes.py    # maquetación HTML obligatoria + gráficas SVG
├── modulos/       # un fichero por informe: pyg, fiscal, memoria, …
└── servicio.py    # orquesta: coge años → calcula → pinta → registra la ejecución
```

## Contrato de un módulo

Cada `app/modulos/<nombre>.py` exporta:

| Elemento | Obligatorio | Qué es |
|---|---|---|
| `NOMBRE` | sí | identificador del portal: `pyg`, `autodespro`, `proyecciones`, `fiscal`, `conciliacion`, `duplicados`, `memoria` |
| `TITULO` | sí | título humano |
| `INTERNO` | sí | `True` sólo para `conciliacion` y `duplicados` |
| `DESPLAZAMIENTOS` | sí | ejercicios que necesita respecto al pedido: `[0]`, `[0,-1]`, `[0,-1,-2,-3,-4]` |
| `PARAMETROS` | no | parámetros extra con su valor por defecto (`{"trimestre": None, "email": ""}`) |
| `calcular(por_anio, ctx)` | sí | devuelve un dict con **números** (no texto formateado) |
| `informe_html(datos, ctx)` | sí | devuelve el HTML del informe |
| `metricas_dashboard(datos)` | no | diccionario de KPIs para el panel |

- `por_anio`: `{ejercicio: list[Linea]}` con las líneas ya cargadas y cacheadas.
- `ctx`: `{"empresa", "cod_empresa", "year", "year_anterior", "nombre_mes", "trimestre", "email", …}`
  más los `PARAMETROS` resueltos.
- El módulo **no** llama al ERP ni a la caché. Nunca usa `print`; deja los avisos en `datos["avisos"]`
  (lista de strings) para que el informe los muestre.

## Primutivas disponibles (`app/ledger.py`)

```python
lineas_de_asientos(asientos)            # asientos del ERP -> list[Linea]
Linea.cuenta / .debe / .haber / .fecha / .documento / .serie / .descripcion
Linea.tercero / .contrapartida / .linea_n / .punteo_cuenta / .punteo_bancario / .importe
saldos_por_cuenta(lineas)               # {cuenta: Saldo(debe, haber, n)}
Saldo.deudor  # debe-haber      Saldo.acreedor  # haber-debe
suma_deudor(saldos, prefijos, recortar=False)   # Σ(debe-haber) por prefijo PGC
suma_acreedor(saldos, prefijos, recortar=False) # Σ(haber-debe) por prefijo PGC
por_mes(lineas) / por_trimestre(lineas) / mes_de(fecha) / anio_de(fecha) / trimestre_de(fecha)
serie_mensual(lineas, prefijos_ingreso, prefijos_gasto)     # 12 filas para gráficas
agrupar_por_cuenta(lineas, nivel=3)     # desglose por prefijo de cuenta
por_tercero(lineas, prefijos)           # saldos por tercero
comprobar_cuadre(lineas)                # ΣDebe vs ΣHaber
fecha_a_int(v) / a_float(v)
fmt(n) -> "12.345,67 €" | num(n) -> "12.345,67" | fmt_pct(n) -> "12,3%"
```

Regla de signos: activo y gasto → `suma_deudor`; pasivo e ingreso → `suma_acreedor`.
Nunca recortar a cero salvo que el informe original lo hiciera a propósito; si un agregado
sale con el signo contrario, eso es información, no ruido.

## Maquetación obligatoria (`app/informes.py`)

```python
inf.envoltura(titulo=…, subtitulo=…, cuerpo=…, interno=bool, empresa=…, ejercicio=…,
              meta={"Clave": "valor"}, extra_pie="")
inf.seccion(titulo, cuerpo, nota="")
inf.tabla(cabeceras, filas, totales=[…], anchos=["40%","30%"], alinear="right")
inf.kpis([("Etiqueta", valor_ya_formateado), …], columnas=4)
inf.importe(n, con_signo=False)   # colorea y formatea en es-ES; devuelve HTML
inf.aviso(texto, tipo="alerta"|"error"|"ok"|"info", titulo="")
inf.barras_svg(categorias, series, alto=190, titulo="")   # series=[{"nombre","color","valores"}]
inf.lineas_svg(categorias, series, titulo="")
inf.barra_pct(65.3, etiqueta="…", color="#1a4b8c")
```

Normas que no se negocian: el HTML de `informe_html` **debe empezar por `<div`** (lo pinta el
portal con `dangerouslySetInnerHTML`), sin markdown ni bloques de código; CSS inline; Arial 13px
(11px la Memoria); ancho 780px (800 la Memoria); cabeceras `#1a4b8c` sobre blanco; negativos
`#c62828`; positivos `#2e7d32`; filas alternas `#fff`/`#f9fbff`; importes es-ES. El pie lo pone
`envoltura` (contacto de ABGA en los de cliente, `[USO INTERNO]` en los internos).

## Datos reales para probar

```
fixtures/apuntes_6091_2025.json     # empresa 6091 (MB Dommo), ejercicio 2025, 1.462 asientos
fixtures/apuntes_6091_2024.json     # ejercicio 2024, 2.042 asientos
```

Formato: `{"empresa": "6091", "year": 2025, "asientos": [ {Fecha, Serie, Documento, Detalles:[…]}, … ]}`.

Para calcular sin tocar el ERP:

```python
import json, sys
sys.path.insert(0, "backend")
from app.ledger import lineas_de_asientos
from app import modulos
asientos = json.load(open("fixtures/apuntes_6091_2025.json"))["asientos"]
lineas = lineas_de_asientos(asientos)
ctx = {"empresa": "MB Dommo, S.L.", "cod_empresa": "6091", "year": 2025, "year_anterior": 2024,
       "nombre_mes": "septiembre", "trimestre": 3, "email": ""}
m = modulos.obtener("pyg")
datos = m.calcular({2025: lineas, 2024: lineas}, ctx)
html = m.informe_html(datos, ctx)
```

## Cosas que ya sabemos del ERP (no volver a investigarlas)

- Token: `POST /token` (form-urlencoded) → `access_token`, vive ~14 días. Cacheado.
- Datos: `GET /api/apuntes/?$filter=Ejercicio eq '2025'&$top=200&$skip=N`.
  - `$top` = tamaño de página, **máximo real 200**.
  - `$skip` = **número de página** (1-indexado), no desplazamiento de filas.
  - La envoltura trae `ResultadosTotales`, `PaginaActual`, `ElementosEnPagina`.
  - La enumeración va ordenada por fecha y **se reinicia** al pasarse del final.
- No existen endpoints agregados: `/api/balance`, `/api/mayores`, `/api/cuentas` → 404.
- El ERP responde **429** si se le piden muchas cosas seguidas: el cliente ya espacia las
  peticiones y reintenta con espera creciente.
- `Fecha` es un entero `YYYYMMDD` (en el filtro también: `Fecha ge 20250101`).
