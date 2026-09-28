/* Conciliación de mayores · datos reales de la plataforma
 *
 * Lo que la pantalla esperaba: pares «apunte del mayor ⇄ movimiento del extracto bancario», con
 * movimientos generados a mano (P_BANCO, P_CLI, P_PROV), una propuesta de casado de la IA con su
 * porcentaje de confianza y una validación por persona.
 *
 * Lo que la plataforma tiene (módulo `conciliacion`): punteo contable del ejercicio —cuentas y
 * terceros con partidas sin puntear, su antigüedad, su nivel de riesgo y los hallazgos—. No hay
 * extractos bancarios, ni propuesta automática de casación, ni confianza de ninguna IA: nada de eso
 * se puede inventar, así que se declara con `ctx.sinDatos`.
 *
 * La traducción: cada cuenta (y cada tercero) con partidas pendientes es una fila de la
 * conciliación. El lado del mayor lleva lo que sí se sabe de esa cuenta (fecha de la partida más
 * antigua, cuántas partidas sin puntear, cuánto suman); el lado del extracto va vacío porque no hay
 * extracto. Por eso el estado sólo puede ser «sin casar» o «cuadrada»: «diferencia» necesita un
 * extracto con el que comparar.
 *
 * Las filas de cada cuenta quedan además en `window.ABGA_CONC` (clave «empresa|cuenta») para que el
 * selector de cuenta pueda pedirlas en vez de generarlas (ver el parche propuesto en el .md).
 *
 * Módulo: `conciliacion` → POST /api/informe
 */
