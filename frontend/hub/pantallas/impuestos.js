/* Impuestos · datos reales de la plataforma
 *
 * La pantalla de impuestos venía con una cartera inventada: el resultado de cada cliente en cada
 * modelo lo calculaba una fórmula escrita en el propio frontal (`impDatos`: facturación por
 * trimestre, plantilla, forma jurídica) y su estado —«presentado», «preparado», «pendiente»— se
 * deducía por la posición que el cliente ocupaba en la lista. Nada de eso existe en la plataforma,
 * que calcula impuestos **por empresa y ejercicio**, no por cliente ni por modelo presentado.
 *
 * Aquí se traduce lo que la plataforma sí sabe:
 *
 *   /api/informe (fiscal)             IVA, retenciones y pago fraccionado del trimestre consultado,
 *                                     obligaciones y vencimientos reales de esa empresa y ejercicio
 *   /api/informe (libro_iva)          base imponible derivada del trimestre (el ERP no la trae)
 *   /api/informe (libro_retenciones)  retenciones de trabajo y de profesionales del trimestre
 *   /api/informe (sumas_saldos)       saldo de las cuentas 47x que el propio módulo fiscal usa
 *
 * La tabla de la pantalla es una cartera × modelo. La plataforma no lleva el estado de la cartera,
 * así que las filas son las empresas **cuyo ejercicio ya está leído en la caché** (se mira el
 * inventario que ya tiene `datos.js`: es local, no despierta al ERP) y el estado de cada fila es lo
 * que se ha podido calcular, no lo que se ha presentado: la presentación telemática no está en la
 * plataforma. Los libros y el balance se piden sólo de la empresa que se está mirando; de las demás
 * empresas de la cartera basta el módulo fiscal (una consulta por empresa, y sólo de las leídas).
 *
 * Lo que la plataforma no tiene se declara con `ctx.sinDatos` y se deja vacío, nunca con cifras
 * inventadas: los textos y los controles del diseño que prometen lo contrario se listan con su
 * parche en `pantallas/impuestos.md`.
 *
 * Aviso de acoplamiento: `IMPUESTOS` (la matriz de la ficha de clientes) se rellena con los códigos
 * de estado nuevos —`con_obligacion`, `a_compensar`, `sin_obligacion`, `sin_apuntes`—, que la ficha
 * busca en `IMP_EST`. El parche P11 de `impuestos.md` (cambiar `IMP_EST`) va con este fichero: sin
 * él la ficha de clientes pintaría `IMP_EST[k2].l` de un código que no existe.
 */
