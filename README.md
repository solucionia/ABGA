# Plataforma ABGA

Sustituto del sistema anterior: el portal de Vercel (export estático) más 7 workflows de n8n.
Aquí vive todo en un backend propio en Python, con autenticación real, multi-empresa,
dashboards con gráficas y caché de los datos del ERP.

```
navegador ──► API FastAPI ──► caché (SQLite/Postgres) ──► ERP apiCON
                  │
                  └─► módulos de informe (deterministas)  ──► HTML / JSON agregado
```

## Por qué el sistema anterior iba lento (y qué se ha cambiado)

Medido contra el ERP real, empresa 6091, ejercicio 2025:

| | Sistema anterior (n8n) | Esta plataforma |
|---|---|---|
| Apuntes que leía | **200 de 1.531** (el 13%) | **1.531 de 1.531** (100%) |
| Token del ERP | nuevo en cada clic | cacheado (~14 días de vida) |
| Segunda consulta | 40 s (todo de nuevo) | **0,04 s** desde caché |
| Primera lectura del ejercicio | ~40 s y datos incompletos | ~200 s y datos completos (una vez al día) |
| Números del informe | los calculaba un nodo Code en JS | los calcula Python, sin LLM |
| LLM | en el camino crítico (maquetaba el HTML) | fuera del camino de los números |
| Dashboard | no existía | KPIs, gráficas y comparativa interanual |
| Login | decorativo: cualquiera entraba con un código de empresa | usuarios, contraseñas (scrypt) y permisos por empresa |
| Errores | el webhook no respondía y el portal giraba hasta el timeout | mensaje de error controlado y registrado |
| Registro de uso | nodo desconectado que nunca escribía | tabla de ejecuciones con empresa, módulo, estado e importes |

Defectos del sistema anterior encontrados al portarlo (todos corregidos aquí):

1. **Truncado de datos.** `GET /api/apuntes/` devuelve **200 asientos por página** e ignora
   `$top=5000`. Los workflows pedían una sola página, así que informaban sobre una fracción del
   ejercicio. Además `$skip` no es un desplazamiento de filas sino el **número de página**, y la
   enumeración se reinicia al pasarse del final. Ahora se pide por **particiones de fecha** hasta
   que cada consulta cabe en una página, y el resultado se verifica contra `ResultadosTotales`.
2. **Impuesto de sociedades restado dos veces.** En REQ-05 la cuenta 630 estaba dentro de «otros
   gastos de explotación» y después se restaba otra vez tras el RAI.
3. **Balance que no cuadraba.** El original hacía `Math.max(0, total)` en cada agregado, así que
   los saldos de signo contrario desaparecían. Además faltaban cuentas enteras: en 2025 se dejaba
   fuera la 465 (242.268,51 €) y la 678. Ahora el balance cuadra al céntimo y, si aparece una
   cuenta fuera de los grupos previstos, el informe la nombra en lugar de descuadrar en silencio.
4. **Prefijos solapados** (`76` y `778` ya contenían a `760`-`769`), que contaban doble algunos
   ingresos.
5. **Duplicados inservibles por umbral.** Con el umbral de 4 puntos heredado salían 28.404 pares;
   con 11 salen ~100 y todos accionables.
6. **REQ-08 inventaba cifras** (resultado del año anterior al 25 %, inmovilizado ×1,2,
   vencimientos ÷5). Aquí esos cuadros se declaran como pendientes de completar.
7. **Rate limiting (429).** El ERP rechaza peticiones seguidas; el cliente nuevo espacia las
   consultas y reintenta con espera creciente (con `Retry-After` si viene).
8. **Credenciales en claro** en los 7 exports de n8n: ahora viven sólo en `.env` fuera de git.

## Puesta en marcha

```bash
make instalar     # crea .venv e instala las dependencias de desarrollo

# credenciales del ERP (nunca a git): .env con APICON_USERNAME, APICON_PASSWORD,
# APICON_CLIENT_ID, APICON_CLIENT_SECRET, APICON_EMPRESA_DEFECTO y SECRET_KEY

./.venv/bin/python backend/scripts/init_db.py          # empresas y usuarios iniciales
cd backend && ../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Portal en `http://localhost:8000`. Documentación interactiva de la API en `/docs`.
Arquitectura, deuda declarada y plan por fases: `ARQUITECTURA.md`.

## Módulos de informe

