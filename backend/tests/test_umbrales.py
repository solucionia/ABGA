"""Pruebas de los criterios de análisis ajustados por cliente.

Antes, un umbral era una constante: cambiar los 90 días de antigüedad era tocar el código y desplegar,
y el cambio valía para los 391 clientes. Ahora se ajusta por empresa y sólo se guarda lo que se aparta
del general.

Lo que se comprueba, y por qué no es de adorno:

* que el ajuste **cambia el veredicto de verdad** y no sólo la ficha del umbral: se mide con las reglas
  que dependen de él, aflojando el criterio y apretándolo;
* que el ajuste de un cliente **no se le aplica a otro** (y que sin ajuste se sigue aplicando el
  general, que es lo que protege a la cartera entera de un cambio);
* que el valor aplicado **se publica en el informe** y marcado como criterio del cliente;
* que no se puede guardar un valor imposible, y que un intento fallido no deja nada a medias.
"""

from __future__ import annotations

import pytest

from app import db, esquema, servicio
from app.aplicacion import umbrales as criterios
from app.errores import EntradaInvalida, NoEncontrado
from app.modulos import analisis as mod
from tests.conftest import ADMIN, EMPRESA, EMPRESA_AJENA, Portal
from tests.test_analisis import analisis_de


@pytest.fixture
def empresas(entorno: object) -> None:
    """Las empresas del portal.

    `entorno` deja lista la base y la caché, pero no crea empresas (el catálogo no las necesita). Un
    ajuste sí: se guarda por empresa y se valida que exista, que es lo que evita dejar criterios
    colgando de un código mal escrito.
    """
    db.crear_empresa(EMPRESA, "MB Dommo, S.L.", 2017)
    db.crear_empresa(EMPRESA_AJENA, "ABGA Consultores, S.L.", 2010)


# ------------------------------------------------------------------ el ajuste manda


def _hallazgo(datos: dict, id_regla: str) -> dict:
    return next(h for h in datos["hallazgos"] if h["id"] == id_regla)


def test_sin_ajustes_se_aplican_los_generales(entorno: object) -> None:
    """Una empresa sin filas propias se juzga con los criterios generales, como siempre."""
    datos = analisis_de()
    assert db.umbrales_de(EMPRESA) == {}
    assert _hallazgo(datos, "modelo_347")["nivel"] == mod.AVISO
    assert _hallazgo(datos, "concentracion")["nivel"] == mod.ALERTA
    assert _hallazgo(datos, "endeudamiento")["nivel"] == mod.OK


def test_aflojar_el_criterio_del_347_cambia_el_veredicto(empresas: object) -> None:
    """Con el umbral general hay tres terceros obligados; subiéndolo, ninguno."""
    assert _hallazgo(analisis_de(), "modelo_347")["nivel"] == mod.AVISO

    criterios.fijar(EMPRESA, "347_operaciones", 1_000_000.0, actor=ADMIN)
    h = _hallazgo(analisis_de(), "modelo_347")
    assert h["nivel"] == mod.OK
    assert "Ningún tercero supera" in h["detalle"]
    assert "1.000.000,00" in h["detalle"], "el veredicto tiene que citar el criterio aplicado"


def test_apretar_el_criterio_del_endeudamiento_lo_pone_en_naranja(empresas: object) -> None:
    """Con el 75% general, un 36% de deuda está bien; con un criterio del 20%, no."""
    assert _hallazgo(analisis_de(), "endeudamiento")["nivel"] == mod.OK

    criterios.fijar(EMPRESA, "endeudamiento", 20.0, actor=ADMIN)
    h = _hallazgo(analisis_de(), "endeudamiento")
    assert h["nivel"] == mod.AVISO
    assert "36,0%" in h["detalle"]


def test_el_tipo_del_impuesto_de_sociedades_es_el_que_se_calcula(empresas: object) -> None:
    """La estimación del 202 se recalcula con el tipo del cliente (2.000 € de base)."""
    assert _hallazgo(analisis_de(), "modelo_202")["importe"] == pytest.approx(360.0)

    criterios.fijar(EMPRESA, "tipo_impuesto_sociedades", 0.25, actor=ADMIN)
    h = _hallazgo(analisis_de(), "modelo_202")
    assert h["importe"] == pytest.approx(500.0)
    assert "25,0%" in h["detalle"]


