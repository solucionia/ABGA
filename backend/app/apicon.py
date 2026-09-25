"""Cliente de apiCON (Diez Software).

Dos cosas que hacen que esto vaya rápido donde n8n se atasca:

1. El token dura ~14 días (`expires_in` 1209599 s), así que se cachea por empresa
   y no se vuelve a autenticar en cada clic.
2. `/api/apuntes/` **pagina de 200 en 200** y devuelve `ResultadosTotales` en la
   envoltura. Los workflows pedían `$top=5000`, la API lo ignoraba y les devolvía
   sólo la primera página: por eso los informes se calculaban con una fracción
   del ejercicio. Aquí se pagina hasta cubrir `ResultadosTotales`.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import httpx

from . import cache
from .config import cargar_config

log = logging.getLogger("abga.apicon")

PAGINA = 200  # máximo real que devuelve el endpoint (por encima de 200 lo ignora)
_lock = threading.Lock()
_en_vuelo: dict[str, threading.Event] = {}


def _a_fecha(v: int) -> date:
    """20250131 -> date(2025, 1, 31)."""
    return date(v // 10000, (v // 100) % 100, v % 100)


def _de_fecha(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def _fecha_de_clave(k: str) -> int:
    """La clave de un asiento es `Ejercicio|Serie|Documento|Fecha|Debe|Haber`."""
    partes = k.split("|")
    try:
        return int(partes[3])
    except (IndexError, ValueError):
        return 0


class ErrorErp(RuntimeError):
    """Fallo al hablar con apiCON, con el mensaje ya listo para el usuario."""

    def __init__(self, mensaje: str, status: int | None = None) -> None:
        super().__init__(mensaje)
        self.status = status


class ClienteApicon:
    def __init__(self, cfg=None) -> None:
        self.cfg = cfg or cargar_config()
        self._tok_mem: dict[str, tuple[str, datetime]] = {}
        self._cli = httpx.Client(timeout=self.cfg.timeout_erp, follow_redirects=True)
        self._ultima_peticion = 0.0

    # ---------- ritmo ----------

    def _esperar_turno(self, pausa: float | None = None) -> None:
        """El ERP responde 429 si se le machaca: una petición detrás de otra como mínimo."""
        pausa = self.cfg.pausa_entre_peticiones if pausa is None else pausa
        with _lock:
            delta = time.monotonic() - self._ultima_peticion
            if delta < pausa:
                time.sleep(pausa - delta)
            self._ultima_peticion = time.monotonic()

    def _pedir(self, metodo: str, ruta: str, **kw) -> httpx.Response:
        intentos = 0
        while True:
            self._esperar_turno()
            try:
                r = self._cli.request(metodo, f"{self.cfg.apicon_base.rstrip('/')}{ruta}", **kw)
            except httpx.HTTPError as e:
                intentos += 1
                if intentos > self.cfg.reintentos_429:
                    raise ErrorErp(f"No se pudo conectar con el ERP: {e}") from e
                time.sleep(2 * intentos)
                continue
            if r.status_code == 429:
                intentos += 1
                if intentos > self.cfg.reintentos_429:
                    raise ErrorErp("El ERP está limitando las peticiones (429). Inténtalo en unos minutos.",
                                   status=429)
                espera = float(r.headers.get("Retry-After") or 0) or self.cfg.espera_429_base * intentos
                log.warning("429 del ERP, espero %.1fs (intento %s)", espera, intentos)
                time.sleep(espera)
                continue
            return r

    # ---------- token ----------

    def token(self, empresa: str, forzar: bool = False) -> str:
        if not forzar:
            mem = self._tok_mem.get(empresa)
            if mem and mem[1] > datetime.now(timezone.utc):
                return mem[0]
            en_cache = cache.leer_token(empresa)
            if en_cache:
                self._tok_mem[empresa] = (en_cache["access_token"], datetime.fromisoformat(en_cache["expira_en"]))
                return en_cache["access_token"]

        r = self._pedir(
            "POST", "/token",
            data={
                "grant_type": "password",
                "username": self.cfg.apicon_username,
                "password": self.cfg.apicon_password,
                "client_id": self.cfg.apicon_client_id,
                "client_secret": self.cfg.apicon_client_secret,
                "cod_empresa": empresa,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 200:
            raise ErrorErp(f"El ERP rechazó las credenciales de la empresa {empresa} (HTTP {r.status_code}).",
                           status=r.status_code)
        j = r.json()
        tok = j.get("access_token") or j.get("token")
        if not tok:
            raise ErrorErp("El ERP no devolvió token de acceso.")
        segundos = int(j.get("expires_in") or 3600)
        # margen de 1 hora para no usar un token a punto de caducar
        expira = datetime.now(timezone.utc) + timedelta(seconds=max(60, segundos - 3600))
        self._tok_mem[empresa] = (tok, expira)
        cache.guardar_token(empresa, tok, expira.isoformat(timespec="seconds"))
        log.info("token nuevo para %s (caduca en %ss)", empresa, segundos)
        return tok

    def _cab(self, empresa: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(empresa)}", "Accept": "application/json",
                "Accept-Encoding": "gzip"}

    # ---------- apuntes ----------

    def apuntes(self, empresa: str, ejercicio: int, *, forzar: bool = False,
                ttl: int | None = None) -> dict[str, Any]:
        """Devuelve el ejercicio completo (paginado y verificado), con caché.

        Con `APICON_SOLO_CACHE=1` no se llama al ERP en ningún caso: se lee la caché ignorando
        el TTL y, si el ejercicio no está, se falla con un mensaje claro. Es la red de seguridad
        para que una demo o una previsualización no toquen el ERP en producción (el TTL de 12 h
        caduca y una consulta normal acabaría descargando el ejercicio entero).
        """
        if self.cfg.solo_cache:
            guardado = cache.leer_apuntes(empresa, ejercicio, ttl=-1)
            if guardado:
                return guardado
            raise ErrorErp(
                f"Modo solo-caché: los apuntes de la empresa {empresa}, ejercicio {ejercicio}, "
                "no están en la caché y no se le pueden pedir al ERP "
                "(quitar APICON_SOLO_CACHE para permitirlo).")

        if not forzar:
            guardado = cache.leer_apuntes(empresa, ejercicio, ttl)
            if guardado:
                return guardado

        clave_vuelo = f"{empresa}:{ejercicio}"
        ev = _en_vuelo.get(clave_vuelo)
        if ev is not None:
            # otra petición ya lo está trayendo: esperamos a que termine y leemos caché
            ev.wait(timeout=self.cfg.timeout_erp)
            guardado = cache.leer_apuntes(empresa, ejercicio, ttl=-1)
            if guardado:
                return guardado

        ev = threading.Event()
        _en_vuelo[clave_vuelo] = ev
        try:
            return self._traer_todo(empresa, ejercicio)
        finally:
            ev.set()
            _en_vuelo.pop(clave_vuelo, None)

    def _pagina_rango(self, empresa: str, ejercicio: int, ini: int, fin: int,
                      pagina: int = 1, **extra: Any) -> dict[str, Any]:
        """Una página de un rango de fechas. `$skip` es el número de página (1-indexado)."""
        filtro = f"Ejercicio eq '{ejercicio}' and Fecha ge {ini} and Fecha le {fin}"
        params: dict[str, Any] = {"$filter": filtro, "$top": str(min(self.cfg.apicon_top, PAGINA)),
                                  "$skip": str(pagina)}
        params.update(extra)
        r = self._pedir("GET", "/api/apuntes/", params=params, headers=self._cab(empresa))
        if r.status_code == 401:
            r = self._pedir("GET", "/api/apuntes/", params=params,
                            headers={"Authorization": f"Bearer {self.token(empresa, forzar=True)}",
                                     "Accept": "application/json"})
        if r.status_code != 200:
            raise ErrorErp(f"El ERP devolvió HTTP {r.status_code} al pedir los apuntes de {ejercicio}.",
                           status=r.status_code)
        return r.json()

    @staticmethod
    def _clave_asiento(a: dict) -> str:
        return (f"{a.get('Ejercicio')}|{a.get('Serie')}|{a.get('Documento')}|"
                f"{a.get('Fecha')}|{a.get('Debe')}|{a.get('Haber')}")

    def _traer_rango(self, empresa: str, ejercicio: int, ini: int, fin: int,
                     destino: dict[str, dict], stats: dict[str, Any], *, profundidad: int = 0) -> None:
        """Trae un rango de fechas partiéndolo hasta que quepa en una sola página.

        Motivo: el listado del ERP no garantiza un orden estable entre páginas y, al paginar,
        los asientos empatados en la frontera se pierden (comprobado: 1.462 de 1.531). Si cada
        consulta devuelve la partición entera, no hay frontera que perder.

        La partición se hace con fechas reales: partir por el punto medio aritmético de un
        entero `YYYYMMDD` produce fronteras inexistentes (20240666) y deja días fuera.
        """
        stats["peticiones"] += 1
        j = self._pagina_rango(empresa, ejercicio, ini, fin)
        datos = j.get("Datos") or []
        total = j.get("ResultadosTotales")
        total = len(datos) if total is None else int(total)
        tope = min(self.cfg.apicon_top, PAGINA)

        if total == 0:
            return
        if total <= tope and len(datos) >= total:
            for a in datos:
                destino[self._clave_asiento(a)] = a
            stats["particiones"] += 1
            return

        d_ini, d_fin = _a_fecha(ini), _a_fecha(fin)
        if d_ini >= d_fin:
            self._traer_dia_denso(empresa, ejercicio, ini, destino, stats, total, tope, datos)
            return

        if profundidad > 12:
            log.warning("%s/%s: rango %s-%s demasiado denso, me quedo con lo leído",
                        empresa, ejercicio, ini, fin)
            for a in datos:
                destino[self._clave_asiento(a)] = a
            return

        corte_fecha = d_ini + timedelta(days=(d_fin - d_ini).days // 2)
        if corte_fecha <= d_ini:
            corte_fecha = d_ini + timedelta(days=1)
        self._traer_rango(empresa, ejercicio, ini, _de_fecha(corte_fecha - timedelta(days=1)),
                          destino, stats, profundidad=profundidad + 1)
        self._traer_rango(empresa, ejercicio, _de_fecha(corte_fecha), fin,
                          destino, stats, profundidad=profundidad + 1)

    def _traer_dia_denso(self, empresa: str, ejercicio: int, fecha: int, destino: dict[str, dict],
                         stats: dict[str, Any], total: int, tope: int, primera_pagina: list[dict]) -> None:
        """Un día con más asientos que una página: aquí no se puede partir por fecha.

        Se intenta primero por **serie** (el ERP numera los asientos por serie, así que es una
        partición natural); si una sola serie sigue siendo más grande que una página, se pagina
        y se repiten pasadas hasta cubrir el total declarado, comprobando el recuento. Queda
        registrado en `stats["dias_paginados"]` para que la cobertura del informe lo refleje.
        """
        stats["dias_paginados"].append(f"{fecha} ({total})")

        series = sorted({str(a.get("Serie")) for a in primera_pagina if a.get("Serie")})
        if len(series) > 1:
            cubierto = 0
            tentativa: dict[str, dict] = {}
            for s in series:
                j = self._pagina_rango_serie(empresa, ejercicio, fecha, s)
                stats["peticiones"] += 1
                sub = j.get("ResultadosTotales")
                sub = len(j.get("Datos") or []) if sub is None else int(sub)
                cubierto += sub
                if sub <= tope:
                    for a in j.get("Datos") or []:
                        tentativa[self._clave_asiento(a)] = a
                else:
                    tentativa = {}
                    break
            if tentativa and len(tentativa) >= total:
                destino.update(tentativa)
                stats["particiones"] += 1
                return

        # paginación con verificación: primero con orden explícito, y repitiendo pasadas
        # porque el orden del ERP no está garantizado entre llamadas
        intentos = [{"$orderby": "Documento"}, {}, {}, {}, {}]
        for pasada, orden in enumerate(intentos, start=1):
            extra = dict(orden)
            for pagina in range(1, (total // tope) + 3):
                jj = self._pagina_rango(empresa, ejercicio, fecha, fecha, pagina, **extra)
                stats["peticiones"] += 1
                dd = jj.get("Datos") or []
                if not dd:
                    break
                for a in dd:
                    destino[self._clave_asiento(a)] = a
                if len(dd) < tope:
                    break
            ya = sum(1 for k in destino if k.startswith(f"{ejercicio}|") and _fecha_de_clave(k) == fecha)
            if ya >= total:
                stats["particiones"] += 1
                return
            log.info("%s/%s %s: pasada %s cubrió %s de %s asientos", empresa, ejercicio, fecha, pasada, ya, total)
        log.warning("%s/%s %s: no se ha podido cubrir el día completo (%s asientos) — el informe lo "
                    "declarará como cobertura parcial", empresa, ejercicio, fecha, total)

    def _pagina_rango_serie(self, empresa: str, ejercicio: int, fecha: int, serie: str) -> dict[str, Any]:
        filtro = f"Ejercicio eq '{ejercicio}' and Fecha eq {fecha} and Serie eq '{serie}'"
        r = self._pedir("GET", "/api/apuntes/",
                        params={"$filter": filtro, "$top": str(min(self.cfg.apicon_top, PAGINA)), "$skip": "1"},
                        headers=self._cab(empresa))
        if r.status_code != 200:
            return {"Datos": [], "ResultadosTotales": 0}
        return r.json()

    def _recorrido_paginas(self, empresa: str, ejercicio: int, destino: dict[str, dict],
                           stats: dict[str, Any], tope: int,
                           total_declarado: int | None = None) -> int:
        """Recorre el listado sin filtro de fecha, por número de página.

        Complementa al particionado por fechas: comprobado sobre 6091/2024, hay asientos que
        el filtro por fecha no devuelve aunque su fecha esté dentro del ejercicio, y sólo
        aparecen en este recorrido.

        Dos criterios que fallaban y por qué se descartaron:
          * cortar cuando las fechas retroceden — las páginas del ERP **se solapan** y no son
            monótonas (una página empieza en enero y la siguiente en octubre).
          * cortar tras dos páginas sin asientos nuevos — las primeras páginas ya las trajo la
            partición por fechas, así que eso cortaba justo antes de llegar a las que sí traen
            lo que falta.
        Se recorre el número de páginas que implica `ResultadosTotales` y se para sólo cuando una
        página viene vacía.
        """
        nuevas = 0
        max_paginas = 30 if total_declarado is None else (total_declarado // tope) + 3
        for pagina in range(1, max_paginas + 1):
            j = self._pagina_ejercicio(empresa, ejercicio, pagina, tope)
            stats["peticiones"] += 1
            datos = j.get("Datos") or []
            if not datos:
                break
            for a in datos:
                k = self._clave_asiento(a)
                if k not in destino:
                    destino[k] = a
                    nuevas += 1
        return nuevas

    def _pagina_ejercicio(self, empresa: str, ejercicio: int, pagina: int, tope: int) -> dict[str, Any]:
        r = self._pedir("GET", "/api/apuntes/",
                        params={"$filter": f"Ejercicio eq '{ejercicio}'", "$top": str(tope),
                                "$skip": str(pagina)},
                        headers=self._cab(empresa))
        if r.status_code != 200:
            return {"Datos": [], "ResultadosTotales": 0}
        return r.json()

    def _traer_todo(self, empresa: str, ejercicio: int) -> dict[str, Any]:
        """Trae el ejercicio completo combinando las dos estrategias y verificando la cobertura.

        1. Particionado por rangos de fecha (rápido cuando funciona: 2025 quedó completo así).
        2. Si no alcanza `ResultadosTotales`, recorrido por páginas sin filtro de fecha.
        3. Si aún falta, un segundo recorrido: el orden del ERP no es estable entre llamadas.
        Lo que no se consiga queda declarado en la cobertura, nunca oculto.
        """
        t0 = time.perf_counter()
        asientos: dict[str, dict] = {}
        stats: dict[str, Any] = {"peticiones": 0, "particiones": 0, "dias_paginados": [],
                                 "recorridos": []}
        tope = min(self.cfg.apicon_top, PAGINA)

        self._traer_rango(empresa, ejercicio, ejercicio * 10000 + 101, ejercicio * 10000 + 1231,
                          asientos, stats)

        # total declarado por el ERP para el ejercicio completo
        j = self._pagina_rango(empresa, ejercicio, ejercicio * 10000 + 101, ejercicio * 10000 + 1231, 1)
        stats["peticiones"] += 1
        total_declarado = j.get("ResultadosTotales")
        total_declarado = int(total_declarado) if total_declarado is not None else None
        antes = len(asientos)

        if total_declarado is None or len(asientos) < total_declarado:
            for intento in (1, 2):
                nuevos = self._recorrido_paginas(empresa, ejercicio, asientos, stats, tope,
                                                 total_declarado)
                stats["recorridos"].append({"intento": intento, "nuevos": nuevos})
                if not nuevos:
                    break
                if total_declarado is not None and len(asientos) >= total_declarado:
                    break
            log.info("%s/%s: el particionado por fechas dio %s asientos y el recorrido por páginas "
                     "aportó %s más", empresa, ejercicio, antes, len(asientos) - antes)

        lista = sorted(asientos.values(), key=lambda a: (str(a.get("Fecha")), str(a.get("Documento"))))
        segundos = time.perf_counter() - t0
        n = len(lista)
        if total_declarado is None:
            cobertura = f"{n} asientos (el ERP no declara total)"
        elif n >= total_declarado:
            cobertura = (f"completa ({n} asientos: {stats['particiones']} particiones por fecha"
                         + (" + recorrido por páginas)" if stats["recorridos"] else ")"))
        else:
            cobertura = f"parcial ({n} de {total_declarado} asientos)"
            log.warning("COBERTURA PARCIAL %s/%s: %s (peticiones=%s)", empresa, ejercicio, cobertura,
                        stats["peticiones"])
        cache.guardar_apuntes(empresa, ejercicio, lista, resultados_totales=total_declarado,
                              cobertura=cobertura, segundos=segundos)
        return {
            "empresa": empresa, "year": ejercicio, "asientos": lista,
            "n_asientos": n,
            "n_lineas": sum(len(a.get("Detalles") or []) for a in lista),
            "resultados_totales": total_declarado, "cobertura": cobertura,
            "peticiones": stats["peticiones"], "particiones": stats["particiones"],
            "dias_paginados": stats["dias_paginados"], "recorridos": stats["recorridos"],
            "segundos": round(segundos, 2), "desde_cache": False,
            "actualizado": cache.ahora(),
        }


_cliente: ClienteApicon | None = None


def cliente() -> ClienteApicon:
    global _cliente
    if _cliente is None:
        _cliente = ClienteApicon()
    return _cliente


def lineas_de(asientos: Iterable[dict]) -> list[dict]:
    """Aplana los asientos en líneas de detalle, como hacía el nodo Code de n8n."""
    salida: list[dict] = []
    for a in asientos or []:
        for d in a.get("Detalles") or []:
            if not d.get("Fecha"):
                d = {**d, "Fecha": a.get("Fecha"), "Documento": d.get("Documento") or a.get("Documento"),
                     "Serie": d.get("Serie") or a.get("Serie")}
            salida.append(d)
    return salida
