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
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# credenciales del ERP (nunca a git): .env con APICON_USERNAME, APICON_PASSWORD,
# APICON_CLIENT_ID, APICON_CLIENT_SECRET, APICON_EMPRESA_DEFECTO y SECRET_KEY

./.venv/bin/python scripts/init_db.py          # empresas y usuarios iniciales
./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Portal en `http://localhost:8000`. Documentación interactiva de la API en `/docs`.

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

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/api/login` · `/api/logout` | sesión (token firmado, cookie httpOnly) |
| GET | `/api/yo` · `/api/empresas` · `/api/modulos` | contexto del usuario |
| GET | `/api/dashboard?cod_empresa&year` | KPIs y series en JSON agregado (~9 KB, no los apuntes) |
| POST | `/api/informe` | genera un informe y devuelve `{status, html, data, meta, avisos}` |
| POST | `/api/refrescar` · GET `/api/trabajos/{id}` | releer del ERP en segundo plano, con progreso |
| GET | `/api/interno/resumen` | panel de ABGA: ejecuciones, caché, módulos, usuarios |
| POST | `/api/interno/cache` · `/usuarios` · `/empresas` | administración (sólo rol interno) |
| GET | `/api/salud` · `/api/cache` | diagnóstico |

El contrato de siempre se respeta: `{status:"ok", html:"<div…>", data:{…}}`, así que el HTML se
puede seguir imprimiendo o incrustar.

## Datos y caché

- Caché de apuntes por empresa y ejercicio, con TTL de 12 h. El motor lo elige `DATABASE_URL`:
  SQLite (`data/abga.sqlite3`) en local y **PostgreSQL** en producción (Coolify). El mismo SQL
  vale para los dos: la traducción vive sólo en `app/bd.py`
  (`./.venv/bin/python backend/scripts/verificar_bd.py` ejecuta el mismo recorrido en los dos
  motores y compara los resultados).
- Cobertura verificada: si el recorrido no alcanza `ResultadosTotales`, el meta del informe lo
  dice (`"cobertura": "parcial (n de m)")` y queda en el log.
- `scripts/precalentar.py` deja los ejercicios listos; pensado para un cronjob nocturno de Hermes.
- `scripts/traer_cache.py` y `scripts/traer_ejercicio.py` traen ejercicios a mano.
- `scripts/probe_*.py` son las sondas con las que se descubrió el comportamiento del ERP
  (paginación, límites, 429). No hacen falta en producción.

## Pruebas

```bash
./.venv/bin/python backend/scripts/verificar_nucleo.py    # integridad contable y maquetación
./.venv/bin/python backend/scripts/verificar_modulos.py   # todos los módulos contra datos reales
./.venv/bin/python backend/scripts/e2e_api.py http://127.0.0.1:8000   # API, permisos y avisos
```

Los fixtures de `fixtures/` son respuestas reales del ERP (empresa 6091) y están fuera de git.

## Seguridad

- Contraseñas con `scrypt`; tokens de sesión firmados con HMAC-SHA256 y caducidad.
- Cada usuario ve sólo las empresas asignadas; los informes internos exigen rol interno.
- `.env`, `data/` y `fixtures/` están en `.gitignore`. **Los exports originales de n8n contienen
  las credenciales del ERP en claro**: no se comparten ni se suben a ningún repositorio.
- Pendiente antes de abrirlo a clientes reales: cambiar las contraseñas de demostración, poner
  HTTPS por delante y decidir el dominio definitivo.
