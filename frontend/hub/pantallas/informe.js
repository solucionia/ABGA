/* Informe financiero · datos reales de la plataforma
 *
 * La pantalla «Informe financiero» del hub traía todas sus cifras escritas a mano dentro del propio
 * código de la aplicación. Este traductor las sustituye, en el mismo sitio y con la misma forma, por
 * lo que devuelve la plataforma.
 *
 * La pantalla se apoya en tres datos del hub: INF_PER (los periodos del selector), INF_PYG (la
 * cuenta de pérdidas y ganancias, dos ejercicios) e INF_BAL (el balance de situación, dos
 * ejercicios). Además usa CLIENTES (la empresa que se está viendo) y, para las gráficas, la
 * estacionalidad de ejemplo (SEAS/NOISE) y el saldo de tesorería de cierre.
 *
 * DE DÓNDE SALE CADA BLOQUE
 *
 *   INF_PER   del propio ejercicio. La plataforma informa por ejercicio completo, no por mes ni por
 *             trimestre, así que el selector ofrece un único periodo (el ejercicio en curso). Va
 *             con las series mensuales reales del ejercicio (ingresos/gastos y saldo de tesorería)
 *             para que las gráficas puedan usarlas en cuanto se aplique el parche correspondiente
 *             (ver pantallas/informe.md).
 *   INF_PYG   del módulo `autodespro` (el «Informe financiero» de la plataforma, REQ-03). Se toma
 *             `totalIng` (total de ingresos de explotación) como cifra de negocios, que es la base
 *             de los márgenes del propio informe de la plataforma. Los gastos van en negativo,
 *             como los espera la pantalla; el impuesto de sociedades (cuenta 630) en negativo y el
 *             resultado del ejercicio tal cual lo da la contabilidad.
 *   INF_BAL   del mismo módulo: activo no corriente, existencias, deudores (clientes + otros
 *             deudores), tesorería, pasivo no corriente y pasivo corriente, del ejercicio y del
 *             anterior. El patrimonio neto de partida se reconstruye como el de cierre menos el
 *             resultado del ejercicio, porque la plataforma no publica el saldo inicial del
 *             patrimonio.
 *
 * POR QUÉ `autodespro` Y NO `pyg`: el módulo `pyg` sólo trae del año anterior dos cifras (ingresos
 * y resultado) y no trae balance; `autodespro` trae las dos columnas completas, que es exactamente
 * lo que esta pantalla compara.
 *
 * LO QUE LA PLATAFORMA NO SABE DAR todavía (se declara con `ctx.sinDatos`, no se inventa): los
 * periodos acumulados (mes o trimestre), la serie mensual del ejercicio anterior, el envío del
 * informe al cliente y el guardado del comentario del asesor.
 *
 * DOS PARCHES SON IMPRESCINDIBLES para que las cifras salgan bien (van listados en
 * pantallas/informe.md, porque hay que aplicarlos en index.html):
 *
 *   1. `rvInf` multiplica todas las cifras por el «factor» del cliente (`c.factor`). Las empresas
 *      de la plataforma no traen ese campo —el hub lo siembra a 0—, así que hoy todo saldría
 *      multiplicado por cero.
 *   2. `rvInf` recalcula el impuesto de sociedades con un tipo fijo del 25 %, en vez de usar el
 *      importe real de la cuenta 630. Sin el parche, el resultado del periodo y el patrimonio neto
 *      del balance no son los reales.
 */
