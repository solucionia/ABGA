"""Esquema de la base de datos, escrito una sola vez para SQLite y PostgreSQL.

Los tipos (`TEXT`, `INTEGER`, `REAL`) son válidos en los dos motores; `bd.traducir()` convierte
el autoincremental de SQLite en `BIGSERIAL` cuando el motor es PostgreSQL.

Ojo con las bases ya creadas: `CREATE TABLE IF NOT EXISTS` **no añade columnas** a una tabla que ya
existe, así que toda columna nueva va además en `MIGRACIONES` y `migrar()` la aplica al conectar.
"""

ESQUEMA = """
CREATE TABLE IF NOT EXISTS apuntes (
    empresa TEXT NOT NULL,
    ejercicio INTEGER NOT NULL,
    asientos_json TEXT NOT NULL,
    n_asientos INTEGER NOT NULL,
    n_lineas INTEGER NOT NULL,
    resultados_totales INTEGER,
    cobertura TEXT NOT NULL,
    segundos REAL,
    actualizado TEXT NOT NULL,
    PRIMARY KEY (empresa, ejercicio)
);
CREATE TABLE IF NOT EXISTS tokens (
    empresa TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    expira_en TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calc_cache (
    clave TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usuarios (
    email TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    rol TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS empresas (
    cod_empresa TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    ejercicio_inicio INTEGER,
    notas TEXT,
    pin_hash TEXT
);
CREATE TABLE IF NOT EXISTS permisos (
    email TEXT NOT NULL,
    cod_empresa TEXT NOT NULL,
    PRIMARY KEY (email, cod_empresa)
);
CREATE TABLE IF NOT EXISTS ejecuciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instante TEXT NOT NULL,
    cod_empresa TEXT NOT NULL,
    ejercicio INTEGER,
    modulos TEXT NOT NULL,
    origen TEXT NOT NULL,
    email TEXT,
    segundos REAL,
    estado TEXT NOT NULL,
    desde_cache INTEGER NOT NULL DEFAULT 0,
    detalle TEXT,
    importes TEXT
);
CREATE INDEX IF NOT EXISTS idx_ejecuciones_emp ON ejecuciones (cod_empresa, instante DESC);
"""

# Columnas añadidas después de que existieran las tablas. Se aplican una a una y si la columna ya
# está, el error se ignora: es la forma barata de migrar sin una herramienta de migraciones.
MIGRACIONES = (
    "ALTER TABLE empresas ADD COLUMN pin_hash TEXT",
)


def _tiene_columna(con, tabla: str, columna: str) -> bool:
    """¿Está ya la columna? Se pregunta antes de tocar la tabla (ver `migrar`)."""
    if getattr(con, "postgres", False):
        fila = con.execute("SELECT 1 FROM information_schema.columns "
                           "WHERE table_name=? AND column_name=?", (tabla, columna)).fetchone()
        return fila is not None
    for fila in con.execute(f"PRAGMA table_info({tabla})").fetchall():
        if fila[1] == columna:
            return True
    return False


def migrar(con) -> None:
    """Pone al día una base que ya existía (la creación sola no toca tablas viejas).

    Se comprueba **antes** de alterar, y no es un detalle: un `ALTER TABLE` necesita bloqueo
    exclusivo, así que si otra conexión tiene una transacción abierta la migración se queda
    esperando y **deja la aplicación colgada** (pasó probando en modo producción: el login se
    quedó a 30 s sin responder). Con la columna ya puesta no se toca la tabla.
    """
    for sentencia in MIGRACIONES:
        palabras = sentencia.split()
        tabla, columna = palabras[2], palabras[5]
        if _tiene_columna(con, tabla, columna):
            continue
        try:
            con.execute(sentencia)
            con.commit()
        except Exception:
            # En PostgreSQL un error aborta la transacción: hay que deshacerla o el siguiente
            # commit falla.
            con.rollback()
