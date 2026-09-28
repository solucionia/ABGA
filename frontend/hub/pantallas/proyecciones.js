/* Proyecciones · datos reales de la plataforma
 *
 * La pantalla llegó calculando sus propias cifras: unas temporadas fijas (`SEAS_RAW`), un ruido
 * mensual inventado (`NOISE`), tres escenarios escritos a mano con sus porcentajes (`ESC`), cinco
 * supuestos editables con rangos (`PARAMS`) y unas funciones `projBase`/`realMonths`/`project`/`pyg`
 * que extrapolaban ventas y gastos desde una cifra base. Nada de eso sale de la contabilidad del
 * cliente: son cifras del frontal.
 *
 * Ahora los números los pone el módulo `proyecciones` de la plataforma, que es determinista:
 *
 *   · regresión lineal ponderada POR MAGNITUD sobre los ejercicios con apuntes cargados
 *     (`tendencias`: proyección, pendiente, intercepto, R², nº de ejercicios, tendencia, tasa);
 *   · escenarios conservador / base / optimista como factores declarados sobre la proyección base
 *     (`escenarios`: factorIngresos, factorGastos, variacionResultado), no como porcentajes sueltos;
 *   · PyG del ejercicio proyectado (`proyeccionBase`) y magnitudes del ejercicio cargado
 *     (`magnitudesActual`) y de los anteriores (`historico`);
 *   · reparto mensual del ejercicio proyectado con la estacionalidad REAL de los ejercicios
 *     completos (`mesMensualProyectado` + `factorEstacionalIngresos`), no con temporadas fijas;
 *   · el ejercicio en curso mes a mes (`mesEnCurso`, con `mesCorte`/`esParcial` y el flag
 *     `proyectado` en los meses que la propia plataforma estima);
 *   · su lectura del resultado (`alertas`, `avisos`, `nivelGlobal`, `hayTesoreria`).
 *
 * La proyección de la plataforma es POR EJERCICIO: proyecta el siguiente al cargado
 * (`yearProyectado`). El gráfico del hub enseña meses porque el módulo reparte ese mismo ejercicio
 * anual con los pesos estacionales reales: es la proyección de la plataforma abierta en meses, no
 * un modelo nuevo del frontal. Lo mismo con la banda: los meses del escenario conservador y del
 * optimista son la cifra anual de ese escenario repartida con los pesos que devuelve el módulo.
 *
 * Lo que la plataforma no proyecta —tres ejercicios vista, simulación partida a partida, la
 * probabilidad de un escenario, guardar escenarios— no se rellena: se declara con `ctx.sinDatos`.
 *
 * Los parámetros del informe (tipo del IS, factores de escenario, mes de corte) se dejan en los
 * valores por defecto del módulo: el frontal no inventa what-ifs propios.
 */