| Módulo | Publicado de | Quién lo ve |
|---|---|---|
| `dashboard` | nuevo | cliente (KPIs, gráficas, comparativa) |
| `pyg` | REQ-05 | cliente |
| `autodespro` | REQ-03 | cliente |
| `proyecciones` | REQ-02 | cliente |
| `fiscal` | REQ-06 | cliente |
| `tesoreria` | nuevo | cliente (cobros, pagos, antigüedad, previsión) |
| `memoria` | REQ-08 | cliente |
| `conciliacion` | REQ-01 | **uso interno ABGA** |
| `duplicados` | REQ-04 | **uso interno ABGA** |

Contrato para añadir uno nuevo: `backend/CONTRATO-MODULOS.md`.

## API

Todo el contrato está tipado con Pydantic y publicado en `/docs` (**42 esquemas** y 32 rutas,
contados sobre el `openapi()` de la aplicación): el año fuera de
rango o no numérico responde **422** diciendo qué campo falla, y un campo de más también es error.

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/api/login` · `/api/logout` · `/api/registro` | sesión (token firmado, cookie httpOnly) y alta del cliente con el PIN de la asesoría |
| GET | `/api/yo` · `/api/empresas` · `/api/modulos` · `/api/ejercicios` | contexto del usuario |
| GET | `/api/dashboard?cod_empresa&year` | KPIs y series en JSON agregado (~9 KB, no los apuntes) |
| GET | `/api/analisis?cod_empresa&year[&familia][&nivel][&solo_cache]` | el semáforo de «Análisis y alertas» en JSON, **sin** el HTML, con recorte por familia y nivel; `solo_cache=true` no pide nada al ERP (deja los años sin cargar declarados en `meta.faltantes`) |
| POST | `/api/informe` | genera un informe y devuelve `{status, html, data, meta, avisos}` |
| POST | `/api/informe/exportar` | descarga las tablas del informe (CSV o ZIP) para Excel |
| POST | `/api/refrescar` · GET `/api/trabajos/{id}` | releer del ERP en segundo plano, con progreso |
| GET | `/api/interno/resumen` | panel de ABGA: ejecuciones, caché, módulos, usuarios |
| GET | `/api/interno/metricas` · `/avisos` · POST `/avisos/atender` | uso y salud (informes hechos, de caché, incompletos, fallos) y los avisos, con su cierre |
| GET | `/api/interno/cartera?year[&limite][&desde]` | semáforo de análisis de todos los clientes, ordenado por gravedad (sólo caché) |
| GET | `/api/interno/umbrales?cod_empresa` | con qué criterios se mide a ese cliente, de dónde sale cada uno y hasta dónde se puede ajustar |
| POST | `/api/interno/umbrales` | ajusta un criterio de ese cliente (`valor` vacío = volver al general); fuera del rango, 400 |
| GET | `/api/interno/umbrales/ajustados` | qué clientes tienen criterios propios, con el valor general al lado (sólo ajustes) |
| POST | `/api/interno/cache` · `/usuarios` · `/empresas` · `/pin` | administración (sólo rol interno) |
| GET | `/api/salud` · `/api/cache` | diagnóstico |

El contrato de siempre se respeta: `{status:"ok", html:"<div…>", data:{…}}`, así que el HTML se
puede seguir imprimiendo o incrustar. **Los errores hablan todos el mismo idioma**:
`{"status":"error","error":"…","codigo":"…"}` (con `detalle` cuando es una validación), incluidos
los 404 de ruta.

## Cómo está organizado el backend

```
app/main.py        composición: routers, manejadores de error y estáticos (74 líneas)
app/api/           endpoints (rutas/), contratos (esquemas.py), permisos (dependencias.py)
app/aplicacion/    casos de uso: sesión, usuarios, informes, catálogo
app/servicio.py    orquesta el cálculo: coger años → calcular → maquetar → registrar
app/ledger.py  app/informes.py  app/modulos/    el dominio: contabilidad y maquetación
app/apicon.py bd.py cache.py db.py auth.py trabajos.py config.py   infraestructura
```

La regla (`api → aplicacion → dominio`) **la comprueba la suite**, no la buena voluntad:
`backend/tests/test_arquitectura.py` lee los `import` reales y falla si la capa HTTP toca la base de
datos, si el dominio importa infraestructura o si la aplicación depende de HTTP. Detalles y plan por
fases en `ARQUITECTURA.md`.

## Datos y caché

- Caché de apuntes por empresa y ejercicio, con TTL de 12 h. El motor lo elige `DATABASE_URL`:
  SQLite (`data/abga.sqlite3`) en local y **PostgreSQL** en producción (Coolify). El mismo SQL
  vale para los dos: la traducción vive sólo en `app/bd.py`
  (`./.venv/bin/python backend/scripts/verificar_bd.py` ejecuta el mismo recorrido —esquema,
  usuarios, apuntes, tokens, ejecuciones, **intentos de acceso y trabajos**— en los dos motores y
  compara los resultados uno a uno).
- **El estado que sobrevive al proceso vive en la base**, no en memoria: los intentos de acceso
  (límite de contraseña y de PIN) y los trabajos en segundo plano. Los trabajos corren en hilos de
  este proceso, así que la plataforma se declara de **un solo proceso**: `arranque.py` no arranca
  con `WEB_CONCURRENCY > 1` y lo explica, y `/api/salud` lo publica.
- Cobertura verificada: si el recorrido no alcanza `ResultadosTotales`, el meta del informe lo
  dice (`"cobertura": "parcial (n de m)")` y queda en el log.
- `scripts/precalentar.py` deja los ejercicios listos; pensado para un cronjob nocturno de Hermes.
- `scripts/traer_cache.py` y `scripts/traer_ejercicio.py` traen ejercicios a mano.
- `scripts/probe_*.py` son las sondas con las que se descubrió el comportamiento del ERP
  (paginación, límites, 429). No hacen falta en producción.

## Migraciones

El esquema se versiona con **alembic** y no se aplica a mano en ningún sitio: el DDL vive en
`backend/migraciones/versions/` y `app/esquema.py` es sólo el **contrato** (`TABLAS`), que una
prueba contrasta con lo que crean las migraciones. `bd.conectar()` aplica lo que falte la primera vez
que el proceso toca una base, así que no hay paso previo: arrancar ya pone la base al día.

```bash
make migrar                                   # aplica lo que falte y dice la versión
./.venv/bin/python backend/scripts/migrar.py --estado      # en qué versión está la base
./.venv/bin/python backend/scripts/migrar.py --historial   # qué migraciones hay
```

Para cambiar el esquema: se añade un fichero nuevo en `backend/migraciones/versions/` (plantilla
`script.py.mako`) con su `downgrade`, y —si crea o borra tablas— se actualiza `esquema.TABLAS`.
`backend/tests/test_migraciones.py` comprueba que una base nueva se construye, que una vieja se pone
al día **sin perder datos** y que el contrato y las migraciones coinciden.

La prueba que de verdad importa antes de un despliegue con migración es esa misma, pero sobre **una
copia real de producción** (el mismo fichero que se baja para las comprobaciones de restauración, ver
*Copias de seguridad*): se restaura en un PostgreSQL desechable, se cuentan las filas antes y después y
se comprueba que la base queda en la última versión con todas las tablas del contrato.

```bash
COPIA_PRODUCCION=/tmp/copia.dmp ./.venv/bin/python -m pytest backend/tests/test_migraciones.py -m lento
```

Sin `COPIA_PRODUCCION` la prueba se omite, porque la copia lleva datos de clientes y no vive en el
repositorio. Con ella, la copia tiene que ser de **antes** de la última migración: si ya está al día,
la prueba lo dice en vez de pasar en falso. Y el fichero se borra al terminar.

## Copias de seguridad

La copia la programa **Coolify** en el recurso de la base (pestaña *Backups*), y **ya está puesta**:
diaria a las 01:00 UTC (**03:00 en Madrid** en verano), base `postgres` en formato custom de
`pg_dump`, retención 7 copias / 14 días / 5 GB, guardada en el servidor. Pero una copia no es una
prueba de restauración, así que la comprobación que hay que pasar cada cierto tiempo es ésta:

```bash
# bajar la copia de la VM (lleva datos de clientes: borrarla al terminar)
gcloud compute ssh apps-varias --zone=europe-west1-b --quiet \
  --command="sudo cat /data/coolify/backups/databases/root-team-0/abga-postgres-<uuid>/pg-dump-postgres-<epoch>.dmp" > /tmp/copia.dmp
