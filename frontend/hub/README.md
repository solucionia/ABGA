# ABGA Hub · frontal de la plataforma

Es el frontal que sustituye al portal anterior (`frontend/index.html` + `frontend/app.js`), que de
momento sigue servido en la raíz. El hub se sirve en `/hub/` desde el mismo `StaticFiles` de
`app/main.py`, así que comparte origen con la API y la sesión viaja en la cookie `HttpOnly`.

## Qué hay dentro (y por qué así)

    index.html              la plantilla con las diez pantallas, los estilos y el código de la aplicación
    datos.js                la capa de datos: sesión, catálogo, caché, trabajos y avisos en pantalla
    pantallas/<nombre>.js   un traductor por pantalla: de la API a las estructuras del hub
    soporte/dc-runtime.js   el motor del frontal (evalúa la plantilla y monta React)
    soporte/react.js        React 18.3.1 y ReactDOM 18.3.1, servidos en local (no desde unpkg)
    soporte/fuentes/        las tipografías IBM Plex de la plantilla

`index.html` se conserva **tal y como se entregó**: mismo markup, mismos estilos, misma estructura de
pantallas y el código de la aplicación en la misma etiqueta `<script type="text/x-dc">`, porque el
motor lee de ahí el componente que monta. El código de la aplicación **tiene que seguir inline**: el
runtime lo evalúa del DOM y sacarlo a un fichero aparte deja la página en blanco.

## Cómo entra la plataforma en el frontal

El hub ya tenía su propio punto de hidratación (`componentDidMount`) y su propio estado
(`this.setState`), así que la capa de datos entra por ahí y no por otro sitio:

1. Al final del script de la aplicación hay un **puente** (`window.ABGA_HUB`) que entrega a
   `datos.js` los mismos objetos que usan las pantallas (`CLIENTES`, `DUPS`, `VENC`, `IMP_PYG`…) y
   envuelve `setState` para avisar de cada cambio de pantalla, empresa y ejercicio.
2. `datos.js` **sustituye el contenido de esos objetos** (mismo objeto, mismo nombre) y usa
   `setState` para el estado que la aplicación ya sabe pintar (`tareas`, `dups`, `feed`…). Ninguna
   pantalla cambia su forma de leer los datos.
3. Cada pantalla tiene su traductor en `pantallas/`, registrado con `ABGA.registrar`. Recibe un
   contexto con la API, el estado, `poner(...)` para dejar datos, `parchear(...)` para el estado de
   la aplicación y `sinDatos(...)` para declarar lo que la plataforma no sabe dar.

Regla de la casa: **no se inventa ninguna cifra**. Lo que no existe se deja vacío y se declara.

## Abrir el hub no puede despertar al ERP

Leer un ejercicio del ERP son cientos de consultas al ERP de ABGA (y el ERP limita el ritmo). Por eso
`datos.js` lee el inventario de la caché y su vida útil (`/api/cache` y `/api/salud`) al arrancar:

* abre por una empresa que **ya tenga** un ejercicio leído y sin caducar, y por ese ejercicio;
* cada traductor comprueba `ctx.hayCache()` antes de pedir informes: si el ejercicio no está leído,
  deja la pantalla vacía, lo declara y **ofrece** traerlo con `ctx.pedirDelErp(...)`, que llama a
  `/api/refrescar` y sigue el trabajo (`/api/trabajos/{id}`) mostrando el progreso.

Nunca viaja al navegador el `pin_hash` de las empresas ni ninguna credencial.

## Estado del cableado

| Pantalla | Endpoint | Estado |
|---|---|---|
| Arranque (sesión, empresas, ejercicio, rol) | `/api/yo`, `/api/empresas`, `/api/ejercicios`, `/api/modulos` | cableada |
| Inicio | `/api/dashboard`, `/api/analisis`, informes de `conciliacion`, `duplicados` y `fiscal`, `/api/interno/*` | cableada |
| Envíos a clientes | — | **sin endpoint**: la pantalla se deja vacía y lo dice |
| Informe financiero | `/api/informe` (`pyg`, `autodespro`, `tesoreria`), `/api/dashboard` | en curso |
| Cuentas anuales | `/api/informe` (`memoria`) | en curso: no hay circuito de aprobación |
| Proyecciones | `/api/informe` (`proyecciones`) | en curso: la plataforma proyecta por ejercicio, no por mes |
| Conciliación de mayores | `/api/informe` (`conciliacion`) | en curso: no hay extracto bancario ni propuesta automática |
| Duplicados de facturas | `/api/informe` (`duplicados`, interno) | en curso |
| Impuestos | `/api/informe` (`fiscal`, `libro_iva`, `libro_retenciones`) | en curso: no hay presentación telemática |
| Clientes | `/api/empresas`, `/api/interno/cartera` | en curso: la API no tiene NIF, ciudad, teléfono ni plantilla |
| Ajustes | `/api/interno/usuarios`, `/umbrales`, `/cache`, `/metricas` | en curso; la conexión con el ERP la resuelve el backend |

## Probar

Con la plataforma levantada:

    cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8011
    # el hub queda en http://127.0.0.1:8011/hub/ y el portal en http://127.0.0.1:8011/

Para verlo con cifras reales **sin gastar cuota del ERP**, siembra la caché local con los ejercicios
que ya se exportaron a `fixtures/`:

    ./.venv/bin/python backend/scripts/sembrar_cache_fixtures.py

Y para capturar cada pantalla y comprobar que los datos han entrado:

    /opt/scrapling/venv/bin/python backend/scripts/captura_hub.py interno "Conciliación de mayores" /tmp/hub.png