ABGA.registrar('proyecciones', async function (ctx) {
  var anio = ctx.anio;

  /* ── Sin el ejercicio leído no se pide nada ─────────────────────────────────────────────────
     Leer un ejercicio del ERP son cientos de consultas al ERP del cliente: lo decide una persona.
     Igual que en Inicio, la pantalla se queda vacía y se ofrece traerlo. */

  if (!ctx.hayCache()) {
    ctx.parchear({ proyDatos: null });
    ctx.sinDatos('el ejercicio ' + anio + ' no está leído del ERP');
    ctx.pedirDelErp('El ejercicio ' + anio + ' no está leído todavía.');
    return;
  }

  /* ── El informe ────────────────────────────────────────────────────────────────────────────
     `ctx.informe('proyecciones')` devuelve la `data` del módulo. Sin parámetros: los del módulo. */

  var datos = null;
  try {
    datos = await ctx.informe('proyecciones');
  } catch (fallo) {
    ctx.parchear({ proyDatos: null });
    ctx.sinDatos('proyecciones: ' + ((fallo && fallo.message) || fallo));
    return;
  }

  if (!datos || !datos.disponible) {
    ctx.parchear({ proyDatos: null });
    var porque = (datos && datos.avisos && datos.avisos.length)
      ? datos.avisos[0] : 'no hay apuntes cargados con los que calcularla';
    ctx.sinDatos('proyecciones: ' + porque);
    return;
  }

  /* ── Formato (sólo presentación; ningún número se calcula aquí) ───────────────────────────── */

  var numFmt = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  var milFmt = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 });
  var unoFmt = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  var dosFmt = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2 });

  function hay(v) { return typeof v === 'number' && isFinite(v); }
  function euros(v) { return hay(v) ? numFmt.format(v) + ' €' : '—'; }
  function miles(v) {
    if (!hay(v)) return '—';
    if (Math.abs(v) >= 1e6) return milFmt.format(v / 1e6) + ' M€';
    return numFmt.format(Math.round(v / 1000)) + ' k€';
  }
  function signo(v, dec) {
    if (!hay(v)) return '—';
    return (v >= 0 ? '+' : '−') + (dec === 1 ? unoFmt : dosFmt).format(Math.abs(v)) + ' %';
  }
  function tanto(v) { return hay(v) ? dosFmt.format(v) + ' %' : '—'; }

  /* ── 1. Serie mensual del gráfico ───────────────────────────────────────────────────────────
     Dos tramos, tal y como los da el módulo:
       · `mesEnCurso`  → los 12 meses del ejercicio cargado; los meses hasta `mesCorte` son reales
                         y los posteriores vienen ya estimados por la plataforma (`proyectado`).
       · `mesMensualProyectado` → los 12 meses del ejercicio proyectado, repartidos con la
                         estacionalidad real (`pesoIngresos`/`pesoGastos`).
     El EBITDA de cada mes sale de dos magnitudes del módulo (ingresos − gastos de explotación); es
     su misma definición de EBITDA, no una estimación nueva. */

  var meses = [];
  var mesEnCurso = datos.mesEnCurso || [];
  var mesProyectado = datos.mesMensualProyectado || [];
  var corte = hay(datos.mesCorte) ? datos.mesCorte : 12;
  var i, fila;

  for (i = 0; i < mesEnCurso.length; i++) {
    fila = mesEnCurso[i];
    meses.push({
      label: fila.mes + ' ' + String(datos.year).slice(2),
      anio: datos.year, mes: fila.mes_num,
      v: hay(fila.ingresos) ? fila.ingresos : null,
      ebitda: hay(fila.ingresos) && hay(fila.gastos) ? fila.ingresos - fila.gastos : null,
      real: !fila.proyectado, tipo: fila.proyectado ? 'cierre' : 'real'
    });
  }
  var nReal = 0;
  for (i = 0; i < meses.length; i++) if (meses[i].real) nReal++;

  for (i = 0; i < mesProyectado.length; i++) {
    fila = mesProyectado[i];
    meses.push({
      label: fila.mes + ' ' + String(datos.yearProyectado).slice(2),
      anio: datos.yearProyectado, mes: fila.mes_num,
      v: hay(fila.ingresos) ? fila.ingresos : null,
      ebitda: hay(fila.ingresos) && hay(fila.gastos) ? fila.ingresos - fila.gastos : null,
      real: false, tipo: 'proyeccion'
    });
  }

  /* Banda del rango conservador-optimista, mes a mes: la cifra anual de cada escenario repartida
     con los pesos de ingresos que devuelve el módulo (los mismos del escenario base). */
  var esc = datos.escenarios || {};
  var ingConservador = esc.conservador ? esc.conservador.ingresos : null;
  var ingOptimista = esc.optimista ? esc.optimista.ingresos : null;
  var banda = [];
  for (i = 0; i < meses.length; i++) {
    banda.push({ lo: meses[i].v, hi: meses[i].v });
  }
  for (i = 0; i < mesProyectado.length; i++) {
    var peso = hay(mesProyectado[i].pesoIngresos) ? mesProyectado[i].pesoIngresos / 100 : null;
    var k = mesEnCurso.length + i;
    if (peso === null || !banda[k]) continue;
    banda[k] = {
      lo: hay(ingConservador) ? ingConservador * peso : null,
      hi: hay(ingOptimista) ? ingOptimista * peso : null
    };
  }

  /* ── 2. Indicadores del ejercicio proyectado ────────────────────────────────────────────────
     Todo de `proyeccionBase` (escenario base) y de `magnitudesActual` (el ejercicio cargado). Las
     variaciones las calcula el propio módulo (`varIngresos`, `varResultado`, `varEbitda`): no se
     recalculan aquí. */

  var baseProy = datos.proyeccionBase || {};
  var actual = datos.magnitudesActual || null;
  var margenActual = actual && hay(actual.margenEbitda) ? actual.margenEbitda : null;
  var margenNetoActual = actual && hay(actual.margenNeto) ? actual.margenNeto : null;
  if (!actual) ctx.sinDatos('las magnitudes del ejercicio ' + datos.year +
    ' (no hay apuntes de ese ejercicio entre los cargados)');

  var kpis = [
    {
      label: 'Cifra de negocios · ' + datos.yearProyectado, value: euros(baseProy.ingresos),
      sub: signo(baseProy.varIngresos) + ' frente a ' + datos.year,
      fg: baseProy.varIngresos >= 0 ? 'var(--ok)' : 'var(--err)'
    },
    {
      label: 'EBITDA · ' + datos.yearProyectado, value: euros(baseProy.ebitda),
      sub: 'Margen ' + tanto(baseProy.margenEbitda) + ' · ' + datos.year + ': ' + tanto(margenActual),
      fg: hay(baseProy.margenEbitda) && hay(margenActual)
        ? (baseProy.margenEbitda >= margenActual ? 'var(--ok)' : 'var(--err)') : 'var(--muted)'
    },
    {
      label: 'Resultado neto · ' + datos.yearProyectado, value: euros(baseProy.resultado),
      sub: signo(baseProy.varResultado) + ' frente a ' + datos.year,
      fg: baseProy.varResultado >= 0 ? 'var(--ok)' : 'var(--err)'
    },
    {
      label: 'Margen neto · ' + datos.yearProyectado, value: tanto(baseProy.margenNeto),
      sub: datos.year + ': ' + tanto(margenNetoActual),
      fg: hay(baseProy.margenNeto) && hay(margenNetoActual)
        ? (baseProy.margenNeto >= margenNetoActual ? 'var(--ok)' : 'var(--err)') : 'var(--muted)'
    }
  ];

  /* ── 3. Escenarios ─────────────────────────────────────────────────────────────────────────
     Los tres escenarios de la plataforma. Su `nota` y su `supuestos` se redactan con los factores
     que el módulo declara (`factorIngresos`, `factorGastos`) y con su `variacionResultado`: no hay
     porcentaje de confianza que enseñar, así que no se enseña. */

  var NOMBRE = { conservador: 'Conservador', base: 'Base', optimista: 'Optimista' };
  var escenarios = [];
  var claves = ['conservador', 'base', 'optimista'];
  for (i = 0; i < claves.length; i++) {
    var clave = claves[i];
    var e = esc[clave];
    if (!e) continue;
    var fIng = e.factorIngresos, fGas = e.factorGastos;
    escenarios.push({
      clave: clave, l: NOMBRE[clave],
      nota: clave === 'base'
        ? 'Regresión ponderada de las magnitudes sobre los ejercicios cargados.'
        : 'Ingresos ' + (hay(fIng) ? '×' + dosFmt.format(fIng) : '—') +
          ' y gastos ' + (hay(fGas) ? '×' + dosFmt.format(fGas) : '—') + ' sobre el escenario base.',
      factores: hay(fIng) && hay(fGas)
        ? 'Ingresos ×' + dosFmt.format(fIng) + ' · Gastos ×' + dosFmt.format(fGas) : '—',
      v: miles(e.ingresos), neto: miles(e.resultado), mn: tanto(e.margenNeto),
      supuestos: 'Resultado frente al base: ' + miles(e.variacionResultado) +
        (hay(e.tesoreriaEstimada) ? ' · tesorería estimada ' + miles(e.tesoreriaEstimada) : '')
    });
  }

  /* ── 4. Cuadro de la PyG proyectada ─────────────────────────────────────────────────────────
     Una columna por ejercicio: los del histórico con apuntes y el proyectado. Las filas son las
     magnitudes del módulo; «Margen bruto» es la única fila derivada (ingresos − aprovisionamientos,
     su misma definición). El impuesto es el que aplica el módulo con su tipo, no un 25 % del frontal. */

  var PERIODO = [];
  var magnitud = [];
  (datos.historico || []).forEach(function (h) {
    if (h.sinDatos) return;
    PERIODO.push(String(h.year) + (h.year === datos.year
      ? (datos.esParcial ? ' (en curso, hasta ' + (mesEnCurso[corte - 1] ? mesEnCurso[corte - 1].mes : '—') + ')' : ' (real)')
      : ' (real)'));
    magnitud.push(h);
  });
  if (actual && !magnitud.some(function (m) { return m.year === actual.year; })) {
    PERIODO.push(String(actual.year) + ' (en curso)');
    magnitud.push(actual);
  }
  PERIODO.push(String(datos.yearProyectado) + ' (proyectado · base)');
  magnitud.push(baseProy);

  var FILAS = [
    ['Cifra de negocios', 'ingresos', false, 1],
    ['Aprovisionamientos', 'aprovisionamientos', false, -1],
    ['Margen bruto', 'margenBruto', true, 1],
    ['Gastos de personal', 'gastosPersonal', false, -1],
    ['Otros gastos de explotación', 'otrosGastos', false, -1],
    ['EBITDA', 'ebitda', true, 1],
    ['Amortización del inmovilizado', 'amortizaciones', false, -1],
    ['Ingresos financieros', 'ingresosFinancieros', false, 1],
    ['Gastos financieros', 'gastosFinancieros', false, -1],
    ['Resultado antes de impuestos', 'rai', true, 1],
    ['Impuesto sobre Sociedades (' + tanto(datos.tipoImpuesto) + ')', 'impuesto', false, -1],
    ['Resultado del ejercicio', 'resultado', true, 1]
  ];

  function valorDe(p, clave) {
    if (clave === 'margenBruto') {
      return hay(p.ingresos) && hay(p.aprovisionamientos) ? p.ingresos - p.aprovisionamientos : null;
    }
    return hay(p[clave]) ? p[clave] : null;
  }

  var filas = FILAS.map(function (f, n) {
    var etiqueta = f[0], clave = f[1], negrita = f[2], signoFila = f[3];
    var crudos = magnitud.map(function (p) { return valorDe(p, clave); });
    var real = crudos[crudos.length - 2];
    var proyectado = crudos[crudos.length - 1];
    var delta = hay(real) && real !== 0 && hay(proyectado)
      ? (proyectado / real - 1) * 100 * (signoFila >= 0 ? 1 : -1) : null;
    return {
      l: etiqueta,
      raw: crudos.map(function (v) { return hay(v) ? v : 0; }),
      cells: crudos.map(function (v, j) {
        return {
          v: euros(v), fg: hay(v) && v < 0 ? 'var(--err)' : 'var(--text)',
          w: negrita ? 600 : 400, bg: j === 0 ? 'var(--surface2)' : 'transparent'
        };
      }),
      fw: negrita ? 600 : 400, rowBg: negrita ? 'var(--accent-soft)' : 'transparent',
      delta: hay(delta) ? signo(delta) : '—',
      deltaFg: hay(delta) ? (delta >= 0 ? 'var(--ok)' : 'var(--err)') : 'var(--muted)',
      delay: (n * 25) + 'ms'
    };
  });

  /* ── 5. Cómo proyecta: las tendencias reales por magnitud y los parámetros del informe ──────
     Sustituye a los cinco supuestos editables del frontal. Aquí no hay nada que mover: se enseña
     el ajuste que ha hecho la plataforma (tendencia, R², nº de ejercicios, tasa). */

  var TEND = {
    ingresos: 'Cifra de negocios', aprovisionamientos: 'Aprovisionamientos',
    gastosPersonal: 'Gastos de personal', otrosGastos: 'Otros gastos de explotación',
    amortizaciones: 'Amortización del inmovilizado', ingresosFinancieros: 'Ingresos financieros',
    gastosFinancieros: 'Gastos financieros', tesoreria: 'Tesorería', deudores: 'Deudores',
    proveedores: 'Proveedores', resultado: 'Resultado del ejercicio', cashFlow: 'Flujo de caja'
  };
  var TONO_TEND = { CRECIENTE: 'var(--ok)', DECRECIENTE: 'var(--err)', ESTABLE: 'var(--muted)', 'SIN DATOS': 'var(--muted)' };
  var tendencias = datos.tendencias || {};
  var hasDotacion = false;
  (datos.historico || []).forEach(function (h) {
    if (!h.sinDatos && hay(h.amortizaciones) && h.amortizaciones !== 0) hasDotacion = true;
  });
  var supuestos = [];
  Object.keys(TEND).forEach(function (k) {
    var t = tendencias[k];
    if (!t) return;
    var etiqueta = t.tendencia === 'SIN DATOS' ? 'Sin datos' : t.tendencia.toLowerCase();
    var nota = hay(t.tasaCrecimiento) ? signo(t.tasaCrecimiento, 1) + '/año' : '—';
    var valor = miles(t.proyeccion);
    var sub = datos.yearProyectado + ' · ' + nota + ' · R² ' + (hay(t.r2) ? dosFmt.format(t.r2) : '—') +
      ' · ' + (t.n || 0) + ' ejercicio(s)' + (t.fiabilidad ? ' · fiabilidad ' + t.fiabilidad : '');
    // Dos ceros del módulo no son cifras: no hay cuentas de tesorería en el ERP y no hay
    // dotaciones a la amortización. Se dicen como son, no como «0 €».
    if (k === 'tesoreria' && !datos.hayTesoreria) {
      valor = '—';
      sub = 'sin cuentas 570-577 en el ERP: el módulo informa de la caja generada';
    }
    if (k === 'amortizaciones' && !hasDotacion) {
      valor = '—';
      sub = 'sin dotaciones (68x) contabilizadas: EBIT y EBITDA coinciden';
    }
    supuestos.push({
      k: k, l: TEND[k], val: valor, sub: sub,
      tendTxt: etiqueta + (t.nota ? ' · ' + t.nota : ''),
      tendFg: TONO_TEND[t.tendencia] || 'var(--muted)'
    });
  });

  var parametros = 'Parámetros del informe: tipo del IS ' + tanto(datos.tipoImpuesto) +
    ' · mes de corte ' + (mesEnCurso[corte - 1] ? mesEnCurso[corte - 1].mes + ' ' + String(datos.year).slice(2) : '—') +
    ' · escenarios de la plataforma (conservador ×' + (hay(ingConservador) && hay(baseProy.ingresos) && baseProy.ingresos ? dosFmt.format(ingConservador / baseProy.ingresos) : '—') +
    ').';

  /* ── 6. Lo que la plataforma dice de su propia proyección ─────────────────────────────────── */

  var TONO_ALERTA = {
    ALTA: { fg: 'var(--err)', bg: 'var(--err-soft)', bd: 'var(--err)' },
    MEDIA: { fg: 'var(--warn)', bg: 'var(--warn-soft)', bd: 'var(--warn)' },
    INFO: { fg: 'var(--muted)', bg: 'var(--surface2)', bd: 'var(--border)' }
  };
  var alertas = (datos.alertas || []).map(function (a) {
    var tono = TONO_ALERTA[a.nivel] || TONO_ALERTA.INFO;
    return { n: a.nivel === 'INFO' ? 'Nota' : (a.nivel === 'MEDIA' ? 'Aviso' : 'Alerta'),
             m: a.mensaje, fg: tono.fg, bg: tono.bg, bd: tono.bd };
  });

  /* ── 7. Lo que esta pantalla ya no calcula (y la plataforma no da) ──────────────────────────
     Se declara para que quede escrito: nada de esto se rellena con cifras del frontal. */

  ctx.sinDatos('el horizonte a 36 meses (la plataforma proyecta un único ejercicio: el siguiente al cargado)');
  ctx.sinDatos('los supuestos editables por partida (PARAMS): la plataforma ajusta una regresión ponderada y no simula crecimientos por partida');
  ctx.sinDatos('el porcentaje de confianza de cada escenario: el módulo publica los factores aplicados y la variación del resultado, no una probabilidad');
  ctx.sinDatos('guardar el escenario (la plataforma no guarda escenarios propios del despacho)');
  ctx.sinDatos('las temporadas fijas y el ruido del frontal (SEAS_RAW, NOISE): sustituidos por los factores estacionales reales del módulo');
  if (!datos.hayTesoreria) {
    ctx.sinDatos('el saldo de tesorería proyectado (el ERP no trae cuentas 570-577 en los ejercicios cargados: el módulo informa de la caja generada)');
  }

  /* ── 8. A la pantalla ────────────────────────────────────────────────────────────────────── */

  var corteLbl = mesEnCurso[corte - 1] ? mesEnCurso[corte - 1].mes + ' ' + String(datos.year).slice(2) : '—';
  var hasta = meses.length ? meses[meses.length - 1].label : '—';

  ctx.parchear({
    proyDatos: {
      listo: true,
      year: datos.year, yearProyectado: datos.yearProyectado,
      nivelGlobal: datos.nivelGlobal, tipoImpuesto: datos.tipoImpuesto,
      mesCorte: corte, esParcial: !!datos.esParcial, mesesProyectadosN: datos.mesesProyectadosN,
      hayTesoreria: !!datos.hayTesoreria,
      meses: meses, nReal: nReal, banda: banda,
      horizontes: [{ label: '12 meses', meses: 12 }, { label: '24 meses', meses: 24 }],
      kpis: kpis, escenarios: escenarios,
      cols: PERIODO, rows: filas,
      supuestos: supuestos,
      alertas: alertas,
      avisos: datos.avisos || [],
      fuente: 'Tendencias, escenarios y estacionalidad del módulo «proyecciones» de la plataforma · ' +
        (datos.aniosConDatos || []).length + ' ejercicio(s) con apuntes (' +
        (datos.aniosConDatos || []).join(', ') + ')',
      parametros: parametros,
      resumen: 'Cuenta de pérdidas y ganancias proyectada por la plataforma · real hasta ' + corteLbl +
        ' · proyección de ' + datos.yearProyectado,
      tablaNota: 'Un ejercicio por columna · importes en euros',
      hasta: hasta,
      corte: corteLbl
    }
  });
});