./.venv/bin/python backend/scripts/verificar_copia.py --copia /tmp/copia.dmp
# la restaura en un PostgreSQL desechable y lee los datos con el propio código de la plataforma
```

La última vez que se hizo (27/09/2026, con la copia real de producción): **copia válida**, 9 tablas,
391 empresas, 2 usuarios, 75 ejecuciones, y `listar_empresas()` devolviendo las 391 sobre lo
restaurado. Su propia prueba automática está en `backend/tests/test_copia.py` (marcada `lento`,
necesita `pgserver`). Detalles y pendientes: `ARQUITECTURA.md`, Fase 3.

## Entornos

Hay **dos aplicaciones** en el mismo proyecto de Coolify, con la misma base y la misma caché:

| Aplicación | URL | `APICON_SOLO_CACHE` |
|---|---|---|
| `abga-plataforma` (producción) | https://abga.34.76.127.144.sslip.io | vacía: lee el ERP cuando la caché no tiene el dato |
| `abga-preview` (previsualización) | https://abga-preview.34.76.127.144.sslip.io | `1`: sólo caché, no toca el ERP |

La de previsualización sirve para enseñar cambios y probar sin gastar el ERP. Comparten base (los
mismos datos), pero **no** la `SECRET_KEY`: una sesión de una no vale en la otra. Y en producción, si
el TTL de 12 h ha caducado, el primer informe de una empresa y ejercicio tarda lo que tarde la
descarga (~200 s para un ejercicio completo); los que ya están en caché siguen siendo instantáneos.

## Observabilidad

Cada petición lleva un identificador (`X-Request-ID`): si el cliente lo manda se respeta, si no se
genera. Vuelve en la cabecera de la respuesta, sale en **todas** las líneas de registro de esa petición
y queda en la fila de `ejecuciones` que genera — así un informe registrado y el registro de ese
momento se pueden atar. Con `LOG_FORMATO=json` el registro sale en una línea JSON por evento (`nivel`,
`registro`, `id_peticion`, `mensaje`, y el rastro si hay excepción), para que lo lea un programa.

```bash
# uso y salud de los últimos 7 días (sólo rol interno)
curl -s -b cookies.txt 'https://…/api/interno/metricas?dias=7' | jq '{total, por_estado, informes_parciales, avisos_pendientes}'
# avisos sin atender: informes incompletos o que fallaron al calcular
curl -s -b cookies.txt 'https://…/api/interno/avisos' | jq '.avisos[] | {id, tipo, cod_empresa, modulo, veces, detalle}'
```

Los informes que salen con el ejercicio a medias (`cobertura=parcial`) o que fallan dejan **aviso**:
se agrupan por tipo/empresa/ejercicio/módulo (con contador, para que una caída del ERP no deje cientos
de filas), se ven en el panel interno y se cierran a mano. `/api/salud` publica cuántos hay pendientes,
que es lo que puede vigilar una monitorización sin ver datos de nadie. No hay correo ni webhook a
propósito: no hay destino configurado, y eso se añadiría en un solo sitio (`app/alertas.py`).

## Análisis y cartera

`analisis` no es un informe más: es un **catálogo de comprobaciones** que se ejecutan sobre los apuntes
y salen clasificadas por riesgo (rojo · actuar, naranja · revisar, verde · correcto, gris · los apuntes
no traen el dato). Hoy son **32 comprobaciones** de cinco familias (contable, fiscal, financiero,
mercantil, laboral) y **añadir una es declarar una entrada en `REGLAS`** —qué comprueba, cómo se
calcula y una función que devuelve el nivel—, nada más. Una regla que falle no tumba el informe: sale
en gris diciendo qué pasó.

Dos reglas de la casa que el catálogo respeta: **ninguna cifra se estima** y **sin apuntes no hay
verde**. Si el libro no da un dato, la comprobación dice cuál falta en lugar de rellenarlo; y si el
ejercicio no tiene apuntes cargados, todo sale en gris (antes 12 comprobaciones salían verdes por
buscar ausencias, que es decir «todo bien» de lo que no se sabe).

```bash
# el semáforo de un cliente, para una pantalla (sin el HTML del informe)
curl -s -b cookies.txt 'https://…/api/analisis?cod_empresa=6091&year=2025' | jq '.data.resumen'
# sólo lo que exige actuación, y las familias financieras
curl -s -b cookies.txt 'https://…/api/analisis?cod_empresa=6091&year=2025&nivel=alerta&familia=financiero' | jq '.data.seleccion[] | .titulo'
# los criterios que se están aplicando (se publican con el resultado, con su origen)
curl -s -b cookies.txt 'https://…/api/analisis?cod_empresa=6091&year=2025' | jq '.data.umbrales'

