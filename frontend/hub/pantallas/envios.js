/* Envíos a clientes · la plataforma todavía no envía informes
 *
 * Esta pantalla llegó en el diseño del hub con un calendario de envíos (programado, enviado, abierto,
 * con error), los destinatarios y las plantillas. En la plataforma no hay nada de eso: no existe
 * ningún endpoint de envío, ni registro de correos enviados, ni plantillas guardadas. El envío de
 * informes por correo lo hace hoy ABGA a mano desde su gestor de correo.
 *
 * Así que no se pinta un calendario inventado: se vacía la lista y se dice en pantalla, que es lo
 * único honesto mientras no haya endpoint. Cuando exista, este traductor es el sitio donde va.
 */
ABGA.registrar('envios', async function (ctx) {
  ctx.poner('ENVIOS', []);
  ctx.parchear({ envios: [], envSelId: null, envView: 'lista' });
  ctx.sinDatos('el envío de informes al cliente (no hay endpoint ni registro de envíos)');
  ctx.avisoFijo('El envío de informes a clientes aún no está en la plataforma. ' +
    'No hay ningún dato detrás de este calendario, así que se deja vacío en vez de rellenarlo.');
});