def test_los_limites_de_auditoria_se_pueden_ajustar(empresas: object) -> None:
    """Sin ajustes no se puede determinar; bajando dos límites por debajo de las cifras, sí."""
    assert _hallazgo(analisis_de(), "auditoria")["nivel"] == mod.NO_EVALUABLE

    criterios.fijar(EMPRESA, "auditoria_activo", 10.0, actor=ADMIN)
    criterios.fijar(EMPRESA, "auditoria_cifra_negocios", 10.0, actor=ADMIN)
    h = _hallazgo(analisis_de(), "auditoria")
    assert h["nivel"] == mod.AVISO
    assert "dos de los tres límites" in h["detalle"]


# ------------------------------------------------------------------ cada cliente con lo suyo


def test_el_ajuste_de_un_cliente_no_se_le_aplica_a_otro(empresas: object) -> None:
    criterios.fijar(EMPRESA, "antiguedad_clientes", 1095, actor=ADMIN)

    assert _hallazgo(analisis_de(EMPRESA), "antiguedad_clientes")["nivel"] == mod.OK
    ajena = analisis_de(EMPRESA_AJENA)
    assert _hallazgo(ajena, "antiguedad_clientes")["nivel"] == mod.ALERTA
    assert ajena["umbrales"]["antiguedad_clientes"]["origen"] == "defecto"


def test_el_informe_dice_de_donde_sale_cada_criterio(empresas: object) -> None:
    """Un rojo (o un verde) por un criterio pactado tiene que poder distinguirse del general."""
    criterios.fijar(EMPRESA, "concentracion_clientes", 60.0, actor=ADMIN)
    datos = analisis_de()

    assert datos["umbrales"]["concentracion_clientes"] == {
        "valor": pytest.approx(60.0), "unidad": "%",
        "para": "peso máximo de un cliente sobre el saldo pendiente",
        "min": 1.0, "max": 100.0, "origen": "empresa"}
    assert datos["umbrales"]["endeudamiento"]["origen"] == "defecto"
    assert _hallazgo(datos, "concentracion")["nivel"] == mod.OK

    r = servicio.ejecutar("analisis", cod_empresa=EMPRESA, year=2025, email=ADMIN)
    assert r.status == "ok" and r.html
    assert "ajustado para este cliente" in r.html
    assert "peso máximo de un cliente sobre el saldo pendiente → 60,0% (ajustado para este cliente)" in r.html


def test_volver_al_general_borra_el_ajuste(empresas: object) -> None:
    criterios.fijar(EMPRESA, "antiguedad_clientes", 30, actor=ADMIN)
    assert db.umbrales_de(EMPRESA) == {"antiguedad_clientes": 30.0}

    estado = criterios.fijar(EMPRESA, "antiguedad_clientes", None, actor=ADMIN)
    assert estado["ajustados"] == [] and db.umbrales_de(EMPRESA) == {}
    assert _hallazgo(analisis_de(), "antiguedad_clientes")["nivel"] == mod.ALERTA


# ------------------------------------------------------------------ validación


def test_no_se_puede_guardar_un_valor_imposible(empresas: object) -> None:
    for clave, valor, esperado in [
        ("concentracion_clientes", 300.0, "rango"),
        ("concentracion_clientes", -1.0, "rango"),
        ("antiguedad_clientes", 0.0, "rango"),
        ("antiguedad_clientes", 90.5, "enteros"),
        ("tipo_impuesto_sociedades", 2.0, "rango"),
        ("347_operaciones", "mucho", "número"),
        ("familia", 12.0, "no es un criterio ajustable"),
    ]:
        with pytest.raises(EntradaInvalida) as fallo:
            criterios.fijar(EMPRESA, clave, valor, actor=ADMIN)
        assert esperado in str(fallo.value)

    assert db.umbrales_de(EMPRESA) == {}, "un valor rechazado no puede dejar nada guardado"