# y sin pedirle nada al ERP: con un año sin cargar, declara lo que falta en vez de ir a buscarlo
curl -s -b cookies.txt 'https://…/api/analisis?cod_empresa=6091&year=2025&solo_cache=true' | jq '{faltantes: .meta.faltantes, avisos}'

# con qué se mide a un cliente, y ajustarlo (valor null = volver al general)
curl -s -b cookies.txt 'https://…/api/interno/umbrales?cod_empresa=6091' | jq '{ajustados, umbrales: (.umbrales | map_values(.valor))}'
curl -s -b cookies.txt -X POST 'https://…/api/interno/umbrales' -H 'Content-Type: application/json' \
  -d '{"cod_empresa":"6091","clave":"antiguedad_clientes","valor":120}' | jq '.ajustados'
# la cartera del despacho: quién está en rojo, por cuánto y por qué (sólo rol interno)
curl -s -b cookies.txt 'https://…/api/interno/cartera?year=2025&limite=30' | jq '.filas[] | {empresa, n_rojo, importe_riesgo, rojos}'
```

La **cartera** es la vista que convierte el despacho en asesoría: en vez de abrir cliente por cliente,
una lista con quién tiene rojos. Se calcula **sólo con los ejercicios que ya están en la caché** (no se
le pide nada al ERP: con 391 clientes serían horas y un 429) y por tandas (`limite`/`desde`, con
`pendientes` en la respuesta). Los clientes que no tienen el ejercicio cargado se declaran
(`sin_el_ejercicio`, `sin_datos`), no se rellenan.

Los rojos **dejan aviso** (`tipo=analisis_rojo`): el módulo declara qué hay que apuntar con un hook
opcional (`avisos_de_datos`) y el servicio lo apunta agrupado por empresa y ejercicio, así que un rojo
no depende de que alguien abra el panel para existir.

## Pruebas

Un solo comando, sin recordar nombres de script:

```bash
make pruebas     # toda la suite (omite lo que necesita los fixtures si no están)
make rapido      # sólo lo que no depende de datos reales: es lo que corre la CI
make reales      # lo que sí depende de los fixtures del ERP
make lento       # los verificadores heredados, completos
make verificar   # lint + tipos + toda la suite
```

Lo que la suite deja claro desde el primer día:

- **No necesita secretos ni datos del cliente.** Fabrica su propio `.env` con credenciales
  ficticias y una base de datos temporal; el ERP está simulado (`tests/conftest.py`), así que
  ninguna prueba sale a la red ni escribe en el entorno de desarrollo.
- **El dominio se prueba con datos sintéticos propios** (`tests/sintetico.py`: un ejercicio
  contable completo — apertura, venta con IVA, compra, nómina, retención y cierre — que cuadra al
  céntimo). Es lo que permite comprobar la aritmética del balance y del PyG en la CI, sin datos de
  nadie.
- **Lo que necesita los datos reales se marca** con `@pytest.mark.datos_reales` y se omite solo
  cuando no están.
- Los verificadores de `backend/scripts/verificar_*.py` siguen ahí y la suite los ejecuta: los
  verdes, como prueba de regresión; los tres con expectativas caducadas, como `xfail` con el
  motivo escrito.

```bash
./.venv/bin/python -m pytest -m datos_reales -k modulos   # un módulo concreto
./.venv/bin/python -m pytest -k "cache or permisos" -v   # por nombre de prueba
```

Criterios de decisión y plan por fases: **`ARQUITECTURA.md`**.

Los fixtures de `fixtures/` son respuestas reales del ERP (empresa 6091) y están fuera de git.

## Seguridad

- Contraseñas con `scrypt`; tokens de sesión firmados con HMAC-SHA256 y caducidad.
- Cada usuario ve sólo las empresas asignadas; los informes internos exigen rol interno.
- `.env`, `data/` y `fixtures/` están en `.gitignore`. **Los exports originales de n8n contienen
  las credenciales del ERP en claro**: no se comparten ni se suben a ningún repositorio.
- Pendiente antes de abrirlo a clientes reales: cambiar las contraseñas de demostración, poner
  HTTPS por delante y decidir el dominio definitivo.
