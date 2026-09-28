/* Ajustes · lo que la plataforma sabe del despacho, del ERP y de sus usuarios
 *
 * La pantalla llegó inventada de arriba abajo: cuatro usuarios de ejemplo, un estado de conexión
 * con el ERP que nunca se comprobaba, una tabla de sincronización con volúmenes a ojo, un umbral
 * de confianza de la IA que no existe en ninguna parte y once interruptores que no cambiaban nada.
 *
 * Aquí se cambia por datos reales:
 *
 *   /api/cache                 qué ejercicios hay leídos del ERP: asientos, líneas y cuándo
 *   /api/interno/usuarios      las cuentas del portal: nombre, correo, rol, activo, alta y clientes
 *   /api/interno/umbrales      los umbrales reales del análisis (los que deciden cuándo salta cada
 *                              comprobación), con su valor, su unidad, para qué son y su origen
 *   sesión de la plataforma    la cuenta que está mirando la pantalla (nombre, correo, rol, alta)
 *
 * Lo que no existe —preferencias de notificación por tipo de aviso, interruptores de automatización,
 * los datos fiscales del despacho, el correo de envío a clientes, el ejercicio o el plan contable
 * por defecto y el pie de los informes— se declara con `ctx.sinDatos` y se deja sin pintar.
 */
