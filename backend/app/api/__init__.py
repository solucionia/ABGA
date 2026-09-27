"""Capa HTTP: routers, contratos (Pydantic) y dependencias de permisos.

Regla de la capa: aquí sólo se **valida, autoriza y delega**. Ninguna consulta a la base de datos
ni ninguna regla de negocio: eso vive en `app/aplicacion/` (casos de uso) y en `app/servicio.py`.
"""