ABGA.registrar('informe', async function (ctx) {
  var empresa = ctx.empresa;
  var anio = ctx.anio;
  var clave = 'ej' + anio;                 // clave del único periodo en INF_PER
  var MESES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];

  /* ── Utilidades ─────────────────────────────────────────────────────────────────────────── */

  function num(x) { return (typeof x === 'number' && isFinite(x)) ? x : 0; }
  /** Gasto: se enseña en negativo (como lo espera la pantalla), pero sin «-0» cuando vale cero. */
  function neg(x) { var v = num(x); return v ? -v : 0; }
  function diasDeAnio(y) { return (Date.UTC(y + 1, 0, 1) - Date.UTC(y, 0, 1)) / 86400000; }

  /* ── La cuenta de resultados, con las MISMAS filas que el hub ───────────────────────────── */
  /* Las filas con valor nulo (margen bruto, EBITDA, EBIT, RAI, impuesto y resultado) las calcula
   * la propia pantalla a partir de las demás; las de valor son importes reales del informe. Con
   * `c` y `p` vacíos sale la cuenta a cero, que es lo que se enseña mientras no hay datos. */
  function filasPyg(c, p) {
    return [
      ['Importe neto de la cifra de negocios', num(c.totalIng), num(p.totalIng), 'v'],
      ['Aprovisionamientos', neg(c.aprov), neg(p.aprov), 'ap'],
      ['Margen bruto', null, null, 'mb'],
      ['Gastos de personal', neg(c.gastPers), neg(p.gastPers), 'pe'],
      ['Otros gastos de explotación', neg(c.otrosGast), neg(p.otrosGast), 'ot'],
      ['EBITDA', null, null, 'ebitda'],
      ['Amortización del inmovilizado', neg(c.amort), neg(p.amort), 'am'],
      ['Resultado de explotación', null, null, 'ebit'],
      // Resultado financiero (ingresos − gastos financieros): la pantalla lo suma al EBIT para
      // llegar al resultado antes de impuestos, igual que hace el informe de la plataforma. Si se
      // pusiera sólo el gasto financiero, el RAI perdería los ingresos financieros.
      ['Gastos financieros', num(c.resFin), num(p.resFin), 'fi'],
      ['Resultado antes de impuestos', null, null, 'bai'],
      // Impuesto real (cuenta 630), en negativo por ser gasto: la pantalla no puede inventarlo.
      ['Impuesto sobre Sociedades', neg(c.is), neg(p.is), 'is'],
      ['Resultado del periodo', num(c.resultado), num(p.resultado), 'neto']
    ];
  }

  /* ── El balance, con las MISMAS masas que el hub ────────────────────────────────────────── */
  /* `de` agrupa clientes y otros deudores: la pantalla sólo tiene una fila de deudores y su activo
   * corriente es existencias + deudores + tesorería, así que tiene que ser el activo corriente
   * completo para que el total cuadre con el de la plataforma. */
  function masa(x) {
    return {
      anc: num(x.activoNC), ex: num(x.existencias),
      de: num(x.clientes) + num(x.otrosDeudores), te: num(x.tesoreria),
      pnc: num(x.pasNC), pc: num(x.pasC)
    };
  }
  function balance(c, p) {
    return {
      cur: masa(c), prev: masa(p),
      pn0: { cur: num(c.pn) - num(c.resultado), prev: num(p.pn) - num(p.resultado) }
    };
  }

  /** Un periodo del selector: un ejercicio completo, comparado con el anterior. */
  function periodo(y, mensual, tesoreria) {
    return {
      l: 'Ejercicio ' + y, prev: 'Ejercicio ' + (y - 1), corto: 'Ejercicio ' + y,
      meses: MESES, pf: 1, y: String(y), yp: String(y - 1), dias: diasDeAnio(y),
      mensual: mensual, tesoreria: tesoreria
    };
  }
  function soloUnPeriodo(p) { var o = {}; o[clave] = p; return o; }
  function sinDatosDeLaPlataforma() {
    ctx.sinDatos('los periodos acumulados (mes o trimestre): la plataforma informa por ejercicio completo, no por periodo parcial');
    ctx.sinDatos('la serie mensual del ejercicio anterior: la plataforma sólo publica la del ejercicio en curso');
    ctx.sinDatos('el envío del informe al cliente: la plataforma no tiene endpoint de envíos');
    ctx.sinDatos('el guardado del comentario del asesor: vive sólo en esta pantalla');
  }

  /* ── Sin el ejercicio leído del ERP no se pide ningún informe ───────────────────────────── */
  /* Leerlo son cientos de consultas al ERP de ABGA y eso lo decide una persona: se deja la
   * pantalla en blanco, se declara y se ofrece. */
  if (!ctx.hayCache()) {
    var vacio = {};
    ctx.poner('INF_PER', soloUnPeriodo(periodo(anio, [], [])));
    ctx.poner('INF_PYG', filasPyg(vacio, vacio));
    ctx.poner('INF_BAL', balance(vacio, vacio));
    ctx.parchear({ infPeriodo: clave, infCliente: empresa });
    ctx.sinDatos('el ejercicio ' + anio + ' no está leído del ERP');
    ctx.pedirDelErp('El ejercicio ' + anio + ' no está leído todavía.');
    return;
  }

  /* ── El informe financiero de la plataforma ─────────────────────────────────────────────── */
  var datos;
  try {
    datos = await ctx.informe('autodespro');
  } catch (fallo) {
    var cero = {};
    ctx.poner('INF_PER', soloUnPeriodo(periodo(anio, [], [])));
    ctx.poner('INF_PYG', filasPyg(cero, cero));
    ctx.poner('INF_BAL', balance(cero, cero));
    ctx.parchear({ infPeriodo: clave, infCliente: empresa });
    ctx.sinDatos('el informe financiero del ejercicio ' + anio + ' no se ha podido calcular: ' + (fallo.message || fallo));
    return;
  }

  var c = datos.actual || {};
  var p = datos.anterior || {};

  /* ── Series mensuales del ejercicio (para las gráficas) ─────────────────────────────────── */
  var mensual = (datos.evMensual || []).map(function (m) {
    return { mes: m.mes, ingresos: num(m.ingresos), gastos: num(m.gastos) };
  });
  var tesoreria = (((datos.tesoreria || {}).mensual) || []).map(function (m) { return num(m.saldo); });

  /* ── Se dejan los datos donde la pantalla los lee ───────────────────────────────────────── */
  ctx.poner('INF_PER', soloUnPeriodo(periodo(anio, mensual, tesoreria)));
  ctx.poner('INF_PYG', filasPyg(c, p));
  ctx.poner('INF_BAL', balance(c, p));
  // El estado del hub arranca mirando un periodo de ejemplo ('ago26'): hay que apuntarlo al
  // periodo real y al cliente que se está viendo, o `INF_PER[infPeriodo]` no existe.
  ctx.parchear({ infPeriodo: clave, infCliente: empresa });

  /* ── Lo que se declara (no se inventa) ──────────────────────────────────────────────────── */
  sinDatosDeLaPlataforma();
  if ((datos.reales || []).indexOf(anio) < 0) {
    ctx.sinDatos('el ejercicio ' + anio + ' no trae apuntes propios en la plataforma: las cifras pueden ser de otro ejercicio');
  }
  var cuadre = datos.cuadre || {};
  if (Math.abs(num(cuadre.activo) - num(cuadre.pasivoPN)) > 1) {
    ctx.sinDatos('el balance del ejercicio no cuadra: activo y patrimonio neto más pasivo se llevan ' +
      (num(cuadre.activo) - num(cuadre.pasivoPN)).toLocaleString('es-ES', { maximumFractionDigits: 2 }) + ' €');
  }
  (datos.avisos || []).forEach(function (t) { ctx.sinDatos('informe financiero: ' + t); });
});
