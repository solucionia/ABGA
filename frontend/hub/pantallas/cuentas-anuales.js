/* Cuentas anuales · memoria de la plataforma (módulo `memoria`)
 *
 * La pantalla «Cuentas anuales» del hub era un asistente de cinco pasos con todo escrito a mano:
 * un balance de una empresa inventada, doce notas redactadas de ejemplo con un porcentaje de
 * «confianza de la IA», seis cambios propuestos por la IA respecto a la memoria de 2024, una
 * aprobación firmada con nombre y fecha y un historial de versiones. Nada de eso lo calcula la
 * plataforma.
 *
 * Lo que sí existe es el módulo `memoria` (POST /api/informe con `modulo: 'memoria'`): calcula la
 * memoria de cuentas anuales de verdad, con las cifras del ejercicio tomadas de los apuntes, las
 * diez notas del PGC de PYMES ya redactadas dentro del documento HTML y las comprobaciones de
 * integridad. Eso es lo que alimenta esta pantalla:
 *
 *   CA_DATOS   los datos de partida: lo que el módulo ha leído y lo que no consta en el ERP
 *   CA_BAL     balance y cuenta de resultados; la columna del año anterior sólo se rellena si los
 *              apuntes de ese año están leídos (el módulo no estima la columna que falta)
 *   CA_NOTAS   las notas del PGC, recortadas del propio documento por sus encabezados
 *   CA_CAMBIOS el paso «Revisión» no tiene respaldo: la plataforma no compara con la memoria
 *              anterior ni propone cambios de texto, así que la lista queda vacía y declarada
 *
 * Lo que la plataforma no hace —confianza por nota, circuito de aprobación y firma, versionado,
 * exportación a Word/PDF desde el servidor, paquete del Registro— no se rellena con ejemplos: se
 * declara con `ctx.sinDatos` y los parches de texto están en `cuentas-anuales.md`.
 *
 * Datos que sí se mandan al módulo: la localidad, del catálogo de empresas del hub (el módulo
 * usaría «Madrid» por defecto). El resto de parámetros del informe (administrador, fecha de
 * formulación y las notas 9 y 10) son texto del asesor que la plataforma no tiene: se declaran y
 * el módulo deja el aviso correspondiente en el documento.
 */
