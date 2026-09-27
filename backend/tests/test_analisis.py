"""Pruebas del catálogo de análisis (Fase 6): filtros, umbrales, avisos y cartera.

El catálogo en sí (33 reglas y el motor) ya venía de antes; lo que se prueba aquí es la capa de
producto que se le ha añadido: el recorte por familia y nivel, los umbrales a la vista, el aviso de
rojos y la cartera de clientes del panel interno.

Dos cosas que se comprueban a propósito y no son de adorno:

* que **una regla rota no tumba el catálogo** (es lo que hace que se pueda añadir una regla sin
  miedo a dejar el informe en blanco);
* que **la cartera no le pide nada al ERP** (con 391 clientes, pedirlo sería horas y un 429). Eso se
  comprueba con el contador de llamadas del ERP simulado, no confiando en el comentario.
"""

from __future__ import annotations

import pytest

from app import alertas, cache, db, servicio
from app.modulos import analisis as mod
from tests import sintetico
from tests.conftest import (
    EMPRESA,
    EMPRESA_AJENA,
    ErpSimulado,
    Portal,
)

# ---------------------------------------------------------------- utilidades

def analisis_de(cod_empresa: str = EMPRESA, year: int = 2025, **params: object) -> dict:
    """Calcula «Análisis y alertas» con el ejercicio y el anterior ya en la caché.

    Se cargan en la caché directamente (no se pide al ERP): lo que se prueba aquí es el catálogo,
    no el camino del ERP, y así ninguna prueba depende de la red.
    """
    en_cache(cod_empresa, year)
    en_cache(cod_empresa, year - 1)
    r = servicio.ejecutar("analisis", cod_empresa=cod_empresa, year=year,
                          params=dict(params), email="pruebas@abga.test")
    assert r.status == "ok", r.error
    return r.data


def en_cache(cod_empresa: str, year: int, asientos: list[dict] | None = None) -> None:
    """Deja un ejercicio en la caché **sin pasar por el ERP** (como si ya estuviera cargado)."""
    datos = sintetico.anio(year) if asientos is None else asientos
    cache.guardar_apuntes(cod_empresa, year, datos, resultados_totales=len(datos),
                          cobertura=f"completa ({len(datos)} asientos)", segundos=0.01)


# ---------------------------------------------------------------- el catálogo declara

def test_cada_regla_declara_que_comprueba_y_como(entorno: object) -> None:
    """Una regla sin `comprueba`/`como` es una cifra sin explicación: no puede entrar."""
    ids = [r.id for r in mod.REGLAS]
    assert len(ids) == len(set(ids)), "hay identificadores de regla repetidos"
    familias = {clave for clave, _ in mod.FAMILIAS}
    for r in mod.REGLAS:
        assert r.titulo.strip() and r.comprueba.strip() and r.como.strip(), f"regla incompleta: {r.id}"
        assert r.familia in familias, f"familia desconocida en {r.id}: {r.familia}"
        assert callable(r.evaluar)


def test_todas_las_reglas_salen_en_el_resultado(entorno: object) -> None:
    datos = analisis_de()
    assert len(datos["hallazgos"]) == len(mod.REGLAS)
    assert {h["id"] for h in datos["hallazgos"]} == {r.id for r in mod.REGLAS}
    assert datos["resumen"]["n_total"] == len(mod.REGLAS)
    # el orden es por gravedad: primero lo que hay que mirar
    niveles = [h["nivel"] for h in datos["hallazgos"]]
    assert niveles == sorted(niveles, key=lambda n: mod.ORDEN_NIVEL[n])


