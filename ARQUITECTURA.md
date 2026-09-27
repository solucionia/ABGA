# Arquitectura de la plataforma ABGA

Documento de trabajo técnico. Dice **qué hay hoy**, **qué se ha medido**, **hacia dónde va** y
**en qué orden**, para que cualquier decisión posterior se pueda discutir sobre hechos y no sobre
impresiones. Se lee junto al `README.md` (que explica el producto) y a
`backend/CONTRATO-MODULOS.md` (que explica cómo se añade un informe).

Última revisión: **Fases 0 a 4 y 6 hechas** (Fase 5, el frontal, aplazada a propósito).

---

## 1. Punto de partida: no es un script, es un sistema con un borde descuidado

Lo que ya es arquitectura y no se debe tocar sin motivo:

| Pieza | Qué aporta |
|---|---|
| `app/modulos/` | Registro de plugins con contrato escrito (`CONTRATO-MODULOS.md`): 13 informes independientes que entran en el catálogo sin tocar el borde |
| `app/ledger.py` | Dominio contable puro: líneas, saldos, prefijos PGC, cierres. Sin HTTP ni SQL |
| `app/informes.py` | Maquetación obligatoria del cliente en un único sitio |
| `app/apicon.py` | Adaptador del ERP: token cacheado, particionado por fechas, reintentos de 429 |
| `app/bd.py` + `app/cache.py` | Puerto de persistencia portable SQLite/PostgreSQL con la traducción aislada |
| `app/servicio.py` | Caso de uso «ejecutar un informe»: cargar años → calcular → maquetar → registrar |
| `Dockerfile` + `scripts/arranque.py` | Imagen mínima sin root, configuración validada al arrancar |

Los módulos de informe **no** hablan con el ERP ni con la base de datos: reciben
`{ejercicio: [Linea]}` y un `ctx`. Esa frontera es la que hace posible probar el dominio con datos
propios (ver §4).

## 2. Lo que todavía no es arquitectura (medido, no supuesto)

| # | Problema | Evidencia |
|---|---|---|
| 1 | Los trabajos en segundo plano siguen corriendo en **hilos del proceso**: su estado ya está en la base, pero el hilo no. Con varios procesos haría falta una cola de verdad; mientras, la plataforma se declara de un solo proceso y `arranque.py` se niega a arrancar con `WEB_CONCURRENCY > 1` | `trabajos.py`, `scripts/arranque.py::comprobar_procesos` |
| 2 | Sin migraciones versionadas: `ESQUEMA` + `MIGRACIONES` + `migrar()` en `conectar()`. Ya provocó un cuelgue del login (`ALTER TABLE` pidiendo bloqueo sobre una tabla en uso) | `esquema.py` |
| 3 | Frontend monolítico: `app.js` de 585 líneas, todo por `innerHTML`, sin módulos ni pruebas | `frontend/` |
| 4 | Sin continuidad: no hay copia de seguridad del PostgreSQL de producción en el repositorio, ni entorno de previsualización, ni métricas | ninguna referencia a `pg_dump` |

### Cerrado en la Fase 7 (tipos del dominio de informes, 27/09/2026)

Los 14 ficheros de `app.modulos` —los 13 informes y su catálogo— estaban exentos de mypy desde la
Fase 1 (`ignore_errors`) porque venían de los nodos Code de n8n, que calculan sobre `dict`. Medido
antes de empezar: **31 errores en 11 ficheros**, ninguno en los otros tres. Al arreglarlos se cerró el
último punto de la tabla de arriba y apareció lo que la excepción escondía:

| Qué | Evidencia |
|---|---|
| El informe de **Proyecciones** devolvía el cuerpo metido en una **tupla de un elemento** (una coma de más al cerrar la expresión del HTML): el documento salía con el HTML entre comillas —`('<table style=…',)`, con las comillas escapadas— y así lo pintaba el portal | `ast.parse` lo confirma (`Assign.value` es un `Tuple`); el HTML llevaba 1 marca `('` y 1 `',)`; ninguna prueba lo veía porque la que mira el HTML de los módulos corre con los fixtures reales y se omite en la CI |
| Y por eso ahora hay una prueba que **no** necesita datos del cliente: `backend/tests/test_modulos_sinteticos.py` renderiza los **13** informes con datos sintéticos y exige que el documento sea HTML (sin `repr`, sin comillas escapadas, con el cuerpo empezando por etiqueta) | 14 pruebas; se comprobó que **falla** en `proyecciones` antes del arreglo y pasa después |

Los demás errores eran anotaciones que faltaban (`list[dict[str, Any]]` en acumuladores), variables
reutilizadas con otro tipo (el `m` de un bucle que antes era un movimiento, el `d` de un `dict.get`),
`Mapping`/`Sequence` en las firmas en lugar de `dict`/`list` (que mypy rechaza por invariancia) y una
clave de diccionario que podía venir como `Any | None`. `pyproject.toml` ya **no tiene la excepción**:
`mypy` comprueba 65 ficheros sin una queja.

### Cerrado en la Fase 1 (contrato, capas y errores)

