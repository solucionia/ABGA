# Arquitectura de la plataforma ABGA

Documento de trabajo técnico. Dice **qué hay hoy**, **qué se ha medido**, **hacia dónde va** y
**en qué orden**, para que cualquier decisión posterior se pueda discutir sobre hechos y no sobre
impresiones. Se lee junto al `README.md` (que explica el producto) y a
`backend/CONTRATO-MODULOS.md` (que explica cómo se añade un informe).

Última revisión: **Fase 0 cerrada** (red de seguridad: pruebas, tipos, estilo y CI).

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
| 5 | Tipos: los 13 módulos de informe siguen calculando sobre `dict`/`object` sin tipar (es lo único que queda en la lista de excepciones de mypy) | `pyproject.toml`, `[tool.mypy.overrides]` |

### Cerrado en la Fase 1 (contrato, capas y errores)

| Antes | Ahora |
|---|---|
| `main.py` de **581 líneas** mezclando transporte, negocio y SQL | **74 líneas** que sólo montan routers, manejadores y estáticos. Los casos de uso viven en `app/aplicacion/`, los contratos en `app/api/esquemas.py` |
| `POST /api/interno/usuarios` declarado **dos veces** (la segunda, inalcanzable) | Un solo endpoint, y una prueba que falla si vuelve a haber rutas duplicadas |
| 24 rutas con `payload: dict = Body(...)`; `/docs` sin contrato y un año no numérico daba **500** | **33 esquemas** Pydantic publicados en el OpenAPI; el año fuera de rango o no numérico responde **422** con el campo que falla. Un campo de más también es error |
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
| Contrato tipado | `app/api/esquemas.py`: 10 modelos de petición y 23 de respuesta, **33 esquemas publicados** en el OpenAPI. El año fuera de rango o no numérico responde **422** con el campo que falla; un campo de más también es error (`extra="forbid"`) |
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

**Lo que falta y necesita decisión**:

| Pendiente | Qué falta |
|---|---|
| Programar la copia en `abga-postgres` | Crear el horario (propuesta: diaria a las 03:00, retención 7 copias) y lanzar un «Backup Now». Se puede hacer por la API de Coolify (requiere aprobar el comando) o en su UI |
| Copia fuera del servidor | Si el servidor se pierde, se pierde también `/data/coolify/backups`. Para cubrirlo hace falta un destino S3-compatible (bucket + credenciales) |
| Migraciones versionadas | Sigue pendiente alembic: hoy el esquema se aplica con `CREATE TABLE IF NOT EXISTS` + `MIGRACIONES` en `conectar()` |
| Entorno de previsualización | Un segundo despliegue con `APICON_SOLO_CACHE=1` para enseñar cambios sin tocar el ERP |

## 5. Plan por fases (el orden es por riesgo, no por vistosidad)

| Fase | Trabajo | Por qué antes que lo siguiente | Tamaño |
|---|---|---|---|
| **0** ✅ | pytest + pyproject + ruff/mypy + CI + datos sintéticos | Sin red de seguridad, nada de lo demás se puede verificar | hecho |
| **1** ✅ | Contrato (Pydantic), formato único de error, capas `api → aplicacion → dominio`, CORS cerrado, ruta muerta y verificadores reparados | Era la deuda que más frenaba todo lo demás; hecho sin romper el portal | hecho |
| **2** ✅ | Estado fuera del proceso: intentos y trabajos a la base de datos, `SECRET_KEY` obligatoria y el número de procesos declarado y comprobado | Es lo que decide si la plataforma puede escalar a más de un proceso | hecho |
| **3** | Datos y continuidad: migraciones con alembic, copia de seguridad del PostgreSQL de Coolify **con restauración probada**, entorno de previsualización con `APICON_SOLO_CACHE=1` | Un fallo de datos del cliente no se arregla con código | 2-3 días |
| **4** | Observabilidad: logs estructurados con id de petición (el `codigo` del error ya es estable), métricas sobre la tabla `ejecuciones` que ya existe, alerta cuando un informe salga con `cobertura=parcial` o `error_calculo` | Hace visibles los fallos que hoy sólo se ven si alguien mira | 1 día |
| **5** | Frontend: partir `app.js` en módulos ES y probar las funciones puras (sin framework); valorar Vite+Vue/React **sólo** cuando lleguen los ~50 análisis con semáforo | El estado de la UI se complica de verdad ahí, no antes | 2 días |
| **6** | Producto: catálogo de análisis declarativo (tabla de reglas → resultado con semáforo) sobre el registro de módulos actual | Es el salto a «plataforma de asesoría» que pidió ABGA, y encaja sin tocar el borde | según alcance |

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
   propósito: las tres saltan.

## 7. Cómo se comprueba que esto sigue siendo verdad

```bash
make           # ayuda
make instalar  # dependencias de desarrollo
make verificar # lint + tipos + toda la suite  ← lo que hay que tener en verde
make rapido    # lo que corre la CI, sin datos del cliente
make reales    # contra los fixtures del ERP
make cobertura # cobertura del dominio
```