ABGA.registrar('ajustes', async function (ctx) {
  function fecha(instante) {
    var t = new Date(instante);
    if (isNaN(t.getTime())) return '—';
    return t.toLocaleString('es-ES', { day: '2-digit', month: '2-digit', year: 'numeric',
                                       hour: '2-digit', minute: '2-digit' });
  }

  /* ── La conexión con el ERP: lo que hay leído y cuándo se leyó ────────────────────────────── */

  var leidos = [];
  try {
    leidos = ((await ctx.api.cache()).cache || []).slice();
  } catch (fallo) {
    ctx.sinDatos('el estado de la caché del ERP: ' + (fallo.message || fallo));
  }
  var nombre = {};
  (ctx.estado.empresas || []).forEach(function (e) { nombre[e.cod_empresa] = e.nombre; });
  var ultima = 0;
  leidos.forEach(function (c) { ultima = Math.max(ultima, Date.parse(c.actualizado || '') || 0); });

  // El estado del ERP sale de la propia plataforma (hay conexión configurada) y de la caché (hay
  // ejercicios leídos). Antes era un 'Conectado' escrito a mano que nunca se comprobaba.
  ctx.parchear({
    ajErp: (ctx.estado.erpConfigurado || leidos.length) ? 'ok' : 'err',
    ajErpAt: ultima ? fecha(ultima) : 'sin lecturas registradas',
    ajCache: leidos
      .sort(function (a, b) { return (Date.parse(b.actualizado || '') || 0) - (Date.parse(a.actualizado || '') || 0); })
      .slice(0, 20)
      .map(function (c) {
        return {
          l: (nombre[c.empresa] || c.empresa) + ' · ejercicio ' + c.ejercicio,
          f: Number(c.n_asientos || 0) + ' asientos · ' + Number(c.n_lineas || 0) + ' líneas',
          n: c.actualizado ? fecha(c.actualizado) : '—'
        };
      })
  });
  if (!leidos.length) ctx.sinDatos('los ejercicios leídos del ERP (la caché está vacía)');

  /* ── Los usuarios del portal ─────────────────────────────────────────────────────────────── */

  if (ctx.estado.interno) {
    try {
      var usuarios = (await ctx.api.interno.usuarios()).usuarios || [];
      ctx.parchear({
        ajUsers: usuarios.map(function (u) {
          return {
            id: u.email,
            nombre: u.nombre || u.email,
            email: u.email,
            rol: u.rol === 'interno' ? 'Equipo de ABGA' : 'Cuenta de cliente',
            clientes: (u.empresas || []).length,
            estado: u.activo ? 'Activo' : 'Inactivo',
            // La columna del hub dice «Último acceso», pero la plataforma sólo guarda el alta de
            // la cuenta: se pinta la fecha real y se propone cambiar el encabezado.
            ult: u.creado ? fecha(u.creado) : '—'
          };
        })
      });
    } catch (fallo) {
      ctx.sinDatos('los usuarios del portal: ' + (fallo.message || fallo));
    }
  } else {
    ctx.sinDatos('los usuarios del despacho (es del panel interno de ABGA)');
  }

  /* ── Los umbrales del análisis: los que de verdad usa la plataforma ──────────────────────── */

  var TITULO = {
    '347_operaciones': 'Modelo 347 · operaciones con terceros',
    concentracion_clientes: 'Concentración de clientes',
    antiguedad_clientes: 'Antigüedad de la deuda de clientes',
    endeudamiento: 'Endeudamiento',
    tipo_impuesto_sociedades: 'Tipo del Impuesto sobre Sociedades',
    auditoria_activo: 'Auditoría · límite de activo',
    auditoria_cifra_negocios: 'Auditoría · cifra de negocios',
    auditoria_empleados: 'Auditoría · plantilla',
    iva_a_compensar: 'IVA a compensar',
    concentracion_proveedores: 'Concentración de proveedores',
    carga_financiera: 'Carga financiera',
    rotacion_existencias: 'Rotación de existencias'
  };
  var umbrales = [];
  var clienteUmbral = '';
  if (ctx.estado.interno) {
    try {
      var ajustes = await ctx.api.interno.umbrales(ctx.empresa);
      clienteUmbral = ajustes.empresa || ctx.empresa;
      umbrales = Object.keys(ajustes.umbrales || {}).map(function (clave) {
        var u = ajustes.umbrales[clave] || {};
        return {
          // El título sale de un mapa de nombres legibles y, si la clave no está, se usa el
          // identificador tal cual. La descripción (`para`) viene de la plataforma: es la que
          // explica qué mide el umbral.
          l: TITULO[clave] || clave.replace(/_/g, ' '),
          d: u.para || '',
          v: (u.valor === null || u.valor === undefined ? '—' : u.valor) + ' ' + (u.unidad || ''),
          o: u.origen === 'defecto' ? 'Por defecto' : (u.origen || '—')
        };
      });
      if (!umbrales.length) ctx.sinDatos('los umbrales del análisis del cliente en curso');
    } catch (fallo) {
      ctx.sinDatos('los umbrales del análisis: ' + (fallo.message || fallo));
    }
  }
  ctx.parchear({ ajUmbrales: umbrales, ajUmbralCliente: clienteUmbral });

  /* ── La cuenta que está mirando los ajustes ──────────────────────────────────────────────── */

  var sesion = ctx.estado.usuario || {};
  ctx.parchear({
    ajDespacho: [
      { k: 'Cuenta', v: sesion.nombre || sesion.email || '—' },
      { k: 'Correo', v: sesion.email || '—' },
      { k: 'Rol', v: sesion.rol === 'interno' ? 'Equipo de ABGA' : 'Cuenta de cliente' },
      { k: 'Estado de la cuenta', v: sesion.activo === false ? 'Inactiva' : 'Activa' },
      { k: 'Alta', v: sesion.creado ? fecha(sesion.creado) : '—' },
      { k: 'Clientes asignados', v: (sesion.empresas || []).length }
    ]
  });

  /* ── Lo que el diseño de esta pantalla supone y la plataforma no tiene ───────────────────── */

  ctx.sinDatos('los datos fiscales del despacho (razón social, NIF, dirección) y su correo de envío a clientes');
  ctx.sinDatos('el ejercicio por defecto, el plan contable y el pie de los informes (cada informe sale con los datos del cliente y del ejercicio que se elija)');
  ctx.sinDatos('las preferencias de notificación por tipo de aviso (los avisos se generan y se ven en la campana; no se configuran)');
  ctx.sinDatos('los interruptores de automatización de la IA (la plataforma no guarda ninguna preferencia de ese tipo)');
  ctx.sinDatos('el último acceso de cada usuario (la plataforma guarda el alta de la cuenta, no la última sesión)');

  ctx.avisoFijo('Ajustes del despacho: la plataforma no guarda ninguna configuración del despacho, ' +
    'así que no hay nada que guardar ni interruptores que cambiar. Lo que se ve aquí es real —la cuenta ' +
    'con la que estás dentro, los ejercicios leídos del ERP, los usuarios del portal y los umbrales ' +
    'del análisis— y lo que el diseño pedía y no existe está declarado como «sin datos».');
});