| Antes | Ahora |
|---|---|
| `main.py` de **581 líneas** mezclando transporte, negocio y SQL | **74 líneas** que sólo montan routers, manejadores y estáticos. Los casos de uso viven en `app/aplicacion/`, los contratos en `app/api/esquemas.py` |
| `POST /api/interno/usuarios` declarado **dos veces** (la segunda, inalcanzable) | Un solo endpoint, y una prueba que falla si vuelve a haber rutas duplicadas |
| 24 rutas con `payload: dict = Body(...)`; `/docs` sin contrato y un año no numérico daba **500** | **42 esquemas** Pydantic publicados en el OpenAPI; el año fuera de rango o no numérico responde **422** con el campo que falla. Un campo de más también es error |
| Tres convenciones de error (y el `detail` de FastAPI **que el portal no leía**) | Un único cuerpo `{status, error, codigo}` con códigos estables, para todos los errores incluidos los 404 de ruta |
| CORS con `allow-origins=*` **y** credenciales: reflejaba cualquier `Origin` | CORS cerrado por defecto (el panel se sirve del mismo origen); sólo se abre con `CORS_ORIGENES` de dominios concretos, y `*` se ignora |
| El panel de usuarios mostraba «Usuario **undefined** creado (**undefined**)» | La respuesta lleva `email`, `rol` y `password` — lo que el frontal pinta de verdad |
| 3 verificadores heredados en rojo y 5 comprobaciones que ya no comparaban nada | Los 12 verificadores en verde; las comprobaciones muertas, reparadas o documentadas |

### Cerrado en la Fase 2 (estado en memoria, `SECRET_KEY` y número de procesos)

| Antes | Ahora |
|---|---|
| **`/api/login` no tenía ningún límite de intentos**: se podía probar un diccionario entero contra una cuenta sin que nada lo frenara | 10 fallos por cuenta cada 15 minutos → **429**; el límite del PIN (8 por empresa) sigue igual |
| Los intentos vivían en un **diccionario del proceso**: un reinicio los borraba y con dos procesos el mismo límite valía el doble | Tabla `intentos`; sobrevive al reinicio, cuenta igual con varios procesos y caduca por ventana |
| Los trabajos vivían en memoria: al reiniciar, el portal pedía el progreso de un id que ya no existía (404 en bucle) y con dos procesos el trabajo era invisible desde el otro | Tabla `trabajos`: el progreso se ve desde cualquier proceso, queda constancia de lo que pasó y **lo que quedó a medias se marca «interrumpido» al arrancar** en lugar de mentir |
| `SECRET_KEY` con valor por defecto (`cambiar-esta-clave`): un despliegue mal configurado arrancaba firmando sesiones con una clave pública | Obligatoria y con mínimo de 32 caracteres; el arranque falla diciendo cómo generarla |
| Restricción implícita de un solo proceso | Declarada en `/api/salud`, en el log de arranque y **comprobada**: `WEB_CONCURRENCY > 1` detiene el arranque con un mensaje que lo explica |

## 3. Arquitectura objetivo: monolito modular por capas

Con un solo mantenedor, microservicios o colas serían peor que el problema. El objetivo es un
**monolito modular** donde cada capa se pueda probar sola:

```
backend/app/
  main.py         composición: routers, manejadores de error y estáticos (74 líneas)
  api/
    rutas/        un fichero por recurso: sesion · catalogo · informes · interno
    esquemas.py   contratos de entrada y salida (Pydantic) — el contrato de la API
    dependencias.py  quién es el usuario y a qué empresa puede entrar
    manejadores.py   traducción de errores a respuestas HTTP
    cookies.py    la cookie de sesión, en un sitio
  errores.py      vocabulario de errores (estado + código), compartido por api y aplicacion
  aplicacion/     casos de uso: sesion · usuarios · informes · catalogo
  servicio.py     orquestación del cálculo de un informe (cargar años → calcular → registrar)
  ledger.py       dominio contable puro: líneas, saldos, prefijos PGC, cierres
  informes.py     maquetación obligatoria del cliente (HTML, SVG, importes es-ES)
  modulos/        los 13 informes: cálculo determinista, sin ERP ni SQL
  apicon.py bd.py cache.py db.py auth.py trabajos.py config.py esquema.py exportar.py
                  infraestructura: ERP, persistencia, sesión, trabajos en curso, configuración
backend/tests/    dominio · núcleo real · contrato de módulos · API · seguridad · heredados
```

**Regla de dependencia:** `api → aplicacion → dominio`, y la infraestructura implementa lo que
necesita la aplicación; el dominio no importa nada de fuera. Se puede comprobar con una lectura:
en `modulos/` y `ledger.py` no aparece `fastapi` ni `sqlite3`; en `api/` no aparece ninguna consulta
SQL. Corolario práctico: un informe nuevo se prueba con datos sintéticos, y una tarea programada
(los informes por email que pidió ABGA) reutiliza el mismo caso de uso en lugar de duplicar el
recorrido por HTTP.

## 4. Fase 0 — entregada: la red de seguridad

Sin esto, cualquier refactor se hace a ciegas. Es lo que había antes y lo que hay ahora:

