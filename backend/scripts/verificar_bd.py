"""Prueba la capa de datos contra los DOS motores: SQLite y PostgreSQL.

Ejecuta exactamente el mismo recorrido (esquema, usuarios y permisos, apuntes, tokens, caché de
cálculo y registro de ejecuciones) sobre cada motor y compara los resultados uno a uno. Si algo
no coincide, sale con código distinto de cero.

El PostgreSQL de la prueba es el embebido de `pgserver` (no necesita infraestructura): sirve
para probar de verdad la ruta de producción antes de desplegar en Coolify.

    ./.venv/bin/python backend/scripts/verificar_bd.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "backend"))

from app import bd, cache, db, trabajos  # noqa: E402

ASIENTOS = [
    {"Numero": "1", "Fecha": 20250115, "Descripcion": "FV/2025/00001-CLIENTE UNO",
     "Detalles": [{"Cuenta": "43000000", "Debe": 1210.0, "Haber": 0.0},
                  {"Cuenta": "70000000", "Debe": 0.0, "Haber": 1000.0},
                  {"Cuenta": "47700000", "Debe": 0.0, "Haber": 210.0}]},
    {"Numero": "2", "Fecha": 20250210, "Descripcion": "OP/2025/00002-PROVEEDOR DOS",
     "Detalles": [{"Cuenta": "62800000", "Debe": 100.0, "Haber": 0.0},
                  {"Cuenta": "41000000", "Debe": 0.0, "Haber": 100.0}]},
]

fallos: list[str] = []


def comprobar(nombre: str, obtenido, esperado) -> None:
    ok = obtenido == esperado
    print(f"    {'ok   ' if ok else 'FALLO'} {nombre}: {obtenido!r}")
    if not ok:
        fallos.append(f"{nombre}: {obtenido!r} != {esperado!r}")


def recorrido(motor: str) -> None:
    print(f"\n=== {motor} ===")
    bd.reiniciar()

    # --- esquema ---
    con = bd.conectar()
    tablas = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        if bd.es_postgres() else
        "SELECT name AS table_name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    nombres = sorted(f["table_name"] for f in tablas if not str(f["table_name"]).startswith("sqlite_"))
    esperadas = sorted(["apuntes", "calc_cache", "ejecuciones", "empresas", "intentos", "permisos",
                        "tokens", "trabajos", "usuarios"])
    comprobar("tablas creadas", nombres, esperadas)

    # --- empresas y usuarios ---
    db.crear_empresa("6091", "MB Dommo, S.L.", 2023, "piloto")
    db.crear_empresa("1092", "ABGA Consultores", 2010, "")
    comprobar("empresa leída", db.empresa("6091")["nombre"], "MB Dommo, S.L.")
    comprobar("empresa inexistente", db.empresa("9999"), None)
    comprobar("listar empresas", [e["cod_empresa"] for e in db.listar_empresas()],
              ["1092", "6091"])  # ORDER BY nombre

    db.crear_usuario("Cliente@Ejemplo.com", "Cliente Uno", "hash-1", "cliente", ["6091"])
    db.crear_usuario("jefa@abga.es", "Jefa ABGA", "hash-2", "interno", [])
    comprobar("email normalizado", db.usuario("cliente@ejemplo.com")["email"], "cliente@ejemplo.com")
    comprobar("permisos del cliente", db.usuario("cliente@ejemplo.com")["empresas"], ["6091"])
    comprobar("tiene_acceso sí", db.tiene_acceso("cliente@ejemplo.com", "6091"), True)
    comprobar("tiene_acceso no", db.tiene_acceso("cliente@ejemplo.com", "1092"), False)
    comprobar("el interno ve todas", db.empresas_de("jefa@abga.es"), ["1092", "6091"])
    comprobar("hash guardado", db.hash_de("cliente@ejemplo.com"), "hash-1")

    # volver a crear el usuario cambia los datos y no duplica filas
    db.crear_usuario("cliente@ejemplo.com", "Cliente Uno (renombrado)", "hash-3", "cliente", ["1092"])
    comprobar("upsert de usuario", db.usuario("cliente@ejemplo.com")["nombre"], "Cliente Uno (renombrado)")
    comprobar("usuarios sin duplicar", len(db.listar_usuarios()), 2)
    comprobar("permiso reemplazado", db.usuario("cliente@ejemplo.com")["empresas"], ["1092"])

    db.asignar_empresa("cliente@ejemplo.com", "6091")
    db.asignar_empresa("cliente@ejemplo.com", "6091")  # idempotente
    comprobar("permiso añadido", db.usuario("cliente@ejemplo.com")["empresas"], ["1092", "6091"])
    db.activar("cliente@ejemplo.com", False)
    comprobar("desactivar", db.usuario("cliente@ejemplo.com")["activo"], False)

    # --- apuntes (la caché que evita machacar el ERP) ---
    cache.guardar_apuntes("6091", 2025, ASIENTOS, resultados_totales=2, cobertura="completa (2 de 2)",
                          segundos=12.5)
    leido = cache.leer_apuntes("6091", 2025)
    comprobar("asientos leídos", leido["n_asientos"], 2)
    comprobar("líneas contadas", leido["n_lineas"], 5)
    comprobar("cobertura", leido["cobertura"], "completa (2 de 2)")
    comprobar("total declarado por el ERP", leido["resultados_totales"], 2)
    comprobar("viene de caché", leido["desde_cache"], True)
    comprobar("los asientos vuelven enteros", leido["asientos"][0]["Descripcion"],
              "FV/2025/00001-CLIENTE UNO")
    comprobar("json numérico intacto", leido["asientos"][0]["Detalles"][0]["Debe"], 1210.0)
    # `empresas_con_datos` lee la columna por NOMBRE: en PostgreSQL las filas llegan como diccionario y
    # por posición revienta. Funcionaba en SQLite y dio 500 en producción, así que se comprueba en los
    # dos motores desde aquí.
    comprobar("empresas con datos en caché", db.empresas_con_datos(), {"6091"})
    comprobar("la que no tiene datos no sale", db.empresas_con_datos() & {"1092"}, set())

    cache.guardar_apuntes("6091", 2025, ASIENTOS[:1], resultados_totales=2, cobertura="parcial (1 de 2)",
                          segundos=3.0)
    comprobar("upsert de apuntes no duplica", len(cache.info_cache("6091")), 1)
    comprobar("upsert actualiza", cache.leer_apuntes("6091", 2025)["n_asientos"], 1)
    comprobar("info_cache ve el ejercicio", cache.info_cache()[0]["ejercicio"], 2025)

    comprobar("TTL 0 caduca", cache.leer_apuntes("6091", 2025, ttl=0), None)
    comprobar("TTL negativo no caduca", cache.leer_apuntes("6091", 2025, ttl=-1)["n_asientos"], 1)
    comprobar("invalidar borra", cache.invalidar("6091", 2025), 1)
    comprobar("ya no está", cache.leer_apuntes("6091", 2025), None)

    # --- tokens del ERP ---
    cache.guardar_token("6091", "token-de-prueba", "2999-01-01T00:00:00+00:00")
    comprobar("token vigente", cache.leer_token("6091")["access_token"], "token-de-prueba")
    cache.guardar_token("6091", "token-viejo", "2000-01-01T00:00:00+00:00")
    comprobar("token caducado", cache.leer_token("6091"), None)
    comprobar("actualizar token no duplica", cache.leer_token("9999"), None)

    # --- caché de cálculo ---
    cache.guardar_calc("pyg:6091:2025", {"ingresos": 1000.5, "filas": [1, 2, 3]})
    comprobar("cálculo recuperado", cache.leer_calc("pyg:6091:2025"),
              {"ingresos": 1000.5, "filas": [1, 2, 3]})
    cache.guardar_calc("pyg:6091:2025", {"ingresos": 2000.0})
    comprobar("upsert de cálculo", cache.leer_calc("pyg:6091:2025"), {"ingresos": 2000.0})
    comprobar("clave inexistente", cache.leer_calc("no-existe"), None)

    # --- registro de ejecuciones (el log que estaba desconectado en n8n) ---
    id1 = db.registrar_ejecucion(cod_empresa="6091", ejercicio=2025, modulos="pyg", origen="portal",
                                 email="cliente@ejemplo.com", segundos=1.25, estado="ok",
                                 desde_cache=True, detalle="prueba",
                                 importes={"resultado": 807160.88})
    ejecs = db.ejecuciones(cod_empresa="6091")
    comprobar("id devuelto por el motor", id1 > 0, True)
    comprobar("ejecución registrada", len(ejecs), 1)
    comprobar("importes parseados", ejecs[0]["importes"], {"resultado": 807160.88})
    comprobar("desde_cache es booleano", ejecs[0]["desde_cache"], 1)
    db.registrar_ejecucion(cod_empresa="6091", ejercicio=2025, modulos="fiscal", origen="portal",
                           email="cliente@ejemplo.com", segundos=0.5, estado="ok", desde_cache=False)
    comprobar("dos ejecuciones", len(db.ejecuciones()), 2)
    resumen = db.resumen_ejecuciones(dias=30)
    comprobar("resumen agrupa por módulo", sorted(r["modulos"] for r in resumen), ["fiscal", "pyg"])
    comprobar("resumen cuenta", [r["n"] for r in resumen], [1, 1])

    # una ejecución vieja: el filtro por días tiene que dejarla fuera de la ventana reciente
    con = bd.conectar()
    con.execute("INSERT INTO ejecuciones (instante, cod_empresa, ejercicio, modulos, origen, email,"
                " segundos, estado, desde_cache, detalle, importes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("2000-01-01T00:00:00+00:00", "6091", 2024, "memoria", "cron", "", 9.0, "ok", 0,
                 "antigua", "{}"))
    con.commit()
    comprobar("resumen ignora lo antiguo", sorted(r["modulos"] for r in db.resumen_ejecuciones(dias=30)),
              ["fiscal", "pyg"])

    # --- intentos de acceso (Fase 2: contador en la base, no en memoria del proceso) ---
    print("  intentos de acceso")
    db.limpiar_intentos("pin:6091")
    comprobar("sin intentos", db.contar_intentos("pin:6091", 900), 0)
    db.registrar_intento("pin:6091")
    db.registrar_intento("pin:6091")
    db.registrar_intento("login:cliente@ejemplo.com")
    comprobar("dos intentos con el PIN", db.contar_intentos("pin:6091", 900), 2)
    comprobar("el contador es por clave", db.contar_intentos("login:cliente@ejemplo.com", 900), 1)
    con.execute("INSERT INTO intentos (clave, instante) VALUES (?, ?)",
                ("pin:6091", "2000-01-01T00:00:00+00:00"))
    con.commit()
    comprobar("la ventana deja fuera lo antiguo", db.contar_intentos("pin:6091", 900), 2)
    # Ventana de 40 años: el intento del año 2000 vuelve a contar (comprueba que el dato está
    # guardado y que lo que filtra es la ventana, no el borrado).
    comprobar("con una ventana amplia cuenta todo", db.contar_intentos("pin:6091", 40 * 365 * 86400), 3)
    comprobar("limpiar intentos", (db.limpiar_intentos("pin:6091"), db.contar_intentos("pin:6091", 900))[1], 0)
    con.execute("INSERT INTO intentos (clave, instante) VALUES (?, ?)",
                ("login:antiguo@ejemplo.com", "2000-01-01T00:00:00+00:00"))
    con.commit()
    db.registrar_intento("login:reciente@ejemplo.com")
    comprobar("limpiar caducados se lleva sólo lo antiguo", db.limpiar_intentos_caducados(86400), 1)
    comprobar("y deja lo reciente", db.contar_intentos("login:reciente@ejemplo.com", 900), 1)

    # --- trabajos en segundo plano (su estado también vive en la base) ---
    print("  trabajos en segundo plano")
    t = trabajos.Trabajo(id="prueba-1", tipo="carga", cod_empresa="6091", year=2025,
                         email="cliente@ejemplo.com")
    t.pasos.append({"ejercicio": 2025, "estado": "hecho", "n_asientos": 2})
    trabajos.guardar(t)
    leido_t = trabajos.obtener("prueba-1")
    comprobar("trabajo recuperado", (leido_t.tipo, leido_t.year, leido_t.estado),
              ("carga", 2025, "en_curso"))
    comprobar("sus pasos viajan en JSON", leido_t.pasos[0]["n_asientos"], 2)
    comprobar("aparece en el listado", [x["id"] for x in trabajos.listar(10)], ["prueba-1"])
    comprobar("es el trabajo en curso de ese ejercicio",
              (trabajos.trabajo_en_curso("6091", 2025) or leido_t).id, "prueba-1")
    leido_t.estado, leido_t.mensaje, leido_t.fin = "hecho", "Datos actualizados", leido_t.inicio + 2
    trabajos.guardar(leido_t)
    comprobar("se actualiza sin duplicar",
              (trabajos.obtener("prueba-1").estado, len(trabajos.listar(10))), ("hecho", 1))
    comprobar("ya no está en curso", trabajos.trabajo_en_curso("6091", 2025), None)
    comprobar("marcar interrumpidos", (trabajos.marcar_interrumpidos(),), (0,))
    trabajos.guardar(trabajos.Trabajo(id="prueba-2", tipo="informe", cod_empresa="6091", year=2024))
    comprobar("uno en curso se marca", trabajos.marcar_interrumpidos(), 1)
    comprobar("y queda dicho", trabajos.obtener("prueba-2").mensaje, trabajos.INTERRUMPIDO)
    comprobar("resumen incluye lo antiguo si la ventana es amplia",
              sorted(r["modulos"] for r in db.resumen_ejecuciones(dias=36500)),
              ["fiscal", "memoria", "pyg"])


def main() -> int:
    # 1) SQLite (el motor de desarrollo)
    tmp = tempfile.mkdtemp(prefix="abga-bd-sqlite-")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/abga.sqlite3"
    recorrido("SQLite (desarrollo local)")

    # 2) PostgreSQL real (embebido) — la ruta de producción
    import pgserver

    datos = tempfile.mkdtemp(prefix="abga-bd-pg-")
    servidor = pgserver.get_server(datos)
    uri = servidor.get_uri()
    print(f"\nPostgreSQL de prueba: {uri}")
    os.environ["DATABASE_URL"] = uri
    try:
        recorrido("PostgreSQL")
    finally:
        bd.reiniciar()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fallos:
        print(f"FALLOS ({len(fallos)}):")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("Los dos motores dan exactamente el mismo resultado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
