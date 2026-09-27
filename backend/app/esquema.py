"""Contrato del esquema: qué tablas tiene que tener una base de la plataforma.

La definición del esquema (el DDL) vive en las **migraciones** (`backend/migraciones/versions/`),
que son la única vía para crear o cambiar la base: una base nueva se construye aplicándolas y una
base vieja se pone al día igual. Aquí queda sólo la lista de tablas esperadas, que usan los
verificadores y las pruebas, y que una prueba contrasta con lo que dejan las migraciones — así no
pueden separarse lo que se crea y lo que se espera.
"""

TABLAS = (
    "apuntes",
    "avisos",
    "calc_cache",
    "ejecuciones",
    "empresas",
    "intentos",
    "permisos",
    "tokens",
    "trabajos",
    "umbrales_empresa",
    "usuarios",
)

# Tablas sin las que la plataforma no puede funcionar (una copia que no las traiga no sirve).
IMPRESCINDIBLES = ("empresas", "usuarios", "permisos", "ejecuciones")
