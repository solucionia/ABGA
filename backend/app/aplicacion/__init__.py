"""Capa de aplicación: los casos de uso, sin saber nada de HTTP.

Aquí vive la decisión (qué se comprueba, en qué orden, con qué consecuencia), no el transporte. El
router valida el formato, resuelve la sesión y traduce la respuesta; esta capa recibe datos
normales y lanza `ErrorPlataforma` con el estado que corresponde.

Consecuencia buscada: los casos de uso se pueden ejecutar desde un cronjob, un script o un test sin
levantar un servidor ni simular una petición HTTP.
"""
