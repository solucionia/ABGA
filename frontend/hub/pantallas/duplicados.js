/* Duplicados de facturas · datos reales de la plataforma
 *
 * Lo que la pantalla esperaba: una bandeja de parejas escrita a mano (DUPS) con el NIF del
 * proveedor, el número de factura, la base imponible, el IVA y un registro del tipo «Registrada
 * por IA · 05/09/2026», con un porcentaje de similitud que ponía la IA.
 *
 * Lo que la plataforma tiene: el informe del módulo `duplicados`, que es INTERNO de ABGA. Da pares
 * de asientos con los criterios que han coincidido, la puntuación del módulo (11, 12...), su nivel
 * (PROBABLE / POSIBLE / REVISAR) con la gravedad (ALTA / MEDIA / BAJA) y el importe en riesgo.
 *
 * La traducción lleva cada par de asientos a la forma que la pantalla ya sabía pintar. Lo que la
 * plataforma no da —NIF, número de factura, base e IVA, quién lo registró, el escaneo de la
 * factura— se deja vacío y se declara con `ctx.sinDatos`, nunca se rellena con cifras inventadas.
 *
 * El módulo es interno: con un usuario de cliente no se puede pedir el informe, así que la pantalla
 * se queda vacía y lo dice. Y si el ejercicio no está leído del ERP, no se piden informes: se
 * ofrece traerlo (leer un ejercicio son cientos de consultas al ERP de ABGA).
 *
 * Módulo: `duplicados` (interno) → POST /api/informe
 */