def test_una_empresa_que_no_existe_no_se_puede_ajustar(empresas: object) -> None:
    with pytest.raises(NoEncontrado):
        criterios.fijar("9999", "endeudamiento", 50.0, actor=ADMIN)
    with pytest.raises(NoEncontrado):
        criterios.estado("9999")


def test_un_ajuste_metido_a_mano_en_la_base_no_rompe_el_informe(entorno: object) -> None:
    """La base no es la única puerta: una fila de más se ignora en vez de tumbar el análisis."""
    from app import cache
    from app.bd import upsert

    upsert("umbrales_empresa", ("cod_empresa", "clave", "valor", "actualizado", "actualizado_por"),
           ("cod_empresa", "clave"), (EMPRESA, "de_otra_version", 7.0, cache.ahora(), ADMIN))

    datos = analisis_de()
    assert datos["resumen"]["n_total"] == len(mod.REGLAS)
    assert mod.umbrales_efectivos({"de_otra_version": 7.0, "antiguedad_clientes": None}) == \
        mod.UMBRALES_POR_DEFECTO


def test_la_tabla_esta_en_el_contrato_del_esquema() -> None:
    """Si la migración crea una tabla que el contrato no espera, el verificador de copias protesta."""
    assert "umbrales_empresa" in esquema.TABLAS


# ------------------------------------------------------------------ el panel interno


def test_los_endpoints_del_panel_ajustan_de_verdad(portal: Portal) -> None:
    portal.entrar_como_admin()

    estado = portal.api.get("/api/interno/umbrales", params={"cod_empresa": EMPRESA}).json()
    assert estado["status"] == "ok" and estado["n_ajustados"] == 0
    assert estado["umbrales"]["auditoria_empleados"]["valor"] == 50

    r = portal.api.post("/api/interno/umbrales",
                        json={"cod_empresa": EMPRESA, "clave": "antiguedad_clientes", "valor": 365})
    assert r.status_code == 200, r.text
    assert r.json()["ajustados"] == ["antiguedad_clientes"]
    assert r.json()["umbrales"]["antiguedad_clientes"]["origen"] == "empresa"

    lista = portal.api.get("/api/interno/umbrales/ajustados").json()
    assert lista["n_clientes"] == 1 and lista["n_criterios"] == 1
    assert lista["clientes"][0]["criterios"]["antiguedad_clientes"] == {
        "valor": 365.0, "general": 90, "unidad": "días", "actualizado": lista["clientes"][0]
        ["criterios"]["antiguedad_clientes"]["actualizado"], "por": ADMIN}

    # y el análisis de ese cliente ya sale con el criterio nuevo
    datos = portal.api.get("/api/analisis", params={"cod_empresa": EMPRESA, "year": 2025}).json()
    assert datos["data"]["umbrales"]["antiguedad_clientes"]["origen"] == "empresa"


def test_un_valor_imposible_por_la_api_es_un_400(portal: Portal) -> None:
    portal.entrar_como_admin()
    r = portal.api.post("/api/interno/umbrales",
                        json={"cod_empresa": EMPRESA, "clave": "endeudamiento", "valor": 900})
    assert r.status_code == 400 and r.json()["codigo"] == "entrada_invalida"


def test_el_cliente_no_puede_ajustar_sus_criterios(portal: Portal) -> None:
    """Ajustar cómo se le mide es decisión de la asesoría, no del cliente."""
    portal.entrar_como_cliente()
    assert portal.api.get("/api/interno/umbrales",
                          params={"cod_empresa": EMPRESA}).status_code == 403
    assert portal.api.post("/api/interno/umbrales",
                           json={"cod_empresa": EMPRESA, "clave": "endeudamiento",
                                 "valor": 99}).status_code == 403
    assert portal.api.get("/api/interno/umbrales/ajustados").status_code == 403


def test_sin_sesion_tampoco(portal: Portal) -> None:
    assert portal.api.get("/api/interno/umbrales",
                          params={"cod_empresa": EMPRESA}).status_code == 401
    assert portal.api.post("/api/interno/umbrales",
                           json={"cod_empresa": EMPRESA, "clave": "endeudamiento",
                                 "valor": 50}).status_code == 401
