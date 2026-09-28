"""La caché caducada se sirve al momento y se refresca detrás, sin bloquear la petición.

Antes, un panel abierto con el TTL pasado esperaba al ERP **dentro** de la petición: la misma
llamada que contesta en milisegundos con caché fresca se quedaba dos minutos (y en la práctica
se cortaba) para enseñar un dato que ya estaba en la base. Aquí se mide justo eso: que con
caché caducada no vuelva a tocarse el ERP en la petición, que se declare `caducado` y que la
recarga salga como trabajo en segundo plano.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app import cache, config, trabajos
from tests.conftest import EMPRESA, ENTORNO_DE_PRUEBA, Portal, escribir_env


def envejecer(year: int, dias: int = 40) -> None:
    """Deja la caché de ese ejercicio fuera del TTL (43.200 s = 12 h en el defecto)."""
    antiguo = (datetime.now(UTC) - timedelta(days=dias)).isoformat()
    con = cache.conectar()
    con.execute("UPDATE apuntes SET actualizado=? WHERE empresa=? AND ejercicio=?",
                (antiguo, EMPRESA, int(year)))
    con.commit()


def _pedidos(respuesta: Any) -> list[int]:
    """Ejercicios que pidió el panel en esa llamada (las claves del JSON son texto)."""
    return sorted(int(y) for y in respuesta.json()["meta"]["ejercicios"])


def test_una_caché_caducada_se_sirve_sin_volver_al_erp(portal: Portal) -> None:
    assert portal.entrar_como_admin().status_code == 200
    primera = portal.api.get("/api/dashboard", params={"cod_empresa": EMPRESA, "year": 2025})
    assert primera.status_code == 200
    assert portal.erp.n_llamadas > 0, "la primera vez hay que leer el ERP"
    pedidos = _pedidos(primera)
    assert pedidos, "el panel pide varios ejercicios, no sólo el que se ve"
    for ejercicio in pedidos:
        envejecer(ejercicio)
    llamadas_antes = portal.erp.n_llamadas

    inicio = time.perf_counter()
    segunda = portal.api.get("/api/dashboard", params={"cod_empresa": EMPRESA, "year": 2025})
    tarda = time.perf_counter() - inicio

    assert segunda.status_code == 200
    assert portal.erp.n_llamadas == llamadas_antes, "con caché caducada no se toca el ERP"
    meta = segunda.json()["meta"]
    assert meta["desde_cache"] is True
    assert sorted(int(y) for y in meta["caducados"]) == pedidos
    for ejercicio in pedidos:
        assert meta["ejercicios"][str(ejercicio)]["caducado"] is True, f"falta caducado en {ejercicio}"
    assert tarda < 5, f"la petición se quedó esperando {tarda:.1f} s"


def test_forzar_si_vuelve_al_erp(portal: Portal) -> None:
    assert portal.entrar_como_admin().status_code == 200
    primera = portal.api.get("/api/dashboard", params={"cod_empresa": EMPRESA, "year": 2025})
    assert primera.status_code == 200
    for ejercicio in _pedidos(primera):
        envejecer(ejercicio)
    llamadas_antes = portal.erp.n_llamadas

    forzada = portal.api.get("/api/dashboard",
                             params={"cod_empresa": EMPRESA, "year": 2025, "forzar": "true"})

    assert forzada.status_code == 200
    assert portal.erp.n_llamadas > llamadas_antes, "con forzar hay que leer el ERP otra vez"
    assert forzada.json()["meta"]["caducados"] == []


def test_el_refresco_se_programa_como_trabajo(portal: Portal, entorno: Path) -> None:
    """La recarga no es magia: queda un trabajo de tipo `carga` que se ejecuta en un hilo."""
    claves = dict(ENTORNO_DE_PRUEBA, REFRESCO_AUTOMATICO="1")
    escribir_env(entorno, **claves)
    config.cargar_config.cache_clear()

    assert portal.entrar_como_admin().status_code == 200
    primera = portal.api.get("/api/dashboard", params={"cod_empresa": EMPRESA, "year": 2025})
    assert primera.status_code == 200
    pedidos = _pedidos(primera)
    for ejercicio in pedidos:
        envejecer(ejercicio)

    respuesta = portal.api.get("/api/dashboard", params={"cod_empresa": EMPRESA, "year": 2025})
    assert respuesta.status_code == 200

    cargas = [t for t in trabajos.listar(20) if t["tipo"] == "carga"]
    assert cargas, "con REFRESCO_AUTOMATICO la recarga tiene que quedar programada"
    assert cargas[0]["cod_empresa"] == EMPRESA

    # El ERP está simulado, así que el hilo termina enseguida: se espera a que no quede ninguno
    # en curso para que el hilo no siga corriendo cuando la prueba termine (rompería el doble).
    for _ in range(60):
        if not trabajos.cargas_en_curso():
            break
        time.sleep(0.1)
    assert not trabajos.cargas_en_curso(), "la recarga no terminó"
    # Se vuelve a leer: lo que se listó arriba era una instantánea con el trabajo en marcha.
    terminadas = [t for t in trabajos.listar(20)
                  if t["tipo"] == "carga" and t["cod_empresa"] == EMPRESA]
    fallidos = [t for t in terminadas if t["estado"] != "hecho"]
    assert not fallidos, f"la recarga terminó mal: {fallidos}"


def test_un_ejercicio_nunca_leido_se_sigue_pidiendo_al_erp(portal: Portal) -> None:
    """Sin caché no hay nada que servir: ése sí que va al ERP (y si falla, se declara)."""
    assert portal.entrar_como_admin().status_code == 200
    cache.invalidar(EMPRESA)
    llamadas_antes = portal.erp.n_llamadas

    respuesta = portal.api.get("/api/dashboard", params={"cod_empresa": EMPRESA, "year": 2025})

    assert respuesta.status_code == 200
    assert portal.erp.n_llamadas > llamadas_antes
    assert respuesta.json()["meta"]["caducados"] == []