| | Antes | Ahora |
|---|---|---|
| Ejecutar todo | recordar 20 nombres de script | `make pruebas`, `make verificar` |
| Herramientas | ninguna instalada (ni pytest) | `pyproject.toml` con ruff, mypy y pytest y `requirements-dev.txt` |
| Dependencia de datos reales | los verificadores sólo funcionaban con los fixtures del cliente | el dominio se prueba con datos sintéticos propios; los fixtures son opcionales (`-m datos_reales`) |
| Simulación del ERP | no había | `ErpSimulado` con el mismo contrato que el cliente real (caché incluida) |
| Datos de cliente en pruebas | implícitos | la suite fabrica su `.env` y su base temporal: **cero** datos del cliente y **cero** secretos |
| CI | no existía | `.github/workflows/ci.yml`: ruff + mypy + pytest + `verificar_secretos.py` |
| Errores de los verificadores heredados | invisibles (en rojo, nadie los ejecutaba) | ejecutados por la suite; los 3 con expectativas caducadas están marcados y documentados |

**Resultado medido** (en este equipo, con los fixtures locales):

```
make rapido   →   63 pruebas            (no necesita nada del cliente)
make reales   →   25 pruebas            (necesita fixtures)
make lento    →   13 pruebas            (los 12 verificadores heredados, en verde)
make verificar→  131 pruebas + ruff + mypy en verde
make lint     →  ruff: All checks passed
make tipos    →  mypy: Success, no issues in 54 source files
```

**Hallazgos que ha destapado la Fase 0** (esto es lo que compra tener la red puesta):

1. **Tres verificadores heredados en rojo** y nadie se había enterado, porque no había nada que
   los ejecutara. Al medirlos, los tres fallan por **expectativas caducadas del propio arnés**, no
   por un defecto del producto:
   - `verificar_conciliacion.py` exige `INTERNO = True` y el pie de uso interno: la conciliación
     se **abrió al cliente** en la reunión del 18/09/2026. El requisito cambió, no el informe.
   - `verificar_autodespro.py` compara ratios con tolerancia `1e-6` mientras el módulo los
     redondea (1,115 vs 1,1150265), lee la fila del resultado por posición fija (`pyg[-3]`, que
     hoy es la del impuesto porque la tabla ganó filas) y espera las columnas de la más antigua a
     la más nueva.
   - `verificar_proyecciones.py` da por hecho que hay dos ejercicios para la tendencia (hay tres),
     que no hay cuentas 57x (las hay: 572 en 2025) y que la pendiente de ingresos es positiva con
     esos dos puntos (con los dos ejercicios reales, los ingresos **bajaron**).
2. **Cinco comprobaciones muertas**: cuatro verificadores calculan un valor esperado y **no lo
   comparan con nada** (`verificar_conciliacion` → `esperado_pend`, `verificar_fiscal` → `p4751`,
   `verificar_libro_retenciones` → `toca_67`, `verificar_memoria` → `impuesto_legado`,
   `verificar_proyecciones` → `esc_esperado`).
3. **`dashboard.py` y `tesoreria.py` calculaban valores que no se usaban** (un año y una lista de
   meses): código muerto retirado.

## 4.bis Fase 1 — entregada: contrato y capas

Lo que la Fase 0 dejó medido se ha resuelto por capas, sin romper nada (las 131 pruebas siguen en
verde, incluidos los 12 verificadores heredados):

| Trabajo | Resultado |
|---|---|
| Contrato tipado | `app/api/esquemas.py`: 12 modelos de petición y 29 de respuesta, **42 esquemas publicados** en el OpenAPI. El año fuera de rango o no numérico responde **422** con el campo que falla; un campo de más también es error (`extra="forbid"`) |
| Un solo formato de error | `app/errores.py` (vocabulario, con estado y **código estable**) + `app/api/manejadores.py` (traducción). El `detail` de FastAPI ya no se pierde en la pantalla, y una ruta `/api/…` que no existe contesta JSON, no el 404 del servidor de ficheros |
| Capas de verdad | `api/rutas/{sesion,catalogo,informes,interno}` → `aplicacion/{sesion,usuarios,informes,catalogo}` → `dominio` (ledger, informes, modulos) e infraestructura. `main.py` pasó de **581 a 74 líneas** |
| Ruta muerta | `POST /api/interno/usuarios` era el mismo endpoint declarado dos veces; queda uno, con la forma que el panel pinta (`email`, `rol`, `password`) |
| CORS | Cerrado por defecto (mismo origen); se abre sólo con `CORS_ORIGENES` de dominios concretos, y `*` se ignora |
| Tipos | El ratchet de mypy bajó de 5 módulos a **uno** (`app.modulos.*`, el tipado de los informes): `main`, `db`, `auth` e `informes` quedaron limpios y no vuelven a la lista. Mypy cubre ahora **54 ficheros** |

**Hallazgos de la Fase 1** (los tres salieron al mover el código, no de una auditoría):

1. **El panel enseñaba «Usuario undefined creado (undefined)».** El endpoint duplicado devolvía
   `usuario` como objeto, pero el frontal pinta `email`, `rol` y `password` en la raíz. Se ve en
   `frontend/app.js:577`. Ahora la respuesta lleva los tres y hay una prueba que lo fija.
2. **`proyecciones` puede no cuadrar al céntimo consigo mismo.** Con 2023 y 2024 iguales (el escenario
   del arnés) la fila del resultado se desvía **0,01 €** de `RAI − impuesto`, porque el módulo
   redondea cada magnitud por separado. No es un error de cálculo, pero en un informe que ve un
   asesor puede parecerlo: **decisión de producto pendiente** (¿se cuadra la cascada del PyG
   proyectado?), y mientras tanto el arnés compara con tolerancia de un céntimo y lo dice.