(function () {
  'use strict';

  /* El informe se recorta a `max_filas` filas. Se piden más de las que trae por defecto (60) para
     que la bandeja y su contador sean los del informe y no una parte suya. */
  var MAX_FILAS = 200;

  ABGA.registrar('duplicados', async function (ctx) {
    var empresa = ctx.empresa;
    var anio = ctx.anio;

    /* ── Lo que la pantalla no puede pedir ─────────────────────────────────────────────────── */

    // Sin usuario interno no hay informe: el módulo es del panel de ABGA. No se llama a la API y no
    // se ofrece traer nada del ERP: no es que falten datos, es que esta pantalla no es del cliente.
    if (!ctx.estado.interno) {
      vaciar(ctx);
      ctx.sinDatos('los duplicados de facturas (el módulo es interno de ABGA: con este usuario la plataforma no lo calcula)');
      return;
    }

    // Pedir un ejercicio frío son cientos de consultas al ERP: eso lo decide una persona.
    if (!ctx.hayCache()) {
      vaciar(ctx);
      ctx.sinDatos('los duplicados del ejercicio ' + anio + ' (no está leído del ERP)');
      ctx.pedirDelErp('El ejercicio ' + anio + ' no está leído todavía.');
      return;
    }

    var d;
    try {
      d = await informeConParametros(ctx, 'duplicados', { max_filas: MAX_FILAS });
    } catch (fallo) {
      vaciar(ctx);
      ctx.sinDatos('los duplicados: ' + (fallo.message || fallo));
      return;
    }

    /* ── Cada par de asientos, con la forma de la bandeja ──────────────────────────────────── */

    var parejas = (d.duplicados || []).map(function (p, i) {
      var a = p.a || {};
      var b = p.b || {};
      return {
        id: 'D' + (i + 1),
        cli: empresa,                                // el hub llama «cliente» a la empresa
        proveedor: tercero(p),                       // «Proveedor 4003302362», del propio informe
        nif: '',                                     // la API no trae el NIF: ver `ctx.sinDatos`
        score: numero(p.puntuacion),                 // puntos del módulo, no un porcentaje
        motivo: (p.coincidencias || []).join(' · '),
        coinciden: criteriosDePantalla(p.criterios, a, b),   // para marcar los campos
        criterios: p.criterios || [],                        // los criterios del módulo, tal cual
        a: lado(a),
        b: lado(b),
        estado: 'pendiente',                         // la revisión (sí / no duplicada) es del hub
        nivel: p.nivel || '',
        gravedad: p.gravedad || '',
        importe: numero(p.importeRiesgo),
        // Lo que la pantalla todavía no pinta, pero que sí es real (para los parches del .md).
        documentos: (a.documento || '') + ' / ' + (b.documento || ''),
        par: p.par || []
      };
    });

    ctx.poner('DUPS', parejas);
    ctx.parchear({
      dups: parejas.map(function (x) { return Object.assign({}, x); }),
      dupTab: 'pendiente',
      dupSelId: parejas.length ? parejas[0].id : null,
      dupLeaving: null,
      modal: null,
      // Todo lo que el informe sabe y la pantalla aún no pinta: sirve para los parches propuestos
      // (contador real de pares, importe en riesgo del informe, avisos del módulo).
      dupsResumen: resumen(d),
      // La puntuación del módulo es de 8 puntos en adelante (gravedad ALTA) y llega a 14: los pesos
      // son importe 3 + cuentas 2 + misma fecha 3 + proveedor 2 + cliente 2 + descripción idéntica
      // 2. Se deja aquí porque la pantalla lo pinta como si fuese un porcentaje (ver el .md).
      dupsEscala: { umbral: numero(d.umbral), alta: 8, max: 14 }
    });

    /* ── Lo que la plataforma no da en esta pantalla ───────────────────────────────────────── */

    ctx.sinDatos('el NIF del proveedor y del cliente (el informe de duplicados no lo trae)');
    ctx.sinDatos('el número de factura: el informe identifica asientos y documentos contables, no facturas');
    ctx.sinDatos('la base imponible y el IVA de cada factura: el informe da el importe del asiento');
    ctx.sinDatos('quién y cuándo se registró cada asiento («Registrada por IA · fecha»)');
    ctx.sinDatos('el escaneo de las facturas: el modal «Ver original» no tiene documento que enseñar');
    ctx.sinDatos('el análisis continuo («La IA seguirá analizando las facturas nuevas cada hora»): el informe se calcula cuando se pide');
    if (parejas.length < numero(d.totalDuplicados)) {
      ctx.sinDatos('los ' + (numero(d.totalDuplicados) - parejas.length) + ' pares que el informe no ha devuelto (venían ' + parejas.length + ' de ' + numero(d.totalDuplicados) + ')');
    }
  });

  /* ── Traducción de un par de asientos ────────────────────────────────────────────────────── */

  /** Deja la pantalla vacía: ni bandeja ni pareja seleccionada. */
  function vaciar(ctx) {
    ctx.poner('DUPS', []);
    ctx.parchear({ dups: [], dupTab: 'pendiente', dupSelId: null, dupLeaving: null, modal: null,
                   dupsResumen: null, dupsEscala: null });
  }

  /** Las claves que la pantalla busca en `coinciden` son las de sus filas de comparación: nif, num,
   *  fecha, importe y concepto. El módulo devuelve las suyas: importe, cuentas, fecha,
   *  fecha_proxima, descripcion, descripcion_similar, proveedor y cliente. Se traducen las que
   *  tienen fila; `cuentas`, `proveedor` y `cliente` no tienen ninguna y se quedan en el motivo,
   *  que es la frase completa del informe. */
  function criteriosDePantalla(criterios, a, b) {
    var salida = [];
    (criterios || []).forEach(function (c) {
      if (c === 'importe') salida.push('importe');
      else if (c === 'fecha' || c === 'fecha_proxima') salida.push('fecha');
      else if (c === 'descripcion' || c === 'descripcion_similar') salida.push('concepto');
    });
    // El documento del asiento sí se puede comparar; el número de factura no existe en el informe.
    if (a.documento && a.documento === b.documento) salida.push('num');
    return salida.filter(function (x, i) { return salida.indexOf(x) === i; });
  }

  /** Un lado de la pareja: el asiento. La pantalla pinta base + IVA = total, pero el informe sólo
   *  da el importe del asiento: se deja el IVA a 0 para que el total que se pinta sea el importe
   *  real. */
  function lado(x) {
    return {
      num: x.documento || x.id || '',
      fecha: x.fechaTexto || '',
      base: numero(x.importe),
      iva: 0,
      concepto: x.descripcion || '',
      asiento: x.id || '',
      reg: ''                     // la plataforma no guarda quién ni cuándo se registró
    };
  }

  /** El informe no da el nombre del proveedor o del cliente aparte: lo da dentro del detalle de las
   *  coincidencias («Mismo proveedor: 4003302362»). Se usa eso como titular de la pareja; si el par
   *  no comparte tercero, se titula con los dos asientos, que es lo que sí se sabe. */
  function tercero(p) {
    var hallado = '';
    (p.coincidencias || []).forEach(function (texto) {
      if (hallado) return;
      if (texto.indexOf('Mismo proveedor:') === 0) hallado = 'Proveedor ' + texto.slice(17).trim();
      else if (texto.indexOf('Mismo cliente:') === 0) hallado = 'Cliente ' + texto.slice(15).trim();
    });
    if (hallado) return hallado;
    var a = p.a || {};
    var b = p.b || {};
    return 'Asientos ' + (a.id || '?') + ' y ' + (b.id || '?');
  }

  /** Las cifras del informe, tal cual, para los parches que las quieran enseñar. */
  function resumen(d) {
    var porNivel = d.porNivel || {};
    return {
      empresa: d.empresa || '',
      total: numero(d.totalDuplicados),
      probable: numero(porNivel.PROBABLE), posible: numero(porNivel.POSIBLE), revisar: numero(porNivel.REVISAR),
      nivelGlobal: d.nivelGlobal || '',
      importeRiesgoTotal: numero(d.importeRiesgoTotal),
      importeRiesgoUnico: numero(d.importeRiesgoUnico),
      asientosImplicados: numero(d.asientosImplicados),
      importeMaximo: numero(d.importeMaximo),
      asientos: numero(d.totalAsientos), analizados: numero(d.asientosAnalizados),
      excluidos: numero(d.asientosExcluidos), lineas: numero(d.lineasAnalizadas),
      paresComparados: numero(d.paresComparados), paresPosibles: numero(d.paresPosiblesFuerzaBruta),
      ahorro: numero(d.ahorroComparacionesPct),
      umbral: numero(d.umbral), importeMinimo: numero(d.importeMinimo),
      diasProximidad: numero(d.diasProximidad), maxFilas: numero(d.maxFilas),
      porCriterio: d.porCriterio || {},
      avisos: d.avisos || []
    };
  }

  /* ── Apoyo ───────────────────────────────────────────────────────────────────────────────── */

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
})();
