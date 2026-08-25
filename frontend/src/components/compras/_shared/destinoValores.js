/**
 * Resolución del pedido destino de un VALOR (NC, cheque) dentro de una OP.
 *
 * Vive fuera del componente porque es el corazón del camino de plata: la
 * deducción del ítem Y el renglón del resumen tienen que leer exactamente esta
 * función. Cuando cada uno tenía su propio criterio, el desglose mostraba
 * "Notas de crédito −$26M" mientras el total no bajaba un peso.
 *
 * Contrato (el mismo que el backend, ver `NCAplicadaItem`): el `pedido_id` es
 * opcional cuando la OP imputa un único pedido — ahí se infiere — y obligatorio
 * cuando imputa varios.
 */

/**
 * @param {{pedido_id?: number|string|null}} valor - NC o cheque aplicado.
 * @param {string[]} pedidoItemIds - ids (string) de los pedidos de la OP.
 * @param {boolean} isSinglePedido - true si la OP imputa exactamente un pedido.
 * @returns {string|null} id del pedido que descuenta, o null si no hay destino
 *   resoluble. `null` es la respuesta honesta para "seleccionado pero sin
 *   destino todavía": el valor no baja ningún ítem, así que tampoco puede
 *   figurar como descuento.
 */
export const resolverDestinoItemId = (valor, pedidoItemIds, isSinglePedido) => {
  const pedidoId = valor?.pedido_id != null ? String(valor.pedido_id) : null;
  if (pedidoId !== null) {
    // Un destino que no está en la OP no es un destino: mandarlo al backend
    // termina en 422, y descontarlo acá sería mentir sobre el total.
    return pedidoItemIds.includes(pedidoId) ? pedidoId : null;
  }
  return isSinglePedido ? pedidoItemIds[0] : null;
};

/**
 * Una OP a cuenta (sin pedidos) cubre su total sin imputar nada, así que ahí un
 * `pedido_id` nulo es correcto y no un dato faltante.
 *
 * @param {string[]} pedidoItemIds
 * @returns {boolean} true si los valores de esta OP necesitan destino.
 */
export const requiereDestino = (pedidoItemIds) => pedidoItemIds.length > 0;