3. **La salida de los errores no era la misma para el usuario que para el que depura.** El
   `HTTPException(detail=…)` que lanzaban los endpoints internos **no lo leía el portal**: el aviso
   que veía el cliente era «respuesta no válida». Unificado en `{status, error, codigo}`.

## 4.ter Fase 2 — entregada: el estado sale del proceso

| Trabajo | Resultado |
|---|---|
| Intentos persistentes | Tabla `intentos` con la clave del intento (`pin:<empresa>` / `login:<correo>`) y el instante en ISO; la ventana de 15 minutos se filtra en la consulta. Sobrevive al reinicio y cuenta igual con varios procesos |
| **Límite en el login** (no había ninguno) | 10 fallos por cuenta cada 15 minutos → **429** con `codigo: limite_alcanzado`. Un acceso correcto limpia el contador. Cuenta también si el correo no existe, así que no sirve para descubrir cuentas |
| Trabajos en la base | Tabla `trabajos`: tipo, empresa, ejercicio, estado, mensaje, progreso, pasos y resultado; el portal los lee de ahí, así que el progreso se ve desde cualquier proceso y queda constancia. `arranque.py` marca como **interrumpidos** los que quedaron en curso |
| `SECRET_KEY` | Obligatoria y mínimo 32 caracteres; el arranque falla con el comando para generar una. Antes había un valor por defecto conocido en el repositorio |
| Un solo proceso, declarado | `/api/salud` lo dice, el log de arranque lo dice, y `WEB_CONCURRENCY > 1` **detiene** el arranque con el motivo escrito |

**Verificado en los dos motores**: `verificar_bd.py` (que ya comparaba SQLite contra el PostgreSQL
embebido, recorrido a recorrido) ahora cubre también intentos y trabajos: mismo resultado en los
dos. Y la suite pasa de **131 a 143 pruebas**, con 12 nuevas sobre este comportamiento.

**Hallazgo de la Fase 2**: **el acceso no tenía ningún límite de intentos.** El PIN del alta sí lo
tenía, pero contra `/api/login` se podía probar un diccionario entero sin que nada lo frenara; y el
contador del PIN, al vivir en memoria, se borraba con cada reinicio. Los dos agujeros eran el mismo
problema (estado en el proceso) y se cierran juntos. Sale a la luz al escribir la prueba del
comportamiento nuevo, no de una auditoría: la prueba del límite del PIN fue el patrón que faltaba.

### Deuda declarada, a propósito

- **Tipos (mypy)**: sólo los 13 módulos de informe siguen en la lista de excepciones (calculan
  sobre `dict`/`object` tipados a medias, herencia de los nodos Code de n8n). Mypy **sí** cubre el
  resto: capas nuevas incluidas (`api/`, `aplicacion/`, `errores.py`). La lista es un ratchet: un
  módulo que salga de ella no vuelve a entrar.
- **Estilo (ruff)**: tres reglas silenciadas con motivo (`B008` por el patrón `Depends()` de
  FastAPI, `E501` por las plantillas HTML en cadenas y `E741` por la `l` heredada de «línea»), y
  `F841` en `backend/scripts/verificar_*.py` mientras se reescriben con `assert`.
- **Ya no hay `xfail`**: el año no numérico está arreglado y probado, y los tres verificadores
  caducados están reparados. `xfail` queda como herramienta, no como registro de deuda.

## 4.quater Fase 3 — en curso: continuidad (copias de seguridad)

Lo que ya está hecho, y lo que falta.

**Lo que ofrece Coolify** (comprobado en su documentación, no supuesto): copias programadas por
recurso de base de datos, nativas para PostgreSQL (`pg_dump` en formato custom), que se guardan
**en el propio servidor** en `/data/coolify/backups` con retención configurable (nº de copias, días
o GB), botón **Backup Now** y un registro de ejecuciones con nombre de base y **tamaño del
fichero**. Opcionalmente sube una copia a un destino S3-compatible. No hace falta S3 para empezar.

**La regla que no se salta**: *una copia no es una prueba de restauración*. Que la ejecución ponga
«Success» sólo significa que se creó un fichero. Por eso está escrito
`backend/scripts/verificar_copia.py`, que:

1. comprueba que el fichero es un volcado legible (`pg_restore --list`, con las tablas dentro);
2. **levanta un PostgreSQL desechable** (el embebido de `pgserver`, en un directorio temporal) y
   restaura la copia ahí — nunca sobre la base real;
3. verifica que están las tablas de la plataforma (leídas de `esquema.py`: una sola fuente de
   verdad) y que las imprescindibles tienen filas;
4. **lee el resultado con el propio código de la plataforma** (`db.listar_empresas()`,
   `db.listar_usuarios()`, `cache.info_cache()`): si el volcado no sirviera, esas consultas
   fallarían.

Probado de extremo a extremo en este equipo (`backend/tests/test_copia.py`, marcado `lento`): una
base con el esquema de la plataforma → `pg_dump` → la comprobación pasa y lee los datos; un fichero
**truncado** falla; un fichero **inexistente** falla con su mensaje. Los casos malos están ahí a
propósito: sin ellos, la comprobación no probaría nada.

**Hecho y medido (27/09/2026)** — la copia está programada en `abga-postgres` y **probada de verdad**:

| Qué | Valor medido |
|---|---|
| Horario | uuid `gy0s9juxencq0pxymbkwxu9p`, cron `0 1 * * *`, `enabled: true` |
| Cuándo | 01:00 **UTC** = **03:00 en Madrid** en verano (02:00 en invierno). La API de Coolify no acepta zona horaria: el cron es del servidor, y el servidor (`apps-varias`) está en `Etc/UTC` — comprobado con `date` y `/etc/timezone` |
| Qué copia | `dump_all: false`, base `postgres` (así se llama de verdad la base: lo confirma el `DATABASE_URL` de la app, `…:5432/postgres`), formato custom de `pg_dump` |
| Retención | 7 copias · 14 días · 5 GB (en el servidor; `save_s3: false`) |
| Primera copia | 27/09 18:20:34 UTC, estado `success`, **3.601.871 bytes** (3,4 MB) |
| Dónde queda | `/data/coolify/backups/databases/root-team-0/abga-postgres-x1i5tm1kifhvo2mypcgbza6d/pg-dump-postgres-<epoch>.dmp` |

**La prueba de restauración, con esa copia de producción** (no con una de laboratorio):

```
ok  pg_restore puede leer el fichero           ok  tabla empresas — 391 filas
ok  el volcado trae tablas — 9 con datos       ok  tabla usuarios — 2 · permisos — 1 · ejecuciones — 75
ok  pg_restore termina bien                    ok  listar_empresas() → 391 empresas
ok  el usuario interno está                    ok  info_cache responde
RESULTADO: la copia se restaura y los datos se leen con la plataforma. Copia válida.
```

Para repetirla cuando haga falta (la copia se trae de la VM y se prueba en un PostgreSQL desechable;
el fichero que baja lleva datos de clientes, así que se borra al terminar):

```bash
gcloud compute ssh apps-varias --zone=europe-west1-b --quiet \
  --command="sudo cat /data/coolify/backups/databases/root-team-0/abga-postgres-<uuid>/pg-dump-postgres-<epoch>.dmp" \
  > /tmp/copia.dmp
./.venv/bin/python backend/scripts/verificar_copia.py --copia /tmp/copia.dmp
```

**Migraciones versionadas (alembic) — hecho y medido (27/09/2026)**

Hasta ahora el esquema se aplicaba de dos formas a la vez: `CREATE TABLE IF NOT EXISTS` en cada
conexión y una lista de `ALTER TABLE` a mano (`MIGRACIONES`) que se lanzaba al conectar. Ahora hay
una sola vía, `backend/migraciones/`:

- `bd.conectar()` aplica lo que falte **una vez por proceso y base**, así que para quien usa la
  plataforma (o los scripts) nada cambia; lo que cambia es que cada cambio de esquema queda
  versionado en la tabla `alembic_version` y se puede saber en qué punto está una base.
- La migración `0001_esquema_inicial` reproduce el esquema que ya estaba, con `IF NOT EXISTS` y
  comprobación de columnas: **aplicarla a la base de producción no toca los datos**, sólo la marca.
- El DDL vive sólo en la migración; `app/esquema.py` queda como **contrato** (`TABLAS`,
  `IMPRESCINDIBLES`) y una prueba comprueba que lo que crean las migraciones coincide exactamente
  con ese contrato (si alguien añade una tabla en un sitio y no en el otro, se pone rojo).
- **La prueba del despliegue, con la copia real de producción**: se restauró el volcado de
  `abga-postgres` (391 empresas, 2 usuarios, 1 permiso, 75 ejecuciones) en un PostgreSQL temporal, se
  aplicaron las migraciones y los recuentos quedaron **idénticos**; `pin_hash` presente y la base
  marcada en `0001`. Se hace con SQL puro para contar, porque llamar al código de la aplicación
  migraría la base antes de medir.
- A mano: `./.venv/bin/python backend/scripts/migrar.py` (`--estado`, `--historial`) o `make migrar`.
- Al desplegar: la imagen necesita `alembic` y `sqlalchemy` (`requirements.txt` ya los trae) y el
  arranque pone la base al día; si algo fallara, el arranque falla antes de servir.

**Entorno de previsualización — hecho y medido (27/09/2026)**

Hasta hoy había un solo despliegue y llevaba `APICON_SOLO_CACHE=1`: servía de la caché y no tocaba el
ERP. Eso vale para enseñar, pero no es lo que debe tener delante quien usa la plataforma de verdad (un
informe que no esté en la caché no se puede generar). Ahora hay **dos aplicaciones** en el mismo
proyecto de Coolify:

| Aplicación | Puerto del host | URL | `APICON_SOLO_CACHE` | Para qué |
|---|---|---|---|---|
| `abga-plataforma` (`enponjop7qgrlq0ou0bqudtw`) | 3099 → 8000 | https://abga.34.76.127.144.sslip.io | vacía (lee el ERP) | El portal que se le enseña al cliente |
| `abga-preview` (`g1zpqdfx3ic6aj2rfludxgym`) | 3097 → 8000 | https://abga-preview.34.76.127.144.sslip.io | `1` (sólo caché) | Enseñar cambios sin gastar el ERP |

- Las dos comparten la misma base y la misma caché: la previsualización enseña **los mismos datos**
  que producción, sin pedirle nada al ERP.