ABGA.registrar('impuestos', async function (ctx) {
  'use strict';

  var empresa = ctx.empresa;
  var anio = ctx.anio;
  var hoy = new Date();
  var ttl = (ctx.estado.ttl || 43200) * 1000;
  var MAX_EMPRESAS = 30;   // tope de empresas de la cartera que se consultan de una vez

  // Trimestre que se enseña: el que corre cuando el ejercicio es el año en curso y, si el ejercicio
  // ya ha cerrado, el 4T, que es el último que se declara. El módulo fiscal admite 1-4 y devuelve
  // con él las obligaciones y los vencimientos de ese trimestre.
  var trimestre = anio === hoy.getFullYear() ? Math.floor(hoy.getMonth() / 3) + 1 : 4;

  // Estados posibles de una fila: lo que la plataforma ha calculado, nunca lo que se ha presentado.
  var ESTADOS = {
    a_ingresar:     { l: 'A ingresar · calculado', t: 'accent' },
    a_compensar:    { l: 'A compensar o a devolver', t: 'ok' },
    sin_obligacion: { l: 'Sin obligación en el trimestre', t: 'muted' },
    sin_apuntes:    { l: 'Sin apuntes en el trimestre', t: 'warn' },
    na:             { l: 'No aplica en este trimestre', t: 'muted' }
  };

  // Lo que la plataforma no tiene, dicho una vez por pantalla y no disimulado con ceros.
  [
    'la presentación telemática: la plataforma calcula los modelos, no los presenta ni guarda justificantes, acuses ni CSV',
    'el estado de preparación por cliente y modelo: la plataforma calcula por empresa y ejercicio, no lleva la cartera',
    'los modelos 115 (sólo aparece como retenciones a profesionales en el libro de retenciones), 130, 200, 347 y 390',
    'el asesor asignado y el NIF de cada empresa: /api/empresas no los devuelve',
    'el calendario de cada cliente: los vencimientos que se enseñan son los del trimestre consultado de cada empresa',
    'la situación fiscal por cliente en la ficha: la matriz de modelos se rellena con la empresa que se está analizando'
  ].forEach(function (texto) { ctx.sinDatos(texto); });

  var VACIO = { impModelo: '', impFilas: [], impCas: {}, impMeta: {}, impEst: {}, impBusy: {},
                impSel: null, impFiltro: 'todos' };

  // Sin el ejercicio leído no se pide ningún informe: leerlo son cientos de consultas al ERP de
  // ABGA y eso lo decide una persona (abajo se le ofrece).
  if (!ctx.hayCache()) {
    ctx.poner('VENC', []);
    ctx.poner('IMPUESTOS', []);
    ctx.parchear(VACIO);
    ctx.sinDatos('el ejercicio ' + anio + ' no está leído del ERP');
    ctx.pedirDelErp('El ejercicio ' + anio + ' no está leído todavía.');
    return;
  }

  /** Un informe de la plataforma de una empresa concreta. Los parámetros del módulo van en `params`. */
  function informe(cod, modulo, params) {
    return ctx.api.informe({ modulo: modulo, cod_empresa: cod, year: anio, params: params || {} })
      .then(function (respuesta) { return respuesta.data || {}; });
  }

  /** Número seguro: la API devuelve números, pero un null no puede convertirse en una cifra rara. */
  function num(v) { return typeof v === 'number' && isFinite(v) ? v : (Number(v) || 0); }

  /** Saldo al cierre del ejercicio de la primera cuenta que empieza por el prefijo dado. */
  function saldoCuenta(filas, prefijo) {
    var f = (filas || []).filter(function (x) { return String(x.cuenta || '').indexOf(prefijo) === 0; })[0];
    return f ? num(f.saldo_final) : null;
  }

  /* ── La empresa que se está mirando: el módulo fiscal del trimestre ───────────────────────── */

  var fis;
  try {
    fis = await informe(empresa, 'fiscal', { trimestre: trimestre });
  } catch (fallo) {
    ctx.poner('VENC', []);
    ctx.poner('IMPUESTOS', []);
    ctx.parchear(VACIO);
    ctx.sinDatos('el módulo fiscal de la empresa ' + empresa + ': ' + (fallo.message || fallo));
    return;
  }

  var detalle = fis.ivaTrimestreDetalle || [];
  var actual = fis.ivaTrimestreActual || {};
  var vencimientos = fis.vencimientos || [];
  var modelos = vencimientos.map(function (v) { return v.modelo; });
  if (modelos.indexOf('303') < 0) modelos.unshift('303');
  if (modelos.indexOf('111') < 0) modelos.push('111');

  /* ── Vencimientos reales del trimestre (los mismos que enseña Inicio) ─────────────────────── */

  var cartera = (ctx.estado.interno ? (ctx.estado.empresas || []).length : 1);
  var leidas = 0;
  Object.keys(ctx.estado.cache || {}).forEach(function (cod) {
    var t = (ctx.estado.cache[cod] || {})[anio];
    if (t && (hoy.getTime() - t) < ttl) leidas += 1;
  });
  var venc = vencimientos.map(function (v) {
    return {
      modelo: v.modelo, desc: v.concepto + (v.nota ? ' · ' + v.nota : ''),
      fecha: String(v.dia).padStart(2, '0') + '/' + String(v.mes).padStart(2, '0') + '/' + v.anio,
      // `clientes` y `prep` sólo los usa el cuadro de vencimientos de Inicio: se rellenan con el
      // mismo criterio que su traductor (empresas de la cartera · ejercicios leídos) para no
      // dejarlos a cero si la pantalla cambia antes de que Inicio vuelva a cargar.
      clientes: cartera, prep: leidas,
      iso: v.iso, humano: v.humano, aplica: v.aplica !== false, nota: v.nota || ''
    };
  });
  ctx.poner('VENC', venc);

  /* ── Cartera: las empresas con el ejercicio leído (mirar la caché es local) ───────────────── */

  var nombreDe = {};
  (ctx.estado.empresas || []).forEach(function (e) { nombreDe[e.cod_empresa] = e.nombre || e.cod_empresa; });

  var candidatas = [];
  if (ctx.hayCache()) candidatas.push(empresa);
  (ctx.estado.empresas || []).forEach(function (e) {
    var cod = e.cod_empresa;
    if (cod === empresa) return;
    var leido = (ctx.estado.cache[cod] || {})[anio];
    if (leido && (hoy.getTime() - leido) < ttl) candidatas.push(cod);
  });
  candidatas.sort(function (a, b) {
    if (a === empresa) return -1;
    if (b === empresa) return 1;
    return String(a) < String(b) ? -1 : 1;
  });
  if (candidatas.length > MAX_EMPRESAS) {
    ctx.sinDatos('la cartera completa: se consultan las ' + MAX_EMPRESAS + ' primeras empresas con el ejercicio leído');
    candidatas = candidatas.slice(0, MAX_EMPRESAS);
  }

  /* ── Los libros y el balance, sólo de la empresa en pantalla ──────────────────────────────── */

  var libroIva = null, libroRet = null, sumas = null;
  try { libroIva = await informe(empresa, 'libro_iva', { trimestre: trimestre }); }
  catch (fallo) { ctx.sinDatos('el libro de IVA: ' + (fallo.message || fallo)); }
  try { libroRet = await informe(empresa, 'libro_retenciones', { trimestre: trimestre }); }
  catch (fallo) { ctx.sinDatos('el libro de retenciones: ' + (fallo.message || fallo)); }
  try { sumas = await informe(empresa, 'sumas_saldos', { nivel: 4, top: 200, solo_con_saldo: true }); }
  catch (fallo) { ctx.sinDatos('el balance de sumas y saldos: ' + (fallo.message || fallo)); }

  /** El trimestre consultado dentro de un desglose por trimestre (libro de IVA, libro de retenciones). */
  function delTrimestre(lista) {
    return (lista || []).filter(function (d) { return String(d.trimestre) === String(fis.trimestre || trimestre); })[0] || {};
  }
  var ivaT = delTrimestre(libroIva && libroIva.porTrimestre);
  var retT = delTrimestre(libroRet && libroRet.porTrimestre);
  var filasSumas = (sumas && sumas.filas) || [];

  /* ── Un renglón por empresa y modelo, y el desglose de cada uno ───────────────────────────── */

  var filas = [], cas = {}, totalObligaciones = 0, conObligacion = 0;
  var sinDatosCartera = false;

  for (var i = 0; i < candidatas.length; i++) {
    var cod = candidatas[i];
    var f = cod === empresa ? fis : null;
    if (!f) {
      try { f = await informe(cod, 'fiscal', { trimestre: trimestre }); }
      catch (fallo) { sinDatosCartera = true; continue; }
    }
    var q = f.ivaTrimestreActual || {};
    var v202 = (f.vencimientos || []).filter(function (x) { return x.modelo === '202'; })[0];
    var aplica202 = !!(v202 && v202.aplica !== false);
    var esLaDePantalla = cod === empresa;

    // Lo que la plataforma ha calculado para esta empresa en este trimestre, modelo a modelo.
    var porModelo = {
      '303': { importe: num(q.saldo), aplica: true, apuntes: num(q.nLineas) },
      '111': { importe: num(q.retenciones), aplica: true, apuntes: num(q.nLineas) },
      '202': { importe: aplica202 ? num(f.obligacion202) : 0, aplica: aplica202, apuntes: aplica202 ? 1 : 0 }
    };

    modelos.forEach(function (m) {
      var d = porModelo[m];
      if (!d) return;
      var est, grupo;
      if (!d.aplica) { est = 'na'; grupo = 'sin_obligacion'; }
      else if (!d.apuntes) { est = 'sin_apuntes'; grupo = 'sin_obligacion'; }
      else if (d.importe > 0) { est = 'a_ingresar'; grupo = 'a_ingresar'; }
      else if (d.importe < 0) { est = 'a_compensar'; grupo = 'a_compensar'; }
      else { est = 'sin_obligacion'; grupo = 'sin_obligacion'; }

      var e = ESTADOS[est];
      filas.push({
        id: cod, nombre: nombreDe[cod] || cod, nif: '', asesor: '',
        modelo: m, importe: d.importe, aplica: d.aplica, apuntes: d.apuntes,
        tipo: d.importe > 0 ? 'A ingresar' : d.importe < 0 ? 'A compensar o a devolver' : 'Sin importe en el trimestre',
        est: est, estL: e.l, tono: e.t, grupo: grupo,
        aIngresar: d.importe > 0 ? d.importe : 0, aCompensar: d.importe < 0 ? Math.abs(d.importe) : 0,
        trimestre: num(f.trimestre), periodo: f.periodo || ''
      });
      if (grupo === 'a_ingresar') { totalObligaciones += d.importe; conObligacion += 1; }
    });

    /* ── El desglose que se abre al pulsar el renglón ──────────────────────────────────────── */

    var k303 = cod + '|303';
    cas[k303] = [
      ['472', 'IVA soportado contabilizado en el trimestre (cuenta 472)', num(q.soportado), 'importe'],
      ['477', 'IVA repercutido contabilizado en el trimestre (cuenta 477)', num(q.repercutido), 'importe'],
      ['Liquidación', 'IVA contabilizado del trimestre: repercutido − soportado (no es la declaración presentada)', num(q.saldo), 'importe'],
      ['Apuntes', 'Líneas del trimestre en el libro', num(q.nLineas), 'numero']
    ];
    var k111 = cod + '|111';
    cas[k111] = [
      ['4751', 'Retenciones contabilizadas en el trimestre (cuenta 4751)', num(q.retenciones), 'importe'],
      ['Apuntes', 'Líneas del trimestre en el libro', num(q.nLineas), 'numero']
    ];
    var k202 = cod + '|202';
    cas[k202] = [
      ['Base', 'Base del pago fraccionado: ingresos 70x − gastos 6xx del ejercicio completo', num(f.baseIS), 'importe'],
      ['Porcentaje', 'Porcentaje que aplica la plataforma sobre esa base', num(f.porcentajeIS) * 100, 'porcentaje'],
      ['Pago', 'Pago fraccionado estimado (base × porcentaje)', num(f.pagoFraccionadoIS), 'importe']
    ];
    if (!aplica202) {
      cas[k202].unshift(['202', 'El módulo fiscal no exige el 202 en este trimestre' +
        (v202 && v202.nota ? ': ' + v202.nota : ''), '', 'texto']);
    }

    // Sólo de la empresa que se está mirando se piden los libros y el balance: la base derivada del
    // IVA, el desglose de las retenciones y el saldo de las cuentas de Hacienda que usa el módulo.
    if (esLaDePantalla) {
      if (ivaT && ivaT.baseRepercutida !== undefined) {
        cas[k303].splice(1, 0, ['Base 01–09', 'Base imponible derivada del IVA repercutido (libro de IVA: el ERP no trae la base)', num(ivaT.baseRepercutida), 'importe']);
      }
      if (retT && retT.trabajo !== undefined) {
        cas[k111] = [
          ['4751 · trabajo', 'Retenciones de trabajo del trimestre (nóminas) · lo que recoge el 111', num(retT.trabajo), 'importe'],
          ['4751 · profesionales', 'Retenciones de actividades profesionales del trimestre · lo que recoge el 115', num(retT.profesionales), 'importe'],
          ['4751 · otras', 'Otras retenciones de la cuenta 4751 en el trimestre', num(retT.otras), 'importe'],
          ['Base', 'Base derivada de los rendimientos del trabajo (libro de retenciones)', num(retT.baseTrabajo), 'importe'],
          ['Apuntes', 'Líneas del trimestre en el libro', num(q.nLineas), 'numero']
        ];
      }
      var s472 = saldoCuenta(filasSumas, '472');
      var s477 = saldoCuenta(filasSumas, '477');
      if (s472 !== null) cas[k303].push(['4720', 'Saldo de la cuenta 4720 en el ejercicio (balance de sumas y saldos)', s472, 'importe']);
      if (s477 !== null) cas[k303].push(['4770', 'Saldo de la cuenta 4770 en el ejercicio (balance de sumas y saldos)', s477, 'importe']);
      var s4751 = saldoCuenta(filasSumas, '4751');
      if (s4751 !== null) cas[k111].push(['4751', 'Saldo de la cuenta 4751 en el ejercicio (balance de sumas y saldos)', s4751, 'importe']);
      var s4752 = saldoCuenta(filasSumas, '4752');
      if (s4752 !== null) cas[k202].push(['4752', 'Saldo de la cuenta 4752, Hacienda acreedora por IS, en el ejercicio (balance de sumas y saldos)', s4752, 'importe']);
    }
  }

  /* ── La matriz modelo × trimestre de la ficha de clientes ─────────────────────────────────── */

  var IMP_DESC = { '303': 'IVA trimestral', '111': 'Retenciones IRPF', '202': 'Pago fraccionado IS' };
  function celdaDe(modelo, d) {
    if (modelo === '202') {
      // El calendario del módulo sólo obliga el 202 en el 1T y el 3T, y se calcula del trimestre
      // consultado: en el resto de celdas no hay nada que enseñar y se deja «—», sin inventarlo.
      var esConsultado = String(d.trimestre) === String(fis.trimestre || trimestre);
      if (!esConsultado) return 'na';
      if (!(fis.aplicaModelo202)) return 'na';
      return num(fis.obligacion202) > 0 ? 'con_obligacion' : 'sin_obligacion';
    }
    if (!d.nLineas) return 'sin_apuntes';
    var importe = modelo === '303' ? num(d.saldo) : num(d.retenciones);
    if (importe > 0) return 'con_obligacion';
    if (importe < 0) return 'a_compensar';
    return 'sin_obligacion';
  }
  var matriz = ['303', '111', '202'].map(function (m) {
    var celdas = detalle.map(function (d) { return celdaDe(m, d); });
    if (m === '303') {
      celdas.push(num(fis.saldoIVA) > 0 ? 'con_obligacion' : num(fis.saldoIVA) < 0 ? 'a_compensar' : 'sin_obligacion');
    } else if (m === '111') {
      celdas.push(num(fis.retencionesIRPF) > 0 ? 'con_obligacion' : 'sin_obligacion');
    } else {
      celdas.push('na');
    }
    return { modelo: m, desc: IMP_DESC[m] || '', c: celdas };
  });
  ctx.poner('IMPUESTOS', matriz);

  /* ── La cabecera y el estado de la pantalla ───────────────────────────────────────────────── */

  var plazo = venc.filter(function (v) { return v.modelo === '303'; })[0] || venc[0] || null;
  var dias = null;
  if (plazo && plazo.iso) {
    dias = Math.ceil((new Date(plazo.iso + 'T00:00:00').getTime() - hoy.getTime()) / 86400000);
  }
  var t = num(fis.trimestre) || trimestre;
  var periodo = fis.periodo || '';
  var meta = {
    trimestre: t, periodo: periodo, anio: anio,
    periodoTxt: t + 'T ' + anio + (periodo ? ' (' + periodo + ')' : ''),
    fechaLimite: plazo ? plazo.iso : '', fechaLimiteTexto: plazo ? plazo.humano : '',
    dias: dias,
    plazoTxt: dias === null ? 'sin vencimiento en la plataforma'
      : dias > 0 ? 'plazo hasta el ' + plazo.humano + ' · quedan ' + dias + ' días'
      : dias === 0 ? 'el plazo vence hoy (' + plazo.humano + ')'
      : 'plazo vencido el ' + plazo.humano + ' (hace ' + Math.abs(dias) + ' días)',
    obligacionTotal: totalObligaciones, conObligacion: conObligacion,
    empresas: candidatas.length, generado: new Date().toISOString()
  };

  if (sinDatosCartera) ctx.sinDatos('el módulo fiscal de alguna empresa de la cartera');
  if (!filas.length) ctx.sinDatos('ninguna empresa de la cartera tiene el ejercicio ' + anio + ' calculable');

  ctx.parchear({
    impModelo: modelos.indexOf('303') >= 0 ? '303' : (modelos[0] || ''),
    impFilas: filas, impCas: cas, impMeta: meta,
    impEst: {}, impBusy: {}, impSel: null, impFiltro: 'todos'
  });
});
