/* ABGA Hub · capa de datos
 *
 * El hub llegó con los datos de ejemplo dentro del propio código de la aplicación (CLIENTES, DUPS,
 * TAREAS, VENC…). Este fichero es lo único que se añade: trae los datos reales de la plataforma y
 * los deja en el mismo sitio y con la misma forma que el hub ya esperaba, para que las pantallas
 * —su markup, sus estilos y su comportamiento— no cambien.
 *
 * Cómo entra: la aplicación tiene su propio punto de hidratación (`componentDidMount`) y su propio
 * estado (`this.setState`). Aquí se usan esos dos, no otros:
 *
 *   1. `ABGA.cargar(componente)` — lo llama el hub al montarse. Averigua la sesión, el catálogo de
 *      empresas, el ejercicio en curso y el panel que corresponde al rol, y carga la pantalla.
 *   2. `ABGA.alCambiarEstado(...)` — lo llama el puente que hay al final del script del hub cuando
 *      la aplicación cambia de pantalla, de empresa o de ejercicio. Es lo que hace que cada
 *      pantalla pida sus datos a la plataforma en vez de enseñar los de ejemplo.
 *
 * Cada pantalla tiene su traductor en `pantallas/<nombre>.js` y se registra con `ABGA.registrar`.
 * Un traductor recibe el contexto de datos y una única obligación: dejar en los datos del hub la
 * misma estructura que él ya usaba, con datos reales. Lo que la plataforma no sabe todavía se deja
 * vacío y se declara con `ctx.sinDatos(...)`, nunca se rellena con cifras inventadas.
 *
 * Contrato de la API (mismo origen, sesión por cookie `HttpOnly`):
 *
 *   POST /api/login                     {email, password, cod_empresa?, pin?}   → usuario
 *   POST /api/logout                                                            → ok
 *   GET  /api/yo                                                                → {usuario, interno}
 *   GET  /api/empresas                                                          → empresas del usuario
 *   GET  /api/modulos                                                           → catálogo de análisis
 *   GET  /api/ejercicios?cod_empresa=                                           → ejercicios con datos
 *   GET  /api/cache?cod_empresa=                                                → qué hay en caché
 *   GET  /api/dashboard?cod_empresa=&year=                                      → kpis, pyg, balance,
 *                                                                                 mensual, comparativa,
 *                                                                                 terceros, avisos
 *   GET  /api/analisis?cod_empresa=&year=                                       → semáforo (50 comprobaciones)
 *   POST /api/informe                   {modulo, cod_empresa, year, parametros} → html + data + meta
 *   POST /api/informe/exportar          (mismo cuerpo, devuelve fichero)
 *   POST /api/refrescar                 {cod_empresa, year}                     → trabajo (largo)
 *   GET  /api/trabajos/{id}                                                     → estado del trabajo
 *   GET  /api/interno/resumen|usuarios|metricas|avisos|cartera|umbrales         → panel interno de ABGA
 */