- `SECRET_KEY` **distinta** en cada una: una sesión de la previsualización no vale en producción.
- `DEMO_AUTO_LOGIN` y `CORS_ORIGENES` vacías en las dos, y comprobado que sin sesión las dos responden
  **401** (`/api/yo`): eso es lo que evita que una URL expuesta se convierta en un portal abierto.
- En la máquina sólo las separa el puerto del host (3099 y 3097); del nombre y del certificado se
  encarga un `virtualhost` de nginx por dominio, como el resto de los servicios del servidor.
- Consecuencia de dejar producción leyendo el ERP: si el TTL de 12 h ha caducado, **el primer informe
  de esa empresa y ejercicio tarda lo que tarde la descarga** (se midió más de 120 s para un ejercicio
  completo). Los que ya están en la caché siguen siendo instantáneos.
- Al compartir base, los intentos de acceso de la previsualización entran en el mismo contador que los
  de producción (10 fallos / 15 min por cuenta). Si algún día molesta, se le da su propia base: la
  migración `0001` ya permite crear el esquema desde cero.

**Lo que sigue pendiente de la Fase 3**:

| Pendiente | Qué falta |
|---|---|
| Copia fuera del servidor | Si se pierde la máquina se pierde también `/data/coolify/backups`. Para cubrirlo hace falta un destino S3-compatible (bucket + credenciales) y `save_s3: true` |
| Aviso de copia perdida | `missing_backup_notification_days` está a 0: si la copia falla, nadie se enteraría |

**Observabilidad — hecho y medido (27/09/2026)**

La plataforma ya escribía `ejecuciones` (con empresa, módulo, estado, segundos y si salió de caché),
pero mirarla era cosa de quien se acordaba, y las líneas de registro no distinguían una petición de
otra. Ahora:

- **Un identificador por petición** (`X-Request-ID`): si el cliente lo manda, se respeta (saneado: sin
  saltos de línea ni caracteres raros); si no, se genera. Viaja en la cabecera de la respuesta, en
  **todas** las líneas de registro de esa petición y en la fila de `ejecuciones` que genera. Con dos
  personas usando el portal, «el informe falló» y «la ejecución que falló» dejan de ser dos cosas que
  hay que emparejar por la hora.
- **Una línea por petición** con método, ruta, estado y milisegundos. Se deja de duplicar con el
  registro de accesos de uvicorn (que se silencia): dos líneas por petición no ayudan a nadie. Los
  latidos de `/api/salud` van a nivel `DEBUG`, para que no tapen lo que importa.
- **`LOG_FORMATO=json`**: una línea JSON por registro (`instante`, `nivel`, `registro`,
  `id_peticion`, `mensaje`, y el rastro si hay excepción) para que lo lea un programa. Por defecto,
  texto legible con el identificador entre corchetes.
- **`ejecuciones.cobertura`**: el veredicto en claro (`completa`, `parcial`) al lado del texto libre de
  `detalle`. Antes «¿cuántos informes salieron incompletos?» exigía interpretar un texto; ahora es una
  consulta.
- **Métricas** (`GET /api/interno/metricas?dias=7`, sólo rol interno): total, por estado, errores,
  informes incompletos, cuántos salieron de caché, tiempo medio y peor, por módulo y por empresa. Se
  calcula con dos consultas agrupadas portables a los dos motores y se compone en Python; la media por
  módulo va **ponderada** por número de ejecuciones (sumar medias de estados distintos daría un número
  falso). Ojo al leerlas: el inicio de sesión **también** se registra como ejecución (módulo `login`).
- **Avisos** (tabla `avisos`, `GET /api/interno/avisos`, `POST /api/interno/avisos/atender`): se apunta
  un aviso cuando un informe sale con `cobertura=parcial` o falla (`error_calculo`, `error_erp`). Los
  repetidos del mismo tipo/empresa/ejercicio/módulo **se agrupan** (contador `veces`, no 200 filas) y
  se cierran a mano, dejando constancia de quién. `/api/salud` publica **cuántos hay sin atender**: es
  el número que puede vigilar una monitorización sin ver datos de nadie.
- Lo que **no** se ha hecho, a propósito: correo o webhook. No hay destino configurado, y un aviso que
  no llega a nadie es peor que uno que está a la vista. Cuando haya destino se añade en un sitio
  (`app/alertas.py`) sin tocar el panel.



**Fase 6 — el catálogo de análisis, del informe a la cartera (hecho y medido, 27/09/2026)**

La mitad «declarativa» de la Fase 6 **ya estaba** en `app/modulos/analisis.py`: 32 comprobaciones
declaradas como datos (`id`, familia, título, qué comprueba, cómo se calcula, función evaluadora), en
cuatro niveles de semáforo, con los fallos de una regla aislados de las demás y los umbrales en
constantes del principio del fichero. Lo que faltaba era la **capa de producto** alrededor:

- **`GET /api/analisis?cod_empresa&year[&familia][&nivel][&solo_cache]`**: el semáforo en JSON y **sin el HTML** del
  informe, que es lo que necesita una pantalla con 32 fichas. Las familias y los niveles válidos los
  declara el propio módulo (`FAMILIAS`, `NIVELES`): un filtro inventado es un 400 con la lista de los
  que valen, no un resultado vacío. Con **`solo_cache=true`** no le pide nada al ERP: los ejercicios
  que falten salen en `meta.faltantes` y en los avisos. Se añadió porque consultar el semáforo de un
  ejercicio sin cargar dejaba la petición esperando al ERP (minutos por ejercicio, y un 429 si se
  insiste): pedirlo ahora es una decisión explícita, y es lo que usan la cartera y la previsualización.