(function () {
  'use strict';

  /* ── Formato y lectura del documento ─────────────────────────────────────────────────────── */

  /** Importe en euros, como el resto del hub (locale es-ES). */
  function euros(v) {
    var n = Number(v);
    if (!isFinite(n)) n = 0;
    return n.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
  }

  /** Entero con separador de millares (para contar líneas). */
  function miles(v) {
    return Number(v || 0).toLocaleString('es-ES');
  }

  /** Deshace las entidades que usa el maquetador al redactar el documento. */
  function desEscapar(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&#39;/g, "'")
      .replace(/&nbsp;/g, ' ');
  }

  /** Texto plano de un trozo del documento: fuera las tablas (sus cifras se leen en el informe),
   *  fuera las etiquetas, fuera las entidades. Es un aplanado legible del HTML, no el HTML. */
  function aTexto(trozo) {
    var sinTablas = String(trozo || '').replace(/<table[\s\S]*?<\/table>/gi, ' ');
    var sinEtiquetas = sinTablas.replace(/<[^>]*>/g, ' ');
    return desEscapar(sinEtiquetas).replace(/<[^<>]*$/g, ' ').replace(/\s+/g, ' ').trim();
  }

  /** Las notas del PGC tal y como las redacta el módulo dentro del documento: se recortan por sus
   *  encabezados («Nota N · Título»). «Avisos y limitaciones del cálculo» cierra la última. */
  function notasDelDocumento(html) {
    var documento = String(html || '');
    var corte = /Nota (\d+) · ([^<]+)<\/div>|Avisos y limitaciones del cálculo<\/div>/g;
    var marcas = [];
    var coincidencia;
    while ((coincidencia = corte.exec(documento)) !== null) {
      marcas.push({
        n: coincidencia[1] ? Number(coincidencia[1]) : null,
        t: coincidencia[2] ? coincidencia[2].replace(/\s+/g, ' ').trim() : '',
        desde: corte.lastIndex
      });
    }
    var notas = [];
    for (var i = 0; i < marcas.length; i++) {
      if (marcas[i].n === null) break;
      var hasta = (i + 1 < marcas.length) ? marcas[i + 1].desde : documento.length;
      var trozo = documento.slice(marcas[i].desde, hasta);
      var aperturaSiguiente = trozo.lastIndexOf('<div');
      if (aperturaSiguiente > 0) trozo = trozo.slice(0, aperturaSiguiente);
      notas.push({ n: marcas[i].n, t: marcas[i].t, txt: aTexto(trozo) });
    }
    return notas;
  }

  /* ── Descarga real (la usan los botones del paso «Exportar») ─────────────────────────────── */

  /** Lo único que la plataforma exporta de este informe: sus tablas, en CSV (o ZIP si hay varias
   *  hojas). El PDF lo hace el navegador al imprimir y el paquete del Registro no existe.
   *  Se expone aquí para que los botones del hub la llamen (ver `cuentas-anuales.md`). */
  window.ABGA_CA = {
    exportar: async function () {
      var estado = ABGA.estado || {};
      var blob = await ABGA.api.exportar({
        modulo: 'memoria', cod_empresa: estado.empresa, year: Number(estado.ejercicio)
      });
      var esZip = String(blob.type || '').indexOf('zip') >= 0;
      var nombre = 'memoria_' + estado.empresa + '_' + estado.ejercicio + (esZip ? '.zip' : '.csv');
      var url = URL.createObjectURL(blob);
      var enlace = document.createElement('a');
      enlace.href = url;
      enlace.download = nombre;
      document.body.appendChild(enlace);
      enlace.click();
      enlace.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      return nombre;
    }
  };

  /* ── Traductor de la pantalla ────────────────────────────────────────────────────────────── */

  ABGA.registrar('memoria', async function (ctx) {
    var empresa = ctx.empresa;
    var anio = ctx.anio;

    // La memoria son las cifras del ejercicio: sin el ejercicio leído del ERP no se pide ningún
    // informe. Leerlo son cientos de consultas al ERP de ABGA y eso lo decide una persona.
    if (!ctx.hayCache()) {
      ctx.poner('CA_DATOS', []);
      ctx.poner('CA_BAL', []);
      ctx.poner('CA_NOTAS', []);
      ctx.poner('CA_CAMBIOS', []);
      ctx.parchear({ caNota: 0, caCambios: {}, caChecksDatos: [], caAvisos: [] });
      ctx.sinDatos('la memoria del ejercicio ' + anio + ': el ejercicio no está leído del ERP');
      ctx.pedirDelErp('El ejercicio ' + anio + ' no está leído todavía.');
      return;
    }

    // La localidad (domicilio social) la conoce el catálogo de empresas del hub; el módulo usaría
    // «Madrid» por defecto, que no es un dato del ERP. El administrador, la fecha de formulación y
    // las notas 9 y 10 son texto del asesor: no se inventan, se declaran más abajo.
    var cliente = (ctx.MOCK.CLIENTES || []).filter(function (c) { return c.id === empresa; })[0] || {};

    var respuesta;
    try {
      respuesta = await ctx.api.informe({
        modulo: 'memoria', cod_empresa: empresa, year: anio,
        parametros: cliente.ciudad ? { localidad: cliente.ciudad } : undefined
      });
    } catch (fallo) {
      ctx.poner('CA_DATOS', []);
      ctx.poner('CA_BAL', []);
      ctx.poner('CA_NOTAS', []);
      ctx.poner('CA_CAMBIOS', []);
      ctx.parchear({ caNota: 0, caCambios: {}, caChecksDatos: [], caAvisos: [] });
      ctx.sinDatos('la memoria (' + anio + '): ' + (fallo.message || fallo));
      return;
    }

    var d = respuesta.data || {};
    var meta = respuesta.meta || {};
    var integridad = d.integridad || {};
    var cuadre = integridad.cuadre || {};
    var contrarios = integridad.saldosContrarios || [];
    var gruposVacios = integridad.gruposSinMovimiento || [];
    var cuadra = Math.abs(Number(cuadre.descuadre || 0)) <= 1;
    var hayAnterior = Number(d.nLineasAnterior || 0) > 0;

    /* ── Paso 1 · Datos de partida: lo que el módulo ha leído y lo que no consta ───────────── */

    ctx.poner('CA_DATOS', [
      {
        t: 'Balance de sumas y saldos a 31/12/' + anio,
        det: miles(d.nLineas) + ' líneas · ' +
             (cuadra ? 'cuadra: ΣDebe = ΣHaber' : 'descuadre de ' + euros(cuadre.descuadre)),
        ok: cuadra
      },
      {
        t: 'Cuenta de pérdidas y ganancias ' + anio,
        det: 'Resultado del ejercicio según los apuntes: ' + euros(d.resultadoNeto), ok: true
      },
      {
        t: 'Inventario de inmovilizado y amortizaciones',
        det: 'Valor según los apuntes: ' + euros(d.totalInmovilizado) + (Number(d.amortizacionAcumulada) > 0
          ? ' · amortización acumulada ' + euros(d.amortizacionAcumulada)
          : ' · sin cuentas de amortización acumulada (28x) en los apuntes'),
        ok: Number(d.amortizacionAcumulada) > 0
      },
      {
        t: 'Detalle de deudas',
        det: 'Pasivo exigible: ' + euros(d.exigible) +
             ' · el reparto por año de vencimiento no consta en los apuntes',
        ok: false
      },
      {
        t: 'Apuntes del ejercicio ' + (anio - 1) + ' (comparativa)',
        det: hayAnterior ? miles(d.nLineasAnterior) + ' líneas del ejercicio anterior'
                         : 'no leídos: la comparativa con el ejercicio anterior sale en blanco',
        ok: hayAnterior
      },
      {
        t: 'Plantilla media por categoría y sexo',
        det: 'no consta en los apuntes del ERP: la aporta el asesor en la Nota 10', ok: false
      }
    ]);

    /* ── Paso 1 · Balance y cuenta de resultados (sólo las cifras que devuelve el módulo) ───── */

    // El año anterior sólo se rellena con las magnitudes que el módulo devuelve del ejercicio
    // anterior; las que no calcula van a nulo (la pantalla muestra «—», ver el parche del .md).
    function delAnterior(v) {
      return hayAnterior && v !== undefined && v !== null ? Number(v) : null;
    }
    ctx.poner('CA_BAL', [
      ['Activo no corriente', Number(d.activoNoCorriente || 0), null, false],
      ['Activo corriente', Number(d.activoCorriente || 0), null, false],
      ['Total activo', Number(d.totalActivo || 0), delAnterior(d.totalActivoAnt), true],
      ['Patrimonio neto', Number(d.patrimonioNeto || 0), delAnterior(d.patrimonioNetoAnt), false],
      ['Pasivo no corriente', Number(d.deudasLP || 0), null, false],
      ['Pasivo corriente', Number(d.pasivoCorriente || 0), delAnterior(d.pasivoCorrienteAnt), false],
      ['Cifra de negocios', Number(d.ventas || 0), delAnterior(d.ventasAnt), false],
      ['Resultado de explotación', Number(d.ebit || 0), delAnterior(d.ebitAnt), false],
      ['Resultado del ejercicio', Number(d.resultadoNeto || 0), delAnterior(d.resultadoNetoAnt), true]
    ]);

    /* ── Paso 2 · Borrador: las notas que el módulo ha redactado dentro del documento ───────── */

    // Las notas no vienen como lista en `data`: van redactadas dentro del HTML del informe, así que
    // se recortan de ahí. No hay puntuación de «confianza»: el módulo no la calcula.
    var notas = notasDelDocumento(respuesta.html);

    ctx.poner('CA_NOTAS', notas);
    if (!notas.length) {
      ctx.sinDatos('las notas del PGC: no se han podido recortar del documento generado');
    }

    /* ── Paso 3 · Revisión: la plataforma no propone cambios ni compara con la memoria anterior ─ */

    ctx.poner('CA_CAMBIOS', []);
    ctx.parchear({ caNota: 0, caCambios: {} });

    /* ── Paso 4 · Comprobaciones: las de integridad que sí calcula el módulo ─────────────────── */

    var cuadraBalance = Math.abs(Number(d.totalActivo || 0) -
      (Number(d.patrimonioNeto || 0) + Number(d.exigible || 0))) <= 1;
    ctx.parchear({
      // Los avisos del módulo: lo que no se puede sacar de los apuntes y queda declarado en el
      // propio documento (Nota 10 pendiente, cuadro de vencimientos, impuesto sin asiento...).
      caAvisos: d.avisos || [],
      caChecksDatos: [
        {
          t: 'El libro del ejercicio cuadra: ΣDebe = ΣHaber',
          det: euros(cuadre.debe) + ' en ' + miles(cuadre.n_lineas) + ' líneas', ok: cuadra
        },
        {
          t: 'Activo = patrimonio neto + pasivo exigible',
          det: euros(d.totalActivo), ok: cuadraBalance
        },
        {
          t: 'Notas del PGC de PYMES redactadas en el informe',
          det: notas.length + ' notas', ok: notas.length > 0
        },
        {
          t: 'Sin cuentas con el saldo al revés de su naturaleza',
          det: contrarios.length ? contrarios.length + ' cuentas por revisar' : 'ninguna',
          ok: contrarios.length === 0
        },
        {
          t: 'Sin grupos del balance sin movimientos',
          det: gruposVacios.length ? gruposVacios.join(', ') : 'ninguno',
          ok: gruposVacios.length === 0
        },
        {
          t: 'Apuntes del ejercicio y del anterior',
          det: hayAnterior ? 'los dos ejercicios leídos'
                           : 'falta el ejercicio ' + (anio - 1) + ': la comparativa sale en blanco',
          ok: hayAnterior
        }
      ]
    });

    /* ── Lo que la plataforma no hace (se declara, no se rellena) ────────────────────────────── */

    ctx.sinDatos('la confianza por nota: el módulo redacta las notas con los apuntes, no las puntúa');
    ctx.sinDatos('los cambios de texto respecto a la memoria del ejercicio anterior (paso «Revisión»): ' +
                 'la plataforma no guarda ni compara memorias anteriores');
    ctx.sinDatos('el circuito de aprobación y la firma del responsable (paso «Aprobación»): ' +
                 'la plataforma no lo tiene');
    ctx.sinDatos('el historial de versiones de la memoria');
    ctx.sinDatos('la exportación a Word y a PDF desde el servidor: la plataforma exporta las tablas ' +
                 'del informe en CSV o ZIP, y el PDF lo hace el navegador al imprimir');
    ctx.sinDatos('el paquete de depósito en el Registro Mercantil y su huella digital');
    ctx.sinDatos('la plantilla media, los hechos posteriores al cierre y el texto de las notas 9 y 10: ' +
                 'son texto del asesor y no se deducen de los apuntes');
    ctx.sinDatos('la fecha de formulación y el administrador: no están en la plataforma ' +
                 '(el módulo usa el 31 de marzo y «pendiente de indicar»)');
    if (!cliente.ciudad) {
      ctx.sinDatos('el domicilio social (localidad): el catálogo de empresas no lo trae');
    }
    if (meta.desde_cache === false) {
      ctx.sinDatos('el ejercicio se ha leído del ERP en esta petición (' +
                   meta.segundos + ' s): puede tardar');
    }
  });
})();