window.ABGA = (function () {
  'use strict';

  var BASE = '';

  /* ── Cliente de la API ───────────────────────────────────────────────────────────────────── */

  /** Error de la API con el mensaje que ya viene redactado desde el backend. */
  function ErrorApi(mensaje, estado) {
    var e = new Error(mensaje);
    e.estado = estado;
    return e;
  }

  /** Petición JSON con la cookie de sesión. `401` devuelve al portal, que es quien tiene el login. */
  async function pedir(ruta, opciones) {
    var opcionesFinales = Object.assign({ credentials: 'same-origin', headers: {} }, opciones || {});
    if (opcionesFinales.cuerpo !== undefined) {
      opcionesFinales.method = opcionesFinales.method || 'POST';
      opcionesFinales.headers['Content-Type'] = 'application/json';
      opcionesFinales.body = JSON.stringify(opcionesFinales.cuerpo);
      delete opcionesFinales.cuerpo;
    }
    var respuesta;
    try {
      respuesta = await fetch(BASE + ruta, opcionesFinales);
    } catch (fallo) {
      throw ErrorApi('No se ha podido contactar con la plataforma. Comprueba la conexión.', 0);
    }
    var tipo = respuesta.headers.get('content-type') || '';
    var datos = tipo.indexOf('application/json') >= 0 ? await respuesta.json() : null;
    if (respuesta.status === 401) {
      // El rechazo del login también llega como 401, y con el mensaje del propio backend
      // («contraseña incorrecta», «empresa sin acceso»…): se enseña ese, no uno nuestro.
      var mensajeSesion = datos && (datos.error || datos.detail) ? (datos.error || datos.detail) : null;
      if (ruta === '/api/login') {
        throw ErrorApi(mensajeSesion || 'No se ha podido iniciar sesión.', 401);
      }
      // Sin sesión: el acceso se enseña EN ESTE FRONTAL. Antes se redirigía a `/`, que es el
      // portal antiguo, y alguien que abría /hub/ se encontraba con otra interfaz.
      acceso();
      throw ErrorApi(mensajeSesion || 'Hace falta iniciar sesión.', 401);
    }
    if (!respuesta.ok) {
      // El backend contesta siempre en JSON con un `detail` ya redactado para el usuario. Si lo
      // que llega es HTML (un proxy, el servidor de ficheros) no se le enseña a nadie: se traduce.
      // Nuestro contrato de error es `{status, error, codigo}`; el `detail` es el de FastAPI
      // (validación de esquemas). Se lee el que haya para no perder «contraseña incorrecta».
      var detalle = datos && (datos.error || datos.detail) ? (datos.error || datos.detail) : null;
      if (!detalle) detalle = 'La plataforma ha respondido con un error ' + respuesta.status + '.';
      throw ErrorApi(detalle, respuesta.status);
    }
    return datos !== null ? datos : respuesta.text();
  }

  /* ── Atajos de la API ────────────────────────────────────────────────────────────────────── */

  var api = {
    pedir: pedir,
    entrar: function (email, password, codEmpresa, pin) {
      var cuerpo = { email: email, password: password };
      if (codEmpresa) cuerpo.cod_empresa = codEmpresa;
      if (pin) cuerpo.pin = pin;
      return pedir('/api/login', { cuerpo: cuerpo });
    },
    salir: function () { return pedir('/api/logout', { cuerpo: {} }); },
    yo: function () { return pedir('/api/yo'); },
    empresas: function () { return pedir('/api/empresas'); },
    modulos: function () { return pedir('/api/modulos'); },
    ejercicios: function (cod) { return pedir('/api/ejercicios?cod_empresa=' + encodeURIComponent(cod)); },
    /** Estado de la caché: sin empresa, el de toda la cartera. Con `cod_empresa=undefined` el
     *  backend responde 403 (no tiene esa empresa), así que el parámetro sólo viaja si hay valor. */
    cache: function (cod) {
      return pedir('/api/cache' + (cod ? '?cod_empresa=' + encodeURIComponent(cod) : ''));
    },
    dashboard: function (cod, year) {
      return pedir('/api/dashboard?cod_empresa=' + encodeURIComponent(cod) + '&year=' + year);
    },
    analisis: function (cod, year) {
      return pedir('/api/analisis?cod_empresa=' + encodeURIComponent(cod) + '&year=' + year);
    },
    /** Calcula un informe. Devuelve `{html, data, meta}`. */
    informe: function (peticion) { return pedir('/api/informe', { cuerpo: peticion }); },
    /** Igual que el informe, pero la respuesta es el fichero para descargar. */
    exportar: async function (peticion) {
      var respuesta = await fetch(BASE + '/api/informe/exportar', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(peticion)
      });
      if (!respuesta.ok) throw ErrorApi('No se ha podido exportar (error ' + respuesta.status + ').', respuesta.status);
      return respuesta.blob();
    },
    /** Relee del ERP. Devuelve un trabajo: se sigue con `estadoTrabajo(id)`. */
    refrescar: function (cod, year, ejerciciosSueltos) {
      return pedir('/api/refrescar', {
        cuerpo: { cod_empresa: cod, year: year, ejercicios: ejerciciosSueltos || undefined }
      });
    },
    estadoTrabajo: function (id) { return pedir('/api/trabajos/' + encodeURIComponent(id)); },
    interno: {
      resumen: function () { return pedir('/api/interno/resumen'); },
      cartera: function (year) { return pedir('/api/interno/cartera?year=' + year); },
      usuarios: function () { return pedir('/api/interno/usuarios'); },
      metricas: function (dias) { return pedir('/api/interno/metricas?dias=' + (dias || 7)); },
      avisos: function (todos) {
        return pedir('/api/interno/avisos?incluir_atendidos=' + (todos ? 'true' : 'false'));
      },
      umbrales: function (cod) { return pedir('/api/interno/umbrales?cod_empresa=' + encodeURIComponent(cod)); },
      ajustarUmbral: function (peticion) { return pedir('/api/interno/umbrales', { cuerpo: peticion }); },
      borrarCache: function (peticion) { return pedir('/api/interno/cache', { cuerpo: peticion }); }
    }
  };

  /** Espera a que un trabajo largo termine, avisando del progreso. */
  async function esperarTrabajo(trabajo, cadaMs, alProgresar) {
    var id = typeof trabajo === 'string' ? trabajo : (trabajo.trabajo || trabajo).id;
    for (;;) {
      var respuesta = await api.estadoTrabajo(id);
      var t = respuesta.trabajo || respuesta;
      if (alProgresar) alProgresar(t);
      if (t.estado === 'ok' || t.estado === 'error') return t;
      await new Promise(function (r) { setTimeout(r, cadaMs || 1500); });
    }
  }

  /* ── Estado de la sesión de trabajo ──────────────────────────────────────────────────────── */

  var estado = {
    usuario: null, interno: false, empresas: [], empresa: null,
    ejercicio: null, ejercicioInicio: null, modulos: [], listo: false,
    // Qué hay ya leído del ERP (empresa → ejercicios en caché). Es lo que permite abrir el hub
    // sin disparar cientos de lecturas contra el ERP de ABGA: si el ejercicio no está, se dice.
    cache: {}, ttl: 43200
  };

  /* ── Los datos del hub (los mismos objetos que usan sus pantallas) ───────────────────────── */

  var MOCK = null;
  var aplicacion = null;

  /** Sustituye el contenido de un dato del hub sin cambiar el objeto: las pantallas lo tienen
   *  cogido por referencia. Sirve igual para listas, para listas de listas y para objetos. */
  function reemplazar(destino, nuevos) {
    if (Array.isArray(destino)) {
      destino.length = 0;
      (nuevos || []).forEach(function (x) { destino.push(x); });
      return destino;
    }
    if (destino && typeof destino === 'object') {
      Object.keys(destino).forEach(function (k) { delete destino[k]; });
      Object.assign(destino, nuevos || {});
      return destino;
    }
    return nuevos;
  }

  /** Cambios al estado de la aplicación (los que el hub ya sabe pintar). */
  function parche(cambios) { if (aplicacion && aplicacion.setState) aplicacion.setState(cambios); }

  /* ── Traductores por pantalla ────────────────────────────────────────────────────────────── */

  var paneles = {};
  var cargadas = {};
  var enCurso = {};
  var oferta = false;   // hay una oferta en pantalla (traer del ERP): no la borra el cargador

  function registrar(nombre, traductor) { paneles[nombre] = traductor; }

  /** Contexto que recibe cada traductor. */
  function contexto(pantalla) {
    var sinDatos = [];
    return {
      pantalla: pantalla,
      api: api,
      estado: estado,
      MOCK: MOCK,
      empresa: estado.empresa,
      ejercicio: estado.ejercicio,
      anio: Number(estado.ejercicio),
      /** Deja un dato del hub con la forma que él ya esperaba. */
      poner: function (nombre, valor) {
        if (!(nombre in MOCK)) throw new Error('El hub no tiene ningún dato llamado ' + nombre);
        reemplazar(MOCK[nombre], valor);
        return MOCK[nombre];
      },
      /** Un dato del informe de un módulo: `ctx.informe('pyg')` → `data`. */
      informe: async function (modulo, parametros) {
        var respuesta = await api.informe({
          modulo: modulo, cod_empresa: estado.empresa, year: Number(estado.ejercicio),
          // El cuerpo de /api/informe valida la API: el campo de parámetros se llama `params`
          // (PeticionInforme tiene `extra='forbid'`: `parametros` daría 422).
          params: parametros || undefined
        });
        return respuesta.data || {};
      },
      /** ¿El ejercicio está ya leído y sin caducar? Si no, la pantalla no pide informes: pedirlos
       *  son cientos de consultas al ERP del cliente. */
      hayCache: function (anio) {
        var a = Number(anio || estado.ejercicio);
        var leido = (estado.cache[estado.empresa] || {})[a];
        if (!leido) return false;
        return (Date.now() - leido) < estado.ttl * 1000;
      },
      /** Un aviso que se queda en pantalla (no lo borra el cargador): para decir que algo del
       *  diseño no tiene datos detrás todavía. */
      avisoFijo: function (texto) {
        oferta = true;
        avisoConAccion(texto, '', function () {});
        var caja = document.getElementById('abga-aviso');
        if (caja) { var b = caja.querySelector('button'); if (b) b.remove(); }
      },
      /** Ofrece traer el ejercicio del ERP. No se hace solo: leer un ejercicio son cientos de
       *  consultas al ERP del cliente y eso lo decide una persona. */
      pedirDelErp: function (queFalta) {
        oferta = true;
        avisoConAccion((queFalta || 'Este ejercicio no está leído todavía.') +
          ' Traerlo del ERP puede tardar unos minutos.', 'Traer del ERP', function () {
          traerDelErp().then(function (t) {
            if (t && t.estado === 'error') { aviso('El ERP no ha devuelto los datos: ' + (t.mensaje || ''), 'error'); return; }
            var porEmpresa = (estado.cache[estado.empresa] = estado.cache[estado.empresa] || {});
            porEmpresa[estado.ejercicio] = Date.now();
            aviso('');
            cargarPantalla(pantalla, true);
          }).catch(function (fallo) { aviso('No se ha podido traer del ERP: ' + (fallo.message || fallo), 'error'); });
        });
        return false;
      },
      /** Lo que la plataforma todavía no sabe dar: se declara, no se inventa. */
      sinDatos: function (texto) { sinDatos.push(texto); console.info('[ABGA] sin datos:', texto); },
      sinDatosLista: sinDatos,
      /** Cambios al estado de la aplicación. */
      parchear: parche
    };
  }

  /* ── Aviso en pantalla (carga y errores) ─────────────────────────────────────────────────── */

  function aviso(texto, tono) {
    var caja = document.getElementById('abga-aviso');
    if (!texto) { if (caja) caja.remove(); return; }
    if (!caja) {
      caja = document.createElement('div');
      caja.id = 'abga-aviso';
      caja.style.cssText = 'position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:9999;' +
        'font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:9px 16px;' +
        'border-radius:9px;box-shadow:0 6px 20px rgba(3,14,30,.35);max-width:min(720px,92vw);text-align:center';
      document.body.appendChild(caja);
    }
    caja.textContent = texto;
    caja.style.background = tono === 'error' ? '#7f1d1d' : '#0f2f57';
    caja.style.color = '#fff';
  }

  /** Aviso con un botón: se usa para ofrecer algo que la plataforma no hace sola. */
  function avisoConAccion(texto, etiqueta, alPulsar) {
    aviso('');
    var caja = document.getElementById('abga-aviso');
    if (!caja) { aviso(texto); caja = document.getElementById('abga-aviso'); }
    caja.textContent = '';
    var texto_ = document.createElement('span');
    texto_.textContent = texto + ' ';
    var boton = document.createElement('button');
    boton.textContent = etiqueta;
    boton.style.cssText = 'margin-left:10px;border:0;border-radius:7px;padding:5px 12px;cursor:pointer;' +
      'background:#4a90d9;color:#fff;font:inherit;font-weight:600';
    boton.onclick = function () { aviso('Leyendo del ERP de ABGA…'); alPulsar(); };
    caja.appendChild(texto_);
    caja.appendChild(boton);
    return caja;
  }

  /* ── Acceso ─────────────────────────────────────────────────────────────────────────────── */

  /** Pantalla de acceso del propio frontal. Se construye aquí (no en `index.html`) para no tocar
   *  la estructura del hub: es una capa encima, igual que los avisos. Al entrar se recarga la
   *  página con la cookie ya puesta y la aplicación arranca con sesión. */
  function acceso() {
    if (document.getElementById('abga-acceso')) return;
    var caja = document.createElement('div');
    caja.id = 'abga-acceso';
    caja.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;' +
      'justify-content:center;background:var(--surface,#0d1424);';
    caja.innerHTML =
      '<form style="width:min(360px,92vw);background:var(--surface2,#ffffff);' +
      'border:1px solid var(--border,#e3e8f0);border-radius:12px;box-shadow:0 18px 50px rgba(0,0,0,.35);' +
      'padding:26px 24px 22px;font-family:inherit;">' +
        '<div style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:700;">ABGA Consultores</div>' +
        '<h1 style="margin:6px 0 14px;font-size:19px;font-weight:600;color:var(--text);">Plataforma financiera</h1>' +
        '<label style="display:block;font-size:12px;color:var(--muted);margin:12px 0 4px;">Correo electrónico</label>' +
        '<input name="email" type="email" required autocomplete="username" ' +
          'style="width:100%;height:38px;padding:0 10px;border:1px solid var(--border);border-radius:8px;' +
          'background:var(--surface);color:var(--text);font-size:14px;box-sizing:border-box;">' +
        '<label style="display:block;font-size:12px;color:var(--muted);margin:12px 0 4px;">Contraseña</label>' +
        '<input name="password" type="password" required autocomplete="current-password" ' +
          'style="width:100%;height:38px;padding:0 10px;border:1px solid var(--border);border-radius:8px;' +
          'background:var(--surface);color:var(--text);font-size:14px;box-sizing:border-box;">' +
        '<label style="display:block;font-size:12px;color:var(--muted);margin:12px 0 4px;">Número de empresa</label>' +
        '<input name="empresa" inputmode="numeric" required placeholder="6091" ' +
          'style="width:100%;height:38px;padding:0 10px;border:1px solid var(--border);border-radius:8px;' +
          'background:var(--surface);color:var(--text);font-size:14px;box-sizing:border-box;">' +
        '<div data-error role="alert" style="display:none;margin-top:12px;font-size:12.5px;color:var(--err,#c62828);line-height:1.45;"></div>' +
        '<button type="submit" style="width:100%;height:40px;margin-top:16px;border:none;border-radius:8px;' +
          'background:var(--btn,#1a4b8c);color:#fff;font-size:14px;font-weight:600;cursor:pointer;">Entrar</button>' +
        '<div style="margin-top:12px;font-size:11.5px;color:var(--muted);line-height:1.5;">' +
          'Cada usuario ve únicamente sus empresas. El número de empresa os lo facilita ABGA.</div>' +
      '</form>';
    document.body.appendChild(caja);

    var formulario = caja.querySelector('form');
    var cajaError = caja.querySelector('[data-error]');
    var boton = caja.querySelector('button[type=submit]');
    formulario.addEventListener('submit', async function (ev) {
      ev.preventDefault();
      cajaError.style.display = 'none';
      boton.disabled = true;
      boton.textContent = 'Entrando…';
      try {
        await api.entrar(formulario.email.value.trim(), formulario.password.value,
                         formulario.empresa.value.trim());
        location.reload();       // la cookie ya está puesta: se arranca con sesión
      } catch (fallo) {
        // El mensaje viene del propio backend («contraseña incorrecta», «empresa sin acceso»…).
        cajaError.textContent = fallo.message || 'No se ha podido iniciar sesión.';
        cajaError.style.display = 'block';
        boton.disabled = false;
        boton.textContent = 'Entrar';
      }
    });
  }

  /* ── Arranque y carga ────────────────────────────────────────────────────────────────────── */

  /** Quién soy, qué empresas veo, con qué ejercicio abre y qué módulos tiene la plataforma. */
  async function arrancar() {
    if (estado.listo) return estado;
    var quien = await api.yo();
    estado.usuario = quien.usuario || quien;
    estado.interno = quien.interno !== undefined ? !!quien.interno : !!(quien.usuario || {}).interno;
    var lista = await api.empresas();
    estado.empresas = (lista.empresas || lista || []).slice();
    var mias = estado.usuario && estado.usuario.empresas;
    if (mias && mias.length) {
      var permitidas = estado.empresas.filter(function (e) { return mias.indexOf(e.cod_empresa) >= 0; });
      if (permitidas.length) estado.empresas = permitidas;
    }
    try {
      var salud = await api.pedir('/api/salud');
      if (salud && salud.cache && salud.cache.ttl_apuntes) estado.ttl = Number(salud.cache.ttl_apuntes);
      estado.erpConfigurado = !!(salud && salud.erp);
    } catch (fallo) { /* sin ttl: se usa el de por defecto */ }
    try {
      var inventario = await api.cache();
      (inventario.cache || []).forEach(function (c) {
        var cod = String(c.empresa);
        estado.cache[cod] = estado.cache[cod] || {};
        estado.cache[cod][Number(c.ejercicio)] = Date.parse(c.actualizado || '') || 0;
      });
    } catch (fallo) { /* sin inventario: se comportará como si no hubiera nada en caché */ }

    if (estado.empresas.length) {
      // Se abre por una empresa que ya tenga un ejercicio leído: pedir un ejercicio frío son
      // cientos de consultas al ERP del cliente y no se hace por abrir un panel.
      var conDatos = estado.empresas.filter(function (e) {
        return Object.keys(estado.cache[e.cod_empresa] || {}).some(function (a) {
          return (Date.now() - estado.cache[e.cod_empresa][a]) < estado.ttl * 1000;
        });
      });
      var elegida = conDatos.length ? conDatos[0] : estado.empresas[0];
      estado.empresa = elegida.cod_empresa;
      estado.ejercicioInicio = elegida.ejercicio_inicio || null;
      var annos = await api.ejercicios(estado.empresa);
      var listaAnnos = (annos.ejercicios || []).map(function (a) { return Number(a.year || a); }).filter(Boolean);
      var cacheados = Object.keys(estado.cache[estado.empresa] || {}).map(Number)
        .filter(function (a) { return (Date.now() - estado.cache[estado.empresa][a]) < estado.ttl * 1000; });
      estado.ejercicio = cacheados.length ? Math.max.apply(null, cacheados)
        : (listaAnnos.length ? Math.max.apply(null, listaAnnos)
           : (estado.ejercicioInicio || new Date().getFullYear() - 1));
      estado.annosDisponibles = listaAnnos;
    }
    try { estado.modulos = (await api.modulos()).modulos || []; } catch (fallo) { estado.modulos = []; }
    estado.listo = true;
    return estado;
  }

  /** Trae un ejercicio del ERP. Es una acción explícita (ver `ctx.pedirDelErp`). */
  async function traerDelErp(anio) {
    var trabajo = await api.refrescar(estado.empresa, Number(anio || estado.ejercicio));
    return esperarTrabajo(trabajo, 2000, function (t) {
      aviso('Leyendo el ERP de ABGA… ' + Math.round((t.progreso || 0) * 100) + ' % ' + (t.mensaje || ''));
    });
  }

  /** Carga (o recarga) la pantalla que se está viendo. */
  async function cargarPantalla(nombre, forzar) {
    if (!nombre || !paneles[nombre] || !estado.listo) return;
    var ejercicio = (aplicacion && aplicacion.state && aplicacion.state.ejercicio) || estado.ejercicio;
    var clave = nombre + '|' + estado.empresa + '|' + ejercicio;
    if (enCurso[clave]) return enCurso[clave];
    if (cargadas[clave] && !forzar) return;
    var ctx = contexto(nombre);
    oferta = false;
    enCurso[clave] = (async function () {
      try {
        aviso('Cargando datos de la plataforma…');
        await paneles[nombre](ctx);
        Object.keys(cargadas).forEach(function (k) { if (k.indexOf(nombre + '|') === 0) delete cargadas[k]; });
        cargadas[clave] = true;
        parche({ __datos: Date.now() });
        if (!oferta) aviso('');
      } catch (fallo) {
        oferta = false;
        if (fallo && fallo.estado === 401) return;   // sin sesión: el acceso ya se está enseñando
        aviso('No se han podido cargar los datos: ' + (fallo.message || fallo), 'error');
      } finally {
        delete enCurso[clave];
      }
    })();
    return enCurso[clave];
  }

  /** Punto de entrada: lo llama el hub desde su `componentDidMount`. */
  async function cargar(componente) {
    aplicacion = componente;
    try {
      aviso('Conectando con la plataforma…');
      await arrancar();
      if (typeof window.ABGA_SEMBRAR === 'function') {
        window.ABGA_SEMBRAR(estado.empresas.map(function (e) {
          return {
            id: e.cod_empresa, nombre: e.nombre, nif: e.nif || '', forma: e.forma_juridica || '',
            cnae: e.cnae || '', ciudad: e.ciudad || '', asesor: e.asesor || '',
            alta: e.ejercicio_inicio ? String(e.ejercicio_inicio) : '', estado: e.estado || 'ok',
            email: e.email || '', telefono: e.telefono || '', contacto: e.contacto || '',
            iva: e.iva || '', empleados: e.empleados || 0, fact: e.fact || 0, factor: e.factor || 0,
            notas: e.notas || ''
          };
        }));
      }
      // El menú del hub no es el catálogo de módulos de la plataforma: es su propia navegación.
      // Lo único que decide la plataforma es qué se puede abrir: `envios` no tiene endpoint
      // todavía, y `duplicados` y `ajustes` son del panel interno de ABGA (`interno: true`).
      var internos = (estado.modulos || []).filter(function (m) { return m.interno; })
        .map(function (m) { return m.nombre; });
      var abiertas = MOCK.ENTREGADOS.slice();
      if (!estado.interno) {
        abiertas = abiertas.filter(function (k) {
          return internos.indexOf(k) < 0 && k !== 'ajustes';   // ajustes es del panel interno
        });
      }
      abiertas = abiertas.filter(function (k) { return k !== 'envios'; });
      reemplazar(MOCK.ENTREGADOS, abiertas);
      // La cabecera del hub dice si hay ERP y cuándo se leyó por última vez: es la lectura más
      // reciente que hay en la caché, no una hora inventada.
      var ultimaLectura = 0;
      Object.keys(estado.cache).forEach(function (cod) {
        Object.keys(estado.cache[cod]).forEach(function (a) {
          ultimaLectura = Math.max(ultimaLectura, estado.cache[cod][a]);
        });
      });
      var primero = estado.empresas.length ? estado.empresas[0].cod_empresa : null;
      parche({
        ejercicio: String(estado.ejercicio), role: estado.interno ? 'asesor' : 'cliente',
        infCliente: primero, concCliente: primero, proyCliente: primero,
        erpHay: !!estado.erpConfigurado, erpUltima: ultimaLectura || null
      });
      aviso('');
      cargarPantalla((componente.state && componente.state.screen) || 'inicio');
    } catch (fallo) {
      if (fallo && fallo.estado === 401) return;   // sin sesión: el acceso ya se está enseñando
      aviso('La plataforma no responde: ' + (fallo.message || fallo), 'error');
    }
  }

  /** La aplicación ha cambiado de pantalla, de empresa o de ejercicio. */
  function alCambiarEstado(anterior, cambio) {
    if (!aplicacion) return;
    var claves = [];
    if (cambio && typeof cambio === 'object') claves = Object.keys(cambio);
    else if (typeof cambio === 'function') {
      try { claves = Object.keys(cambio(anterior) || {}); } catch (fallo) { return; }
    } else return;
    var esCambio = claves.some(function (k) { return k === 'screen' || k === 'ejercicio' || k.indexOf('Cliente') >= 0; });
    if (!esCambio) return;
    var pantalla = claves.indexOf('screen') >= 0 ? cambio.screen : aplicacion.state.screen;
    // Cada pantalla del hub trabaja con su propia empresa (la llama «cliente»). OJO: hay claves
    // terminadas en «Cliente» que traen el NOMBRE (p. ej. `ajUmbralCliente`): si se cogiera ese
    // valor, la empresa de la sesión dejaría de ser un código y todas las llamadas siguientes
    // contestarían 404. Sólo se cambia cuando el valor es el código de una empresa conocida.
    if (claves.indexOf('screen') < 0 && anterior) {
      claves.forEach(function (k) {
        if (k.indexOf('Cliente') < 0 || anterior[k] === cambio[k] || !cambio[k]) return;
        var cod = String(cambio[k]);
        var conocida = (estado.empresas || []).some(function (e) { return String(e.cod_empresa) === cod; });
        if (conocida) estado.empresa = cod;
      });
    }
    cargarPantalla(pantalla);
  }

  return {
    error: ErrorApi, api: api, pedir: pedir, aviso: aviso, reemplazar: reemplazar,
    registrar: registrar, estado: estado, cargar: cargar, cargarPantalla: cargarPantalla,
    alCambiarEstado: alCambiarEstado, esperarTrabajo: esperarTrabajo,
    datos: function () { return MOCK; },
    _enlazar: function (mock) { MOCK = mock; }
  };
})();