- **Los filtros ahora filtran de verdad.** `familia` estaba declarado en `PARAMETROS`… y no se usaba en
  ninguna parte: el portal podía pedir `familia=financiero` y recibir las 32 comprobaciones igual.
  Ahora el resultado trae `seleccion` (lo que pasa el filtro), `filtro` (qué se aplicó y cuántas
  quedaron fuera) y el **resumen intacto**: el semáforo cuenta siempre todas las comprobaciones, si se
  recortara con el filtro estaría mintiendo.
- **`data.umbrales`**: los criterios aplicados con su unidad, su **rango admitido** y para qué son
  (347, concentración, antigüedad, endeudamiento, tipo del Impuesto de Sociedades, límites de auditoría),
  con `origen: defecto|empresa`. El informe no esconde con qué se le mide: lo publica, y marca el
  criterio que se ha pactado con ese cliente — que es lo que permite discutir un rojo sin abrir el
  código.
- **`GET /api/interno/cartera?year&limite&desde`** (sólo rol interno): la vista que convierte el
  despacho en asesoría — qué clientes tienen el semáforo en rojo, por cuánto y por qué, ordenados por
  gravedad. Con 391 clientes eso sólo es posible con dos decisiones: **no se le pide nada al ERP** (sólo
  se miran los ejercicios ya cargados; con el ERP en medio serían horas y un 429) y **se hace por
  tandas** (`limite`/`desde`, con `pendientes` declarado). Un cliente sin el ejercicio cargado se cuenta
  en `sin_el_ejercicio`/`sin_datos`, no se rellena.
- **`servicio.ejecutar_solo_cache(...)`**: el camino sin ERP, explícito en el código. Si un ejercicio no
  está en la caché, sale en `meta.faltantes` y en los avisos («no se han pedido al ERP estos
  ejercicios…»), para que un ejercicio sin cargar no se confunda con un ejercicio sin contabilidad.
- **Aviso `analisis_rojo`**: el contrato de módulos gana un hook opcional (`avisos_de_datos(datos)`) y
  `analisis` lo usa para que un rojo quede apuntado en la tabla de avisos —agrupado por empresa y
  ejercicio, como los demás— sin que el servicio tenga que conocer sus reglas. Sin esto, un rojo sólo
  existe si alguien abre el informe.

**Hallazgo de la Fase 6** (lo destapó la cartera, no una auditoría): con un ejercicio **sin apuntes**, 12
comprobaciones salían en **verde**. Varias reglas buscan ausencias («no hay facturas repetidas», «sin
saldos con socios», «sin deudas con Hacienda»), y no encontrar nada es correcto en un ejercicio con
datos… pero decir «todo bien» de un ejercicio del que no se sabe nada es justo lo que la casa no hace.
Ahora, sin apuntes, todas las comprobaciones salen en gris con el motivo. Está fijado en una prueba.

**Criterios de análisis ajustados por cliente (Fase 6, 27/09/2026)**

Los umbrales eran **constantes del módulo**: cambiar el 90 de antigüedad era editar código, desplegar y
cambiar el criterio a los 391 clientes a la vez. Un cliente con actividad estacional no aguanta el mismo
saldo viejo que una industrial, y discutir un rojo exige poder decir «se le mide con el criterio que
pactamos, no con el general».

- **Se guarda sólo lo que se aparta del general**, una fila por empresa y criterio (`umbrales_empresa`,
  migración `0003`, con quién y cuándo). Sin fila se aplican los valores de por defecto: migrar no
  cambia ningún informe, y añadir un criterio nuevo al catálogo no obliga a rellenar nada — ni se
  duplica el valor general en 391 filas, que es como envejecen estas tablas.
- **El rango lo declara el propio catálogo** (`ESQUEMA_UMBRALES`: unidad, mínimo, máximo y si es entero).
  La validación vive en el caso de uso, así que ninguna pantalla puede guardar un 300% de concentración:
  fuera de rango es un 400 y la empresa se queda como estaba. El rango se publica, así que el panel no
  tiene que replicarlo.
- **El ajuste manda en el cálculo, no en la ficha.** Las reglas leen los criterios del contexto, y hay
  pruebas que lo miden en los dos sentidos: subir el umbral del 347 deja la regla en verde y bajarlo la
  deja en naranja; el tipo del Impuesto de Sociedades del 25% cambia la estimación del 202; bajando dos
  límites de auditoría la regla pasa de «no se puede determinar» a «hay que auditarse».
- **Los criterios viajan en el contexto, no se consultan desde el dominio.** El módulo no puede tocar la
  base de datos —lo comprueba `test_arquitectura`—, así que el servicio añade `umbrales_empresa` al
  contexto y el módulo mezcla esos ajustes con sus valores por defecto. Consecuencia útil: el catálogo
  sigue calculando sin base de datos (pruebas, informes sueltos) y una fila mal metida en la tabla
  **se ignora** en vez de tumbar el informe; está fijado en una prueba.
- **`GET/POST /api/interno/umbrales` y `GET /api/interno/umbrales/ajustados`** (sólo rol interno): ver
  con qué se mide un cliente, ajustarlo (con `valor` vacío se vuelve al general) y ver de un vistazo qué
  clientes tienen criterios propios. Ese último listado incluye el valor general al lado: si media
  cartera tiene el mismo criterio cambiado, el que está mal es el general.

