/* Clientes · la cartera real de la plataforma y la ficha del cliente
 *
 * La pantalla llegó con ocho clientes escritos a mano dentro del hub (CLIENTES: NIF, domicilio,
 * asesor, facturación anual, plantilla, régimen de IVA, contacto...) y con una ficha por cliente
 * (documentos, envíos, situación fiscal por modelo y depósito de las cuentas anuales) que también
 * era de ejemplo. Este traductor la alimenta con lo que la plataforma sí sabe:
 *
 *   /api/empresas            la cartera del usuario: cod_empresa, nombre, ejercicio_inicio, notas
 *                            (las notas llevan el NIF y los servicios contratados) y con_datos
 *   /api/interno/cartera     el análisis de los clientes que tienen el ejercicio leído (panel
 *                            interno): nivel global, hallazgos por gravedad e importe en riesgo
 *   /api/interno/usuarios    qué cuentas de acceso al portal hay detrás de cada cliente
 *   /api/analisis            el análisis de su empresa cuando quien mira es el propio cliente
 *
 * Lo que la plataforma no guarda se declara con `ctx.sinDatos` y se deja en blanco: el domicilio,
 * la forma jurídica, el CNAE, el régimen de IVA, la plantilla, la facturación anual y el factor de
 * escala del cliente, quién es su asesor, la persona de contacto con su teléfono y su correo, los
 * documentos del expediente, los envíos de informes, el estado de presentación de cada modelo y el
 * histórico de depósito de las cuentas anuales. Nada de eso se rellena con cifras inventadas.
 *
 * Ojo con la privacidad: /api/empresas devuelve `pin_hash` (el PIN de alta del cliente) en cada
 * empresa. La lista que se deja en el hub se construye campo a campo a partir de los que se usan,
 * así que el PIN no puede acabar ni en la pantalla ni en el estado de la aplicación.
 */
