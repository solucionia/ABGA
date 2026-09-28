/* Inicio · datos reales de la plataforma
 *
 * El panel del hub traía cinco indicadores escritos a mano, una lista de tareas, un aviso de
 * vencimientos y una actividad «en directo» que era inventada. Todo eso sale ahora de:
 *
 *   /api/dashboard        indicadores, avisos y meta (si los datos vienen de caché o del ERP)
 *   /api/analisis         las 50 comprobaciones: de ahí salen las tareas que hay que revisar
 *   /api/informe          conciliación, duplicados y fiscal (los tres módulos del resumen)
 *   /api/interno/resumen  la actividad real de la plataforma (últimas ejecuciones) — sólo ABGA
 *
 * Lo que la plataforma no sabe todavía —envíos a clientes, plazos por tarea, asignación de tareas—
 * no se rellena: se queda a la vista en blanco y se declara con `ctx.sinDatos`.
 */
ABGA.registrar('inicio', async function (ctx) {
  var empresa = ctx.empresa;
  var anio = ctx.anio;
  var hoy = new Date();

  // Sin el ejercicio leído del ERP no se pide ningún informe: leerlo son cientos de consultas al
  // ERP de ABGA y eso lo decide una persona (abajo se le ofrece).
  if (!ctx.hayCache()) {
    var vacios = [];
    for (var d = 0; d < 14; d++) vacios.push(0);
    var etiquetas = [];
    for (var e2 = 13; e2 >= 0; e2--) {
      var dia = new Date(hoy.getTime() - e2 * 86400000);
      etiquetas.push(String(dia.getDate()).padStart(2, '0') + '/' + String(dia.getMonth() + 1).padStart(2, '0'));
    }
    ctx.poner('DIAS14', etiquetas); ctx.poner('IA14', vacios); ctx.poner('HUM14', vacios.slice());
    ctx.poner('NOTIFS', []); ctx.poner('VENC', []);
    ctx.parchear({ tareas: [], tareasTodas: true, dups: [], feed: [],
      datosInicio: { clientes: (ctx.estado.empresas || []).length, clientesSub: 'cartera de la plataforma',
                     concPendientes: 0, concSub: 'sin datos del ejercicio', envios: 0,
                     enviosSub: 'el envío de informes aún no está en la plataforma',
                     vencDias: 0, vencSub: 'sin datos del ejercicio', riesgoDuplicados: null } });
    ctx.sinDatos('el ejercicio ' + anio + ' no está leído del ERP');
    ctx.pedirDelErp('El ejercicio ' + anio + ' no está leído todavía.');
    return;
  }

  var dash = await ctx.api.dashboard(empresa, anio);
  // Caché caducada: el panel sale igual (con los datos que hay) y el backend está refrescando
  // el ejercicio detrás. Se dice en pantalla, porque el cliente tiene que saber de cuándo son
  // los datos que está mirando.
  var caducados = ((dash.meta || {}).caducados) || [];
  if (caducados.length) {
    ctx.avisoFijo('Datos del ejercicio ' + caducados.join(', ') + ' leídos de la caché: ' +
      'el ERP se está actualizando en segundo plano y entrarán solos.');
  }
  var analisis = await ctx.api.analisis(empresa, anio);
  var d = dash.data || {};
  var a = analisis.data || {};
  var kpis = d.kpis || {};

  /* ── Las tres partes del resumen que el panel enseña en los indicadores ──────────────────── */

  var conc = null, dup = null, fis = null;
  try { conc = await ctx.informe('conciliacion'); } catch (fallo) { ctx.sinDatos('conciliación: ' + fallo.message); }
  if (ctx.estado.interno) {
    try { dup = await ctx.informe('duplicados'); } catch (fallo) { ctx.sinDatos('duplicados: ' + fallo.message); }
  } else {
    ctx.sinDatos('duplicados (es del panel interno de ABGA)');
  }
  try { fis = await ctx.informe('fiscal'); } catch (fallo) { ctx.sinDatos('fiscal: ' + fallo.message); }

  /* ── Duplicados: el hub los quiere con la forma de su pantalla y de su indicador ─────────── */

  var parejasHub = [];
  if (dup) {
    parejasHub = (dup.duplicados || []).map(function (p, i) {
      function lado(x) {
        return {
          num: x.documento || x.id, fecha: x.fechaTexto || '', base: x.importe || 0, iva: 0,
          concepto: x.descripcion || '', asiento: x.id || '', reg: ''
        };
      }
      return {
        id: 'D' + (i + 1), cli: empresa, nif: '', proveedor: (p.coincidencias || []).join(' · '),
        score: p.puntuacion, motivo: (p.criterios || []).join(', '), coinciden: p.criterios || [],
        a: lado(p.a || {}), b: lado(p.b || {}), estado: 'pendiente', nivel: p.nivel,
        gravedad: p.gravedad, importe: p.importeRiesgo
      };
    });
    ctx.poner('DUPS', parejasHub);
    ctx.parchear({ dups: parejasHub.map(function (x) { return Object.assign({}, x); }) });
  }

  /* ── Tareas: los hallazgos del análisis que piden revisión humana ────────────────────────── */

  var FAMILIA = { contable: 'Contabilidad', fiscal: 'Fiscal', financiero: 'Financiero',
                  mercantil: 'Mercantil', laboral: 'Laboral' };
  var PANTALLA = { dup: 'duplicados', conc: 'conciliacion', iva: 'impuestos', retenciones: 'impuestos',
                   is: 'impuestos', cuadre: 'conciliacion', tesoreria: 'informe', endeudamiento: 'informe' };
  function pantallaDe(h) {
    var claves = Object.keys(PANTALLA);
    for (var i = 0; i < claves.length; i++) if (h.id && h.id.indexOf(claves[i]) >= 0) return PANTALLA[claves[i]];
    return h.familia === 'fiscal' ? 'impuestos' : 'informe';
  }
  var tareas = (a.hallazgos || []).filter(function (h) {
    return h.nivel === 'alerta' || h.nivel === 'aviso';
  }).map(function (h, i) {
    return {
      id: i + 1, tipo: FAMILIA[h.familia] || h.familia, tone: h.nivel === 'alerta' ? 'err' : 'warn',
      cli: empresa, desc: (h.titulo ? h.titulo + ': ' : '') + (h.detalle || ''),
      importe: h.importe || 0, nivel: h.nivel, recomendacion: h.recomendacion || '',
      vence: '—', venceTone: 'muted', asignado: 'Sin asignar', screen: pantallaDe(h)
    };
  });
  ctx.parchear({ tareas: tareas, tareasTodas: true });

  /* ── Avisos: los de la propia plataforma, en la campana y en el registro de actividad ───── */

  var avisosInternos = [];
  var ejecuciones = [];
  var resumenInterno = null;
  if (ctx.estado.interno) {
    try {
      resumenInterno = await ctx.api.interno.resumen();
      avisosInternos = resumenInterno.avisos || [];
      ejecuciones = resumenInterno.ejecuciones || [];
    } catch (fallo) { ctx.sinDatos('panel interno: ' + fallo.message); }
  }
  try {
    var listaAvisos = await ctx.api.interno.avisos(false);
    avisosInternos = (listaAvisos.avisos || []).concat(avisosInternos);
  } catch (fallo) { /* un cliente no ve el panel interno: no pasa nada */ }

  function hace(instante) {
    var t = new Date(instante);
    if (isNaN(t.getTime())) return '';
    var minutos = Math.round((hoy - t) / 60000);
    if (minutos < 1) return 'ahora mismo';
    if (minutos < 60) return 'hace ' + minutos + ' min';
    if (minutos < 60 * 24) return 'hace ' + Math.round(minutos / 60) + ' h';
    return 'hace ' + Math.round(minutos / (60 * 24)) + ' días';
  }
  var TONO_AVISO = { error_erp: 'err', informes_parciales: 'warn', sin_datos: 'warn', denegado: 'err' };
  var notifs = avisosInternos.slice(0, 6).map(function (av) {
    return {
      txt: av.modulo + ' · ' + (av.detalle || ''), t: hace(av.primero),
      tone: TONO_AVISO[av.tipo] || 'warn'
    };
  });
  var avisosTexto = (d.avisos || []).concat(a.avisos || []).map(function (texto) {
    return { txt: texto, t: 'del informe', tone: 'warn' };
  });
  ctx.poner('NOTIFS', notifs.concat(avisosTexto).slice(0, 6));
  ctx.parchear({ notifRead: false });

  /* ── Actividad: lo que ha corrido de verdad (sustituye al registro inventado) ─────────────── */

  var nombreDe = {};
  (ctx.estado.empresas || []).forEach(function (e) { nombreDe[e.cod_empresa] = e.nombre; });
  var feed = ejecuciones.slice(0, 7).map(function (e) {
    var t = new Date(e.instante);
    var h = isNaN(t.getTime()) ? '' : String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0');
    var estado = e.estado === 'ok' ? '' : ' · ' + e.estado;
    return {
      id: e.id, h: h,
      txt: (e.modulos || 'consulta') + estado + (e.desde_cache ? ' · desde caché' : ' · leyendo el ERP') +
           (e.segundos !== null && e.segundos !== undefined ? ' (' + Number(e.segundos).toFixed(1) + ' s)' : ''),
      cli: nombreDe[e.cod_empresa] || e.cod_empresa, tone: e.estado === 'ok' ? (e.desde_cache ? 'ok' : 'ai') : 'err'
    };
  });
  if (feed.length) {
    ctx.parchear({ feed: feed });
  } else {
    ctx.sinDatos('actividad de la plataforma (el registro de ejecuciones es del panel interno)');
  }

  /* ── La gráfica: los últimos 14 días de trabajo real, de caché o yendo al ERP ─────────────── */

  var dias = [], deCache = [], alErp = [];
  for (var k = 13; k >= 0; k--) {
    var dia = new Date(hoy.getTime() - k * 86400000);
    var clave = dia.toISOString().slice(0, 10);
    dias.push(String(dia.getDate()).padStart(2, '0') + '/' + String(dia.getMonth() + 1).padStart(2, '0'));
    var delDia = ejecuciones.filter(function (e) { return String(e.instante || '').slice(0, 10) === clave; });
    deCache.push(delDia.filter(function (e) { return e.desde_cache; }).length);
    alErp.push(delDia.filter(function (e) { return !e.desde_cache; }).length);
  }
  ctx.poner('DIAS14', dias);
  ctx.poner('IA14', deCache);
  ctx.poner('HUM14', alErp);

  /* ── Vencimientos: los modelos reales del ejercicio, con su fecha límite ──────────────────── */

  var preparados = 0;
  try {
    var cache = await ctx.api.cache();
    preparados = (cache.cache || []).filter(function (c) { return Number(c.ejercicio) === anio; }).length;
  } catch (fallo) { /* sin caché a la vista */ }
  var vencimientos = (fis && fis.vencimientos) || [];
  var venc = vencimientos.map(function (v) {
    return {
      modelo: v.modelo, desc: v.concepto + (v.nota ? ' · ' + v.nota : ''),
      fecha: v.dia + '/' + String(v.mes).padStart(2, '0') + '/' + v.anio,
      clientes: (ctx.estado.interno ? (resumenInterno && resumenInterno.empresas ? resumenInterno.empresas.length : 0) : 1),
      prep: preparados, iso: v.iso, aplica: v.aplica
    };
  });
  if (venc.length) ctx.poner('VENC', venc);
  else ctx.sinDatos('vencimientos fiscales del ejercicio');

  /* ── Los cinco indicadores del panel ─────────────────────────────────────────────────────── */

  var concPendientes = conc ? (conc.n_cuentas_pendientes || conc.kpis && conc.kpis.n_cuentas_pendientes || 0) : 0;
  var concAlta = conc ? (conc.hallazgos || []).filter(function (h) { return h.nivel === 'ALTA'; }).length : 0;
  var proximo = venc.filter(function (v) { return v.aplica !== false; })[0];
  var vencDias = 0, vencSub = 'sin vencimientos en la plataforma';
  if (proximo && proximo.iso) {
    var limite = new Date(proximo.iso + 'T00:00:00');
    vencDias = Math.max(0, Math.ceil((limite - hoy) / 86400000));
    vencSub = proximo.fecha + ' · modelo ' + proximo.modelo + (proximo.aplica === false ? ' (no aplica)' : '');
  }
  ctx.parchear({
    datosInicio: {
      clientes: ctx.estado.interno ? (ctx.estado.empresas || []).length : 1,
      clientesSub: ctx.estado.interno ? 'cartera de la plataforma' : 'tu empresa',
      concPendientes: conc ? (conc.kpis ? conc.kpis.n_cuentas_pendientes : conc.n_cuentas_pendientes) : 0,
      concRiesgo: concAlta,
      concSub: conc ? (concAlta + ' hallazgos de gravedad alta · ' + (conc.n_hallazgos || 0) + ' en total') : 'sin datos',
      envios: 0,
      enviosSub: 'el envío de informes aún no está en la plataforma',
      vencDias: vencDias, vencSub: vencSub,
      riesgoDuplicados: dup ? dup.importeRiesgoTotal : null,
      duplicados: dup ? dup.totalDuplicados : 0,
      ingresos: kpis.totalIngresos || 0, resultado: kpis.resultadoNeto || 0,
      desdeCache: !!(dash.meta && dash.meta.desde_cache)
    }
  });
});