**Pendiente de la Fase 6**: acercarse a los ~50 análisis (hay 32), dar destino a los avisos (correo o
Teams, en `app/alertas.py`) y el frontal que pinte el semáforo y ajuste los criterios (Fase 5).

## 5. Plan por fases (el orden es por riesgo, no por vistosidad)

| Fase | Trabajo | Por qué antes que lo siguiente | Tamaño |
|---|---|---|---|
| **0** ✅ | pytest + pyproject + ruff/mypy + CI + datos sintéticos | Sin red de seguridad, nada de lo demás se puede verificar | hecho |
| **1** ✅ | Contrato (Pydantic), formato único de error, capas `api → aplicacion → dominio`, CORS cerrado, ruta muerta y verificadores reparados | Era la deuda que más frenaba todo lo demás; hecho sin romper el portal | hecho |
| **2** ✅ | Estado fuera del proceso: intentos y trabajos a la base de datos, `SECRET_KEY` obligatoria y el número de procesos declarado y comprobado | Es lo que decide si la plataforma puede escalar a más de un proceso | hecho |
| **3** ✅ | Datos y continuidad: migraciones con alembic ✅, copia de seguridad del PostgreSQL de Coolify **con restauración probada** ✅, entorno de previsualización con `APICON_SOLO_CACHE=1` ✅ (y producción leyendo el ERP) | Un fallo de datos del cliente no se arregla con código | hecho |
| **4** ✅ | Observabilidad: identificador de petición (`X-Request-ID`) en las respuestas, en las líneas de registro y en `ejecuciones`; `LOG_FORMATO=json`; `GET /api/interno/metricas`; tabla `avisos` con `cobertura_parcial`/`error_calculo`/`error_erp`, agrupando repetidos y con `/api/salud` publicando los pendientes | Hace visibles los fallos que hoy sólo se ven si alguien mira | hecho |
| **5** | Frontend: partir `app.js` en módulos ES y probar las funciones puras (sin framework); valorar Vite+Vue/React **sólo** cuando lleguen los ~50 análisis con semáforo | El estado de la UI se complica de verdad ahí, no antes | 2 días |
| **6** ✅ | Producto: el catálogo declarativo de análisis (32 reglas, ya existía) **más** su capa de producto: `GET /api/analisis` con filtros y **criterios ajustables por cliente**, `GET /api/interno/cartera` (semáforo de todos los clientes, sólo caché), aviso `analisis_rojo` y camino sin ERP (`ejecutar_solo_cache`) | Es el salto a «plataforma de asesoría» que pidió ABGA, y encaja sin tocar el borde | hecho (queda: acercarse a los ~50 análisis y pintar el semáforo en el frontal) |
| **7** ✅ | Tipos del dominio de informes: los 14 ficheros de `app.modulos` compilan sin la excepción de mypy y hay una prueba que renderiza los 13 informes **sin** datos del cliente | Era el último punto de la tabla de arriba, y en esa excepción se escondía un fallo visible (Proyecciones servía el cuerpo dentro de una tupla) | hecho |

**Lo que no se va a hacer** (y por qué): microservicios, colas o Kubernetes (un contenedor y un
PostgreSQL son lo correcto para este tamaño y este equipo); ORM completo sobre el SQL actual (es
pequeño, ya es portable y está probado en los dos motores: el coste no compensa, lo que faltan son
repositorios tipados); reescribir el frontend antes de que crezca.

## 6. Reglas que la suite hace cumplir

1. **Ninguna prueba habla con el ERP.** 200 s por ejercicio, cuota real y el sistema en producción
   del cliente: se prueba con fixtures o con datos sintéticos.
2. **Ninguna prueba escribe en la base de desarrollo**: cada una usa un directorio temporal.
3. **Ni un dato del cliente en las pruebas ni en git**: `fixtures/`, `data/`, `.env` y `salidas/`
   están fuera del control de versiones, y `verificar_secretos.py` lo comprueba en cada ejecución.
4. **Un informe nuevo no está terminado hasta que su prueba con datos sintéticos pasa en la CI**,
   además de la comprobación contra los fixtures reales.
5. **Un módulo que calcula una cifra que otro módulo ya calcula se contrasta con él**: el error
   del libro de retenciones pasó 152 comprobaciones verdes porque el verificador usaba la misma
   regla equivocada.
6. **Las capas se comprueban, no se confían**: `tests/test_arquitectura.py` lee los `import` reales
   (con `ast`) y falla si la capa HTTP toca la base de datos, si el dominio importa infraestructura,
   si la aplicación depende de HTTP o si `main.py` crece. Comprobado inyectando tres violaciones a
   propósito: las tres saltan. Esa regla tiene consecuencia práctica: los criterios de análisis por
   cliente llegan al módulo **por el contexto** (`servicio` los lee de la base), no consultándolos
   desde el dominio.

## 7. Cómo se comprueba que esto sigue siendo verdad

```bash
make           # ayuda
make instalar  # dependencias de desarrollo
make verificar # lint + tipos + toda la suite  ← lo que hay que tener en verde
make rapido    # lo que corre la CI, sin datos del cliente
make reales    # contra los fixtures del ERP
make cobertura # cobertura del dominio
```