def test_una_regla_rota_no_tumba_el_catalogo(entorno: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """El motor aísla el fallo de una regla: sale como no evaluable y las demás siguen."""
    rota = mod.REGLAS[0]
    monkeypatch.setattr(rota, "evaluar", lambda c: 1 / 0)

    datos = analisis_de()
    assert len(datos["hallazgos"]) == len(mod.REGLAS)
    hallazgo = next(h for h in datos["hallazgos"] if h["id"] == rota.id)
    assert hallazgo["nivel"] == mod.NO_EVALUABLE
    assert "no se ha podido ejecutar" in hallazgo["detalle"]
    assert "ZeroDivisionError" in hallazgo["detalle"]
    assert datos["resumen"]["n_evaluables"] == len(mod.REGLAS) - len(
        [h for h in datos["hallazgos"] if h["nivel"] == mod.NO_EVALUABLE])


# ---------------------------------------------------------------- filtros y umbrales

def test_el_filtro_por_familia_recorta_sin_tocar_el_semaforo(entorno: object) -> None:
    """El semáforo cuenta todas las comprobaciones: si contara lo filtrado, mentiría."""
    todas = analisis_de()
    financiero = analisis_de(familia="financiero")

    assert financiero["resumen"] == todas["resumen"]
    assert financiero["filtro"]["aplicado"] is True
    assert financiero["filtro"]["n_total"] == len(mod.REGLAS)
    assert financiero["filtro"]["n_seleccionados"] == len(financiero["seleccion"])
    assert financiero["seleccion"], "la familia financiera debería tener reglas"
    assert {h["familia"] for h in financiero["seleccion"]} == {"financiero"}
    assert len(financiero["hallazgos"]) == len(mod.REGLAS)


def test_el_filtro_por_nivel_cuadra_con_el_resumen(entorno: object) -> None:
    datos = analisis_de(nivel="alerta")
    assert {h["nivel"] for h in datos["seleccion"]} <= {"alerta"}
    assert len(datos["seleccion"]) == datos["resumen"]["n_rojo"]
    # y hay rojos de verdad en el ejercicio sintético (el periodo medio de cobro se dispara)
    assert datos["resumen"]["n_rojo"] > 0


def test_los_dos_filtros_a_la_vez(entorno: object) -> None:
    datos = analisis_de(familia="financiero", nivel="aviso")
    assert {h["familia"] for h in datos["seleccion"]} <= {"financiero"}
    assert {h["nivel"] for h in datos["seleccion"]} <= {"aviso"}
    assert datos["filtro"]["familia"] == "financiero" and datos["filtro"]["nivel"] == "aviso"


def test_el_modulo_no_admite_filtros_inventados(entorno: object) -> None:
    """El módulo es el último responsable: si le llega basura, no la interpreta en silencio."""
    en_cache(EMPRESA, 2025)
    en_cache(EMPRESA, 2024)
    r = servicio.ejecutar("analisis", cod_empresa=EMPRESA, year=2025,
                          params={"familia": "inventada"}, email="pruebas@abga.test")
    assert r.status == "error" and r.tipo == "calculo"
    assert "familia desconocida" in (r.error or "")


def test_los_umbrales_salen_publicados(entorno: object) -> None:
    """Cambiar un criterio es cambiar una constante de arriba, y el resultado dice cuál se aplicó."""
    u = analisis_de()["umbrales"]
    assert u["347_operaciones"]["valor"] == pytest.approx(3005.06)
    assert u["antiguedad_clientes"]["valor"] == 90
    assert u["auditoria"]["valor"]["activo"] == 2_500_000.0
    for clave, v in u.items():
        assert v["unidad"] and v["para"], f"umbral sin unidad o sin explicación: {clave}"


# ---------------------------------------------------------------- avisos de los rojos

def test_el_modulo_avisa_de_los_rojos(entorno: object) -> None:
    datos = analisis_de()
    avisos = mod.avisos_de_datos(datos)
    assert len(avisos) == 1 and avisos[0]["tipo"] == "analisis_rojo"
    assert str(datos["resumen"]["n_rojo"]) in avisos[0]["detalle"]
    assert len(avisos[0]["detalle"]) < 2_000, "el aviso no debe llevar el informe dentro"


def test_sin_apuntes_no_hay_aviso_de_rojos(entorno: object) -> None:
    """Un ejercicio sin apuntes sale en gris, no en rojo: no es una incidencia."""
    vacio = mod.calcular({2025: [], 2024: []}, {"year": 2025, "empresa": "X", "cod_empresa": "1"})
    assert vacio["resumen"]["n_rojo"] == 0
    assert mod.avisos_de_datos(vacio) == []


def test_un_ejercicio_vacio_no_sale_verde(entorno: object) -> None:
    """Sin apuntes no se puede decir «correcto»: todas las comprobaciones salen no evaluables.

    Lo destapó la cartera: una empresa sin ejercicio cargado aparecía con 12 comprobaciones en
    verde, porque varias reglas comprueban AUSENCIAS (no hay duplicados, sin saldos con socios…) y
    no encontrar nada es «correcto» en un ejercicio con datos, pero no en uno vacío.
    """
    vacio = mod.calcular({2025: [], 2024: []}, {"year": 2025, "empresa": "X", "cod_empresa": "1"})
    assert vacio["resumen"]["n_verde"] == 0 and vacio["resumen"]["n_naranja"] == 0
    assert vacio["resumen"]["n_no_evaluable"] == len(mod.REGLAS)
    assert vacio["resumen"]["nivel_global"] == mod.NO_EVALUABLE
    assert all("no hay apuntes" in h["detalle"] for h in vacio["hallazgos"])


def test_el_servicio_apunta_el_aviso_y_lo_agrupa(entorno: object) -> None:
    """Los repetidos se cuentan (`veces`), no llenan la tabla: eso ya lo hace `alertas`."""
    assert alertas.contar() == 0
    analisis_de()
    pendientes = alertas.pendientes()
    mio = [a for a in pendientes if a["tipo"] == "analisis_rojo"]
    assert len(mio) == 1
    assert mio[0]["cod_empresa"] == EMPRESA and mio[0]["ejercicio"] == 2025
    assert mio[0]["modulo"] == "analisis" and mio[0]["veces"] == 1

    analisis_de()
    pendientes = [a for a in alertas.pendientes() if a["tipo"] == "analisis_rojo"]
    assert len(pendientes) == 1, "la segunda consulta no puede dejar otro aviso"
    assert pendientes[0]["veces"] == 2


def test_un_modulo_sin_hook_no_apunta_nada(erp_simulado: ErpSimulado) -> None:
    """El aviso es opcional: la mayoría de los módulos no declara ninguno."""
    servicio.ejecutar("pyg", cod_empresa=EMPRESA, year=2025, email="pruebas@abga.test")
    assert [a for a in alertas.pendientes() if a["tipo"] == "analisis_rojo"] == []


# ---------------------------------------------------------------- el camino sin ERP

def test_solo_cache_no_le_pide_nada_al_erp(erp_simulado: ErpSimulado) -> None:
    """La propiedad que hace posible la cartera: ni una llamada al ERP, y lo que falta se declara."""
    r = servicio.ejecutar_solo_cache("analisis", cod_empresa=EMPRESA, year=2025)
    assert r.status == "ok", r.error
    assert erp_simulado.n_llamadas == 0
    assert r.meta["faltantes"] == [2024, 2025]
    assert any("sólo lee de la caché" in a for a in r.avisos)
    resumen = r.data["resumen"]
    assert resumen["n_verde"] == 0 and resumen["n_rojo"] == 0, "sin datos no se inventa nada"
    assert resumen["n_no_evaluable"] >= len(mod.REGLAS) - 2, "casi todo sale no evaluable"


def test_solo_cache_calcula_cuando_el_ejercicio_esta_cargado(erp_simulado: ErpSimulado) -> None:
    en_cache(EMPRESA, 2025)
    en_cache(EMPRESA, 2024)
    r = servicio.ejecutar_solo_cache("analisis", cod_empresa=EMPRESA, year=2025)
    assert r.status == "ok" and r.meta["faltantes"] == []
    assert erp_simulado.n_llamadas == 0
    assert r.data["n_lineas"] > 0
    assert r.meta["desde_cache"] is True


def test_solo_cache_declara_el_ejercicio_que_falta(erp_simulado: ErpSimulado) -> None:
    """El ejercicio actual está, el anterior no: lo dice en vez de sacar medio informe en gris."""
    en_cache(EMPRESA, 2025)
    r = servicio.ejecutar_solo_cache("analisis", cod_empresa=EMPRESA, year=2025)
    assert r.meta["faltantes"] == [2024]
    assert any("2024" in a for a in r.avisos)


# ---------------------------------------------------------------- API

def test_la_api_devuelve_el_semaforo_sin_html(portal: Portal) -> None:
    portal.entrar_como_admin()
    r = portal.api.get(f"/api/analisis?cod_empresa={EMPRESA}&year=2025")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["status"] == "ok"
    assert "html" not in cuerpo, "el panel no necesita el informe maquetado"
    assert len(cuerpo["data"]["hallazgos"]) == len(mod.REGLAS)
    assert cuerpo["data"]["resumen"]["n_total"] == len(mod.REGLAS)
    assert cuerpo["data"]["umbrales"]["concentracion_clientes"]["valor"] == 35.0


def test_la_api_admite_los_filtros(portal: Portal) -> None:
    portal.entrar_como_admin()
    r = portal.api.get(
        f"/api/analisis?cod_empresa={EMPRESA}&year=2025&familia=financiero&nivel=aviso")
    assert r.status_code == 200
    seleccion = r.json()["data"]["seleccion"]
    assert seleccion and {h["familia"] for h in seleccion} == {"financiero"}
    assert {h["nivel"] for h in seleccion} == {"aviso"}


@pytest.mark.parametrize("consulta", ["familia=inventada", "nivel=inventado"])
def test_la_api_rechaza_filtros_inventados(portal: Portal, consulta: str) -> None:
    portal.entrar_como_admin()
    r = portal.api.get(f"/api/analisis?cod_empresa={EMPRESA}&year=2025&{consulta}")
    assert r.status_code == 400, r.text
    assert "desconocid" in r.json()["error"]


def test_la_api_exige_sesion_y_empresa_permitida(portal: Portal) -> None:
    assert portal.api.get(f"/api/analisis?cod_empresa={EMPRESA}&year=2025").status_code == 401
    portal.entrar_como_cliente()
    assert portal.api.get(f"/api/analisis?cod_empresa={EMPRESA}&year=2025").status_code == 200
    ajena = portal.api.get(f"/api/analisis?cod_empresa={EMPRESA_AJENA}&year=2025")
    assert ajena.status_code == 403


# ---------------------------------------------------------------- cartera (panel interno)

def _cartera(*, year: int, limite: int = 30, desde: int = 0) -> dict:
    from app.aplicacion import catalogo

    return catalogo.cartera(year=year, limite=limite, desde=desde)


def test_la_cartera_solo_entra_por_lo_que_hay_en_cache(erp_simulado: ErpSimulado) -> None:
    """Ni una llamada al ERP, y los clientes que no tienen el ejercicio se cuentan, no se inventan."""
    en_cache(EMPRESA, 2025)              # entra en la cartera
    en_cache(EMPRESA_AJENA, 2024)        # tiene datos, pero de otro ejercicio
    db.crear_empresa("7777", "Cliente sin cargas, S.L.", 2018)   # ficha sin nada cargado

    c = _cartera(year=2025)
    assert erp_simulado.n_llamadas == 0
    assert [f["cod_empresa"] for f in c["filas"]] == [EMPRESA]
    assert c["totales"]["candidatas"] == 1
    assert c["totales"]["analizadas"] == 1
    assert c["totales"]["sin_el_ejercicio"] == 1
    assert c["totales"]["sin_datos"] == 1
    assert any("no se ha pedido nada al ERP" in a for a in c["avisos"])


def test_la_cartera_ordena_por_gravedad(erp_simulado: ErpSimulado) -> None:
    """Primero quien tiene rojos; un ejercicio vacío (todo en gris) va al final."""
    en_cache(EMPRESA, 2025)                       # tiene rojos (pmc, concentración…)
    en_cache(EMPRESA_AJENA, 2025, asientos=[])    # sin apuntes: todo no evaluable
    c = _cartera(year=2025)
    assert [f["cod_empresa"] for f in c["filas"]] == [EMPRESA, EMPRESA_AJENA]
    assert c["filas"][0]["n_rojo"] > 0 and c["filas"][0]["rojos"]
    assert c["filas"][1]["n_rojo"] == 0
    assert c["totales"]["en_rojo"] == 1
    assert c["totales"]["importe_riesgo"] > 0


def test_la_cartera_se_puede_pedir_por_tandas(erp_simulado: ErpSimulado) -> None:
    for cod in ("1111", "2222", "3333"):
        db.crear_empresa(cod, f"Cliente {cod}, S.L.", 2018)
        en_cache(cod, 2025)
    primera = _cartera(year=2025, limite=2, desde=0)
    assert len(primera["filas"]) == 2
    assert primera["totales"]["candidatas"] == 3 and primera["totales"]["pendientes"] == 1
    segunda = _cartera(year=2025, limite=2, desde=2)
    assert len(segunda["filas"]) == 1 and segunda["totales"]["pendientes"] == 0
    assert {f["cod_empresa"] for f in primera["filas"]}.isdisjoint(
        {f["cod_empresa"] for f in segunda["filas"]})


def test_la_api_de_cartera_es_solo_para_abga(portal: Portal) -> None:
    portal.entrar_como_cliente()
    assert portal.api.get("/api/interno/cartera?year=2025").status_code == 403
    portal.entrar_como_admin()
    r = portal.api.get("/api/interno/cartera?year=2025&limite=5")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["status"] == "ok" and cuerpo["year"] == 2025
    assert cuerpo["limite"] == 5 and isinstance(cuerpo["totales"], dict)
    assert cuerpo["avisos"], "la cartera siempre declara con qué se ha calculado"


def test_la_cartera_deja_el_aviso_de_cada_cliente_en_rojo(entorno: object) -> None:
    """El aviso es lo que hace que un rojo no dependa de que alguien abra el panel."""
    en_cache(EMPRESA, 2025)
    _cartera(year=2025, limite=1)
    rojos = [a for a in alertas.pendientes() if a["tipo"] == "analisis_rojo"]
    assert [a["cod_empresa"] for a in rojos] == [EMPRESA]
    assert rojos[0]["origen"] == "cartera"
