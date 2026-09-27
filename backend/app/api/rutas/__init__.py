"""Routers de la API, uno por recurso.

El orden de montaje importa poco (las rutas son distintas), pero se mantiene agrupado para que el
OpenAPI salga ordenado por recurso: sesión, catálogo, informes y panel interno.
"""

from . import catalogo, informes, interno, sesion

ROUTERS = (sesion.router, catalogo.router, informes.router, interno.router)

__all__ = ["ROUTERS", "catalogo", "informes", "interno", "sesion"]