(function () {
  'use strict';

  ABGA.registrar('conciliacion', async function (ctx) {
    var empresa = ctx.empresa;
    var anio = ctx.anio;

    // El informe se recorta a las cuentas y terceros que se piden: el módulo trae 12 y 10 por defecto
    // (top_cuentas / top_terceros) y están ordenados por riesgo. No son todas: hay ejercicios con más
    // de 400 cuentas con pendiente, y eso se declara.
    var TOP_CUENTAS = 25;
    var TOP_TERCEROS = 15;
    var TODAS = '';   // código de la opción «todas las cuentas y terceros»

    /* ── Lo que la pantalla no puede pedir ───────────────────────────────────────────────────── */

    if (!ctx.hayCache()) {
      sinCuentas(ctx, 'el ejercicio ' + anio + ' no está leído del ERP');
      ctx.sinDatos('la conciliación del ejercicio ' + anio + ' (no está leído del ERP)');
      ctx.pedirDelErp('El ejercicio ' + anio + ' no está leído todavía.');
      return;
    }

    var d;
    try {
      d = await informeConParametros(ctx, 'conciliacion', { top_cuentas: TOP_CUENTAS, top_terceros: TOP_TERCEROS });
    } catch (fallo) {
      sinCuentas(ctx, 'el informe de conciliación no se ha podido calcular');
      ctx.parchear({ concStatus: 'error' });
      ctx.sinDatos('la conciliación: ' + (fallo.message || fallo));
      return;
    }

    /* ── Una fila por cuenta y por tercero con partidas pendientes ───────────────────────────── */

    var filas = [];
    var porClave = {};    // «empresa|cuenta» → las filas de esa cuenta (lo que pide el selector)
    var opciones = [];

    (d.cuentas || []).forEach(function (c) {
      var fila = filaDeCuenta(empresa, c, filas.length);
      filas.push(fila);
      porClave[empresa + '|' + c.cuenta] = [fila];
      opciones.push({ cod: c.cuenta, nombre: c.cuenta + ' · ' + (c.grupo || ''), tipo: 'vacia' });
    });

    (d.terceros || []).forEach(function (t) {
      var fila = filaDeTercero(empresa, t, filas.length);
      filas.push(fila);
      porClave[empresa + '|T:' + t.tercero] = [fila];
      opciones.push({ cod: 'T:' + t.tercero, nombre: 'Tercero · ' + t.tercero, tipo: 'vacia' });
    });

    opciones.unshift({
      cod: TODAS,
      nombre: 'Todas · ' + filas.length + ' cuentas y terceros con pendiente',
      tipo: 'vacia'
    });
    porClave[empresa + '|' + TODAS] = filas;

    // Las filas quedan a mano del hub: si en el selector se elige otra cuenta (o otro cliente),
    // `loadConc` las pide aquí en vez de inventarlas.
    raiz().ABGA_CONC = porClave;

    ctx.poner('CUENTAS', opciones);
    ctx.parchear({
      concCliente: empresa,
      concCuenta: TODAS,
      concStatus: 'ready',
      concRows: filas.map(function (r) { return Object.assign({}, r); }),
      concFilter: 'todas',
      // El punteo del ejercicio, tal cual: lo que la pantalla no pinta también es real.
      concResumen: resumen(d)
    });

    /* ── Lo que la plataforma no da en esta pantalla ─────────────────────────────────────────── */

    ctx.sinDatos('el extracto bancario (Norma 43 o similar): la plataforma no lo tiene');
    ctx.sinDatos('los movimientos casados con el mayor: no hay casación, sólo punteo contable');
    ctx.sinDatos('la propuesta automática de casación y su porcentaje de confianza: no existe');
    ctx.sinDatos('la validación por persona: no hay validaciones guardadas');
    ctx.sinDatos('la diferencia entre mayor y extracto: sin extracto no hay nada que comparar');
    if (numero(d.n_cuentas_pendientes) > (d.cuentas || []).length) {
      ctx.sinDatos('las demás cuentas con pendiente: el informe devuelve las ' + (d.cuentas || []).length +
        ' de mayor riesgo y el ejercicio tiene ' + numero(d.n_cuentas_pendientes) + ' con partidas sin puntear');
    }
    if ((d.hallazgos || []).length) {
      ctx.sinDatos('los ' + numero(d.n_hallazgos) + ' hallazgos del informe (' + euros(numero(d.importe_anomalias)) +
        '): vienen completos en los datos, pero la pantalla no tiene dónde pintarlos');
    }
  });

  /* ── Traducción de una cuenta o un tercero a una fila ──────────────────────────────────────── */

  /** Una cuenta del mayor con partidas sin puntear. */
  function filaDeCuenta(empresa, c, i) {
    var pendientes = numero(c.n_pendientes);
    var partes = numero(c.n);
    var concepto = (c.grupo || '') + ' · ' + pendientes + (partes ? ' de ' + partes : '') +
                   ' partidas sin puntear';
    return partida(empresa, c.cuenta, i, {
      fecha: c.fecha_antigua_es || '',
      asiento: c.cuenta || '',
      concepto: concepto,
      importe: numero(c.pendiente)
    }, {
      origen: 'cuenta',
      cuenta: c.cuenta || '', grupo: c.grupo || '',
      debe: numero(c.debe), haber: numero(c.haber), saldo: numero(c.saldo),
      n: partes, n_pendientes: pendientes, pendiente: numero(c.pendiente),
      n_punteadas: numero(c.n_punteadas), pct_pendiente: numero(c.pct_pendiente),
      antiguedad_dias: numero(c.antiguedad_dias), nivel: c.nivel || '', riesgo: numero(c.riesgo),
      fecha_antigua: numero(c.fecha_antigua), fecha_reciente: numero(c.fecha_reciente)
    });
  }

  /** Un tercero (proveedor o cliente) con partidas sin puntear, con sus cuentas. */
  function filaDeTercero(empresa, t, i) {
    var pendientes = numero(t.n_pendientes);
    var cuentas = numero(t.n_cuentas);
    var concepto = 'Tercero · ' + (t.grupo || '') + ' · ' + pendientes +
                   ' partidas sin puntear en ' + cuentas + ' cuenta' + (cuentas === 1 ? '' : 's');
    return partida(empresa, 'T:' + t.tercero, i, {
      fecha: t.fecha_antigua_es || '',
      asiento: t.cuentas_texto || '',
      concepto: concepto,
      importe: numero(t.pendiente)
    }, {
      origen: 'tercero',
      tercero: t.tercero || '', grupo: t.grupo || '', cuentas: t.cuentas || [],
      cuenta: t.cuentas_texto || '',
      debe: numero(t.debe), haber: numero(t.haber), saldo: numero(t.saldo),
      n: cuentas, n_pendientes: pendientes, pendiente: numero(t.pendiente),
      antiguedad_dias: numero(t.antiguedad_dias), nivel: t.nivel || '', riesgo: numero(t.riesgo),
      fecha_antigua: numero(t.fecha_antigua)
    });
  }

  /** La forma común de la fila: la pantalla la pinta como «mayor ⇄ extracto». El lado del extracto va
   *  a null a propósito: sin extracto no hay nada que casar, así que el estado sólo puede ser «sin
   *  casar» (quedan partidas pendientes) o «cuadrada» (no queda ninguna). Tampoco hay propuesta
   *  automática (`sug`) ni validación (`validado`), que son los otros dos datos que la pantalla
   *  esperaba y que la plataforma no tiene. */
  function partida(empresa, cod, i, mayor, cifras) {
    return Object.assign({
      id: empresa + '|' + cod + '#' + i,
      mayor: mayor,
      ext: null,
      estado: cifras.n_pendientes > 0 ? 'sin_casar' : 'cuadrada',
      sug: null,
      validado: null,
      conf: null,
      flash: false
    }, cifras);
  }

  /** Deja la pantalla sin cuentas: la opción del selector explica por qué. */
  function sinCuentas(ctx, motivo) {
    ctx.poner('CUENTAS', [{ cod: '', nombre: 'Sin datos: ' + motivo, tipo: 'vacia' }]);
    ctx.parchear({
      concCliente: ctx.empresa, concCuenta: '', concStatus: 'empty',
      concRows: [], concFilter: 'todas', concResumen: null
    });
  }

  /** El punteo y los totales del informe, tal cual, para los parches que los quieran enseñar. */
  function resumen(d) {
    var t = d.totales || {};
    var p = d.punteo || {};
    return {
      corte: d.fecha_referencia_es || '', fechaReferencia: numero(d.fecha_referencia),
      asientos: numero(t.n_asientos), lineas: numero(t.n_lineas), cuentas: numero(t.n_cuentas),
      debe: numero(t.debe), haber: numero(t.haber), descuadre: numero(t.descuadre), grupos: numero(t.n_grupos),
      partidas: numero(p.n_total), pendientes: numero(p.n_pendientes), punteadas: numero(p.n_punteadas),
      marcaCuenta: numero(p.n_marca_cuenta), marcaBancaria: numero(p.n_marca_bancaria),
      pctPendientes: numero(p.pct_pendientes), importePendiente: numero(p.importe_pendiente),
      importePendienteAbs: numero(p.importe_pendiente_abs), importePunteado: numero(p.importe_punteado),
      antiguas: numero(p.n_antiguas), importeAntiguo: numero(p.importe_antiguo),
      diasAntiguedad: numero(p.dias_antiguedad),
      cuentasPendientes: numero(d.n_cuentas_pendientes),
      cuentasMostradas: (d.cuentas || []).length, tercerosMostrados: (d.terceros || []).length,
      hallazgos: numero(d.n_hallazgos), importeAnomalias: numero(d.importe_anomalias),
      hallazgosRecuento: d.hallazgos_recuento || {}, listaHallazgos: d.hallazgos || [],
      tramos: d.tramos_antiguedad || [],
      avisos: d.avisos || []
    };
  }

  /* ── Apoyo ───────────────────────────────────────────────────────────────────────────────── */

  /** La ventana del navegador (o el objeto global, si algún día se carga fuera de uno). */
  function raiz() {
    if (typeof window !== 'undefined') return window;
    if (typeof globalThis !== 'undefined') return globalThis;
    return this;
  }

  /** El informe de un módulo. La API espera los parámetros en la clave `params`; `ctx.informe` los
   *  manda en `parametros` y la plataforma responde 422 («Extra inputs are not permitted»), así que
   *  aquí se usa el cliente HTTP directamente. Cuando datos.js mande la clave que la API espera,
   *  esto se puede sustituir por `ctx.informe(modulo, parametros)`. */
  function informeConParametros(ctx, modulo, parametros) {
    if (!parametros) return ctx.informe(modulo);
    return ctx.api.informe({
      modulo: modulo, cod_empresa: ctx.empresa, year: ctx.anio, params: parametros
    }).then(function (respuesta) { return (respuesta && respuesta.data) || {}; });
  }

  /** Un número de la API, sin sorpresas: lo que no sea número cuenta como 0. */
  function numero(valor) {
    var x = Number(valor);
    return isFinite(x) ? x : 0;
  }

  /** Un importe con el formato de aquí, sólo para los textos de `ctx.sinDatos`. */
  function euros(valor) {
    try {
      return new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR' }).format(numero(valor));
    } catch (fallo) {
      return numero(valor).toFixed(2) + ' EUR';
    }
  }
})();