ABGA.registrar('clientes', async function (ctx) {
  var anio = ctx.anio;

  /* ── El estado de cada cliente: el análisis de la cartera (sólo el panel interno) ────────── */

  var cartera = {};   // cod_empresa → fila real de /api/interno/cartera
  var nivel = {};     // cod_empresa → nivel global del análisis
  if (ctx.estado.interno) {
    try {
      var analizada = await ctx.api.interno.cartera(anio);
      (analizada.filas || []).forEach(function (f) {
        nivel[f.cod_empresa] = f.nivel_global;
        cartera[f.cod_empresa] = f;
      });
      if (!(analizada.filas || []).length) {
        ctx.sinDatos('el análisis de los clientes (no hay ningún ejercicio ' + anio + ' leído en la caché)');
      }
      if ((analizada.totales || {}).sin_datos) {
        ctx.sinDatos('el estado de los ' + analizada.totales.sin_datos + ' clientes que no tienen el ejercicio ' +
          anio + ' leído: sin analizar hasta que se cargue el ejercicio');
      }
    } catch (fallo) {
      ctx.sinDatos('el análisis de la cartera de clientes: ' + (fallo.message || fallo));
    }
  } else if (ctx.hayCache(anio)) {
    // Un cliente sólo ve sus empresas: se le pide su análisis, que ya está leído del ERP.
    try {
      var suyo = await ctx.api.analisis(ctx.empresa, anio);
      nivel[ctx.empresa] = ((suyo.data || {}).resumen || {}).nivel_global;
    } catch (fallo) {
      ctx.sinDatos('el análisis del ejercicio ' + anio + ': ' + (fallo.message || fallo));
    }
  } else {
    ctx.sinDatos('el estado de sus empresas en el ejercicio ' + anio +
      ': el ejercicio todavía no está leído (aquí no se pide nada al ERP)');
  }

  /* ── Quién entra al portal en nombre de cada cliente ─────────────────────────────────────── */

  var cuentas = {};   // cod_empresa → cuentas de acceso al portal
  function apuntar(cod, cuenta) { (cuentas[cod] = cuentas[cod] || []).push(cuenta); }
  if (ctx.estado.interno) {
    try {
      var usuarios = (await ctx.api.interno.usuarios()).usuarios || [];
      usuarios.forEach(function (u) {
        (u.empresas || []).forEach(function (cod) {
          apuntar(cod, { nombre: u.nombre || u.email, email: u.email,
                         rol: u.rol === 'interno' ? 'Equipo de ABGA' : 'Cuenta del cliente' });
        });
      });
    } catch (fallo) {
      ctx.sinDatos('las cuentas de acceso al portal de cada cliente: ' + (fallo.message || fallo));
    }
  } else if (ctx.estado.usuario) {
    var yo = ctx.estado.usuario;
    (yo.empresas || []).forEach(function (cod) {
      apuntar(cod, { nombre: yo.nombre || yo.email, email: yo.email, rol: 'Tu cuenta' });
    });
  }

  /* ── Las notas del cliente llevan el NIF y los servicios contratados ─────────────────────── */

  // Son texto libre ("NIF B67700856 · contabilidad General · laboral · obligaciones"), así que se
  // leen con cuidado: si algo no está, se deja vacío en lugar de suponerlo.
  function deNotas(notas) {
    var texto = String(notas || '');
    var nif = /NIF\s*([0-9A-Za-z]{8,12})/i.exec(texto);
    return {
      nif: nif ? nif[1].toUpperCase() : '',
      // Los servicios son las notas sin el NIF y sin separadores sueltos.
      servicios: texto.replace(/NIF\s*[0-9A-Za-z]{8,12}\s*·?\s*/i, '').replace(/^·\s*|·\s*$/g, '').trim()
    };
  }

  /* ── La lista de clientes ────────────────────────────────────────────────────────────────── */

  var ESTADO = { alerta: 'err', aviso: 'warn', ok: 'ok', no_evaluable: 'na' };
  var filas = (ctx.estado.empresas || []).map(function (e) {
    var f = cartera[e.cod_empresa];
    var datos = deNotas(e.notas);
    return {
      id: e.cod_empresa,
      nombre: e.nombre || e.cod_empresa,
      // Recuperados de las notas del cliente; el resto de la ficha no está en la plataforma.
      nif: datos.nif,
      servicios: datos.servicios,
      notas: e.notas || '',
      alta: e.ejercicio_inicio ? String(e.ejercicio_inicio) : '',
      conDatos: !!e.con_datos,
      // El semáforo sale del análisis: alerta, aviso, ok o sin analizar (no 'al día' por defecto).
      estado: ESTADO[nivel[e.cod_empresa]] || 'na',
      // `fact` no se inventa (null = raya en pantalla). `factor` va a 1, que es «no escalar»: el hub
      // lo usa como multiplicador en el informe financiero y la plataforma no tiene factor de escala.
      fact: null, factor: 1, empleados: 0,
      forma: '', cnae: '', ciudad: '', iva: '', asesor: '',
      email: '', telefono: '', contacto: '',
      cuentas: cuentas[e.cod_empresa] || [],
      cartera: f ? { nivel: f.nivel_global, rojo: f.n_rojo, naranja: f.n_naranja,
                     verde: f.n_verde, no_evaluable: f.n_no_evaluable, total: f.n_total,
                     importe: f.importe_riesgo } : null
    };
  });
  ctx.poner('CLIENTES', filas);

  /* ── La ficha: documentos, envíos y cuentas anuales no están en la plataforma ─────────────── */

  // La matriz de modelos por trimestre (`IMPUESTOS`) y su tabla de estados (`IMP_EST`) las alimenta
  // el traductor de la pantalla de Impuestos (`pantallas/impuestos.js`) con lo que la plataforma sí
  // calcula: aquí no se tocan, porque son suyas. Lo que la plataforma no tiene es el *estado de
  // presentación* de cada modelo por cliente, y eso se declara abajo.
  ctx.poner('DOCS', []);
  ctx.poner('ENVIOS', []);
  ctx.parchear({ envios: [] });
  ctx.sinDatos('los documentos del expediente del cliente (no hay endpoint de documentos)');
  ctx.sinDatos('los envíos de informes al cliente (no hay endpoint ni registro de envíos)');
  ctx.sinDatos('el estado de presentación de cada modelo por cliente: el módulo fiscal calcula 303, ' +
    '111 y 202 por empresa y ejercicio, pero no registra qué se ha presentado');
  ctx.sinDatos('el depósito de las cuentas anuales por ejercicio (no hay registro de depósitos)');
  ctx.sinDatos('el domicilio, la forma jurídica, el CNAE, el régimen de IVA, la plantilla, la ' +
    'facturación anual y el factor de escala del cliente, su asesor asignado y la persona de ' +
    'contacto con teléfono y correo (la plataforma sólo guarda las cuentas de acceso al portal)');

  /* ── La ficha abierta tiene que seguir existiendo en la lista ────────────────────────────── */

  // Si el cliente de la ficha ya no está (o no hay ninguno), se vuelve a la lista: `rvClientes`
  // pinta la ficha de `CLIENTES[0]` y con la lista vacía se quedaría en nada.
  var ids = filas.map(function (f) { return f.id; });
  ctx.parchear(function (s) {
    return (!ids.length || (s.fichaId && ids.indexOf(s.fichaId) < 0)) ? { fichaId: null } : {};
  });
});
