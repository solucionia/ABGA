"""Avisos: lo que no puede pasar desapercibido.

Un informe que sale con la cobertura incompleta (el ERP no dejó leer el ejercicio entero) o que falla
al calcular ya quedaba registrado en `ejecuciones`… y ahí se quedaba: había que mirar la tabla para
enterarse. Un aviso es esa misma información **con estado**: se apunta una vez, se ve desde el panel
interno y se marca como atendido.

Dos decisiones que importan más de lo que parece:

* **Los repetidos se agrupan.** Si el ERP se cae una tarde, cada intento no puede dejar una fila:
  el aviso sube su contador (`veces`), actualiza `ultimo` y guarda el último detalle. Así «50 avisos»
  no tapa los otros cuatro que sí son distintos.
* **No hay correo ni webhook.** La plataforma no tiene por dónde avisar todavía; inventar un envío
  que nadie configura sería peor que no tenerlo. Cuando haya destino (correo, Teams, Slack) se añade
  aquí, en un sitio, y el panel no cambia.
"""

from __future__ import annotations

import logging
from typing import Any

from . import bd, cache

log = logging.getLogger("abga.alertas")

TIPOS = (
    "cobertura_parcial",   # el informe salió, pero no con todo el ejercicio leído
    "error_calculo",       # fallo de la plataforma calculando el informe
    "error_erp",           # el ERP no respondió o respondió mal
    "analisis_rojo",       # el semáforo de análisis salió con comprobaciones en rojo
)

COLUMNAS = ("tipo", "cod_empresa", "ejercicio", "modulo", "detalle", "origen", "email",
            "id_peticion", "primero", "ultimo", "veces", "atendido", "atendido_por", "atendido_en")


def _clave(tipo: str, cod_empresa: str, ejercicio: int, modulo: str) -> tuple[str, str, int, str]:
    # El ejercicio se guarda como número (0 = «sin ejercicio») para que la comparación sea igual en
    # SQLite y en PostgreSQL: comparar contra NULL con `=` no devuelve nada en ninguno de los dos.
    return tipo, str(cod_empresa), int(ejercicio or 0), str(modulo or "")


def avisar(tipo: str, *, cod_empresa: str, ejercicio: int | None = None, modulo: str = "",
           detalle: str = "", origen: str = "portal", email: str = "",
           id_peticion: str = "") -> int | None:
    """Apunta un aviso. Devuelve su id, o `None` si el tipo no es de los conocidos."""
    if tipo not in TIPOS:
        log.warning("aviso de un tipo desconocido (%s): no se apunta", tipo)
        return None
    tipo, cod_empresa, ejercicio, modulo = _clave(tipo, cod_empresa, ejercicio or 0, modulo)
    con = cache.conectar()
    ahora = cache.ahora()

    abierto = con.execute(
        "SELECT id FROM avisos WHERE tipo=? AND cod_empresa=? AND ejercicio=? AND modulo=?"
        " AND atendido=0 ORDER BY id DESC LIMIT 1",
        (tipo, cod_empresa, ejercicio, modulo)).fetchone()

    if abierto:
        identificador = int(abierto["id"])
        con.execute(
            "UPDATE avisos SET veces=veces+1, ultimo=?, detalle=?, id_peticion=?, origen=?, email=?"
            " WHERE id=?",
            (ahora, detalle[:2000], id_peticion, origen, email, identificador))
        con.commit()
        log.warning("aviso %s repetido (%s/%s %s): van %s", tipo, cod_empresa, ejercicio, modulo,
                    _veces(identificador))
        return identificador

    identificador = bd.insertar_devolviendo_id(
        "avisos",
        ("tipo", "cod_empresa", "ejercicio", "modulo", "detalle", "origen", "email",
         "id_peticion", "primero", "ultimo", "veces", "atendido"),
        (tipo, cod_empresa, ejercicio, modulo, detalle[:2000], origen, email, id_peticion,
         ahora, ahora, 1, 0))
    # A nivel ERROR lo que dejó un informe sin salir; a nivel WARNING lo que salió incompleto.
    (log.error if tipo.startswith("error") else log.warning)(
        "aviso %s en %s/%s (%s): %s", tipo, cod_empresa, ejercicio or "sin ejercicio", modulo,
        detalle[:300])
    return int(identificador)


def _veces(identificador: int) -> int:
    fila = cache.conectar().execute("SELECT veces FROM avisos WHERE id=?", (int(identificador),)).fetchone()
    return int(fila["veces"]) if fila else 0


def pendientes(*, limite: int = 200) -> list[dict[str, Any]]:
    """Los avisos sin atender, los más recientes primero."""
    filas = cache.conectar().execute(
        "SELECT * FROM avisos WHERE atendido=0 ORDER BY ultimo DESC, id DESC LIMIT ?",
        (int(limite),)).fetchall()
    return [dict(f) for f in filas]


def historico(*, limite: int = 200) -> list[dict[str, Any]]:
    """Todos, atendidos o no (lo que enseña el panel interno)."""
    filas = cache.conectar().execute(
        "SELECT * FROM avisos ORDER BY atendido ASC, ultimo DESC LIMIT ?", (int(limite),)).fetchall()
    return [dict(f) for f in filas]


def contar() -> int:
    """Cuántos avisos están sin atender (el número que va en el latido de salud y en el panel)."""
    fila = cache.conectar().execute(
        "SELECT COUNT(*) AS n FROM avisos WHERE atendido=0").fetchone()
    return int(fila["n"]) if fila else 0


def atender(identificador: int, actor: str) -> bool:
    """Marca un aviso como atendido. Devuelve `False` si no existe o ya lo estaba."""
    con = cache.conectar()
    cursor = con.execute(
        "UPDATE avisos SET atendido=1, atendido_por=?, atendido_en=? WHERE id=? AND atendido=0",
        (str(actor or ""), cache.ahora(), int(identificador)))
    con.commit()
    hecho = bool(cursor.rowcount)
    if hecho:
        log.info("aviso %s atendido por %s", identificador, actor or "(sin nombre)")
    return hecho
