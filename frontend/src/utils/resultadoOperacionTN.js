/**
 * A Tienda Nube operation's commission, ganancia and markup in the operations list, recomputed with the chosen payment
 * method's commission. The API returns a null cost when it is unknown (no costo SI or USD rate on the sale date,
 * sell-in-costo-si T3 PR 9); a 0 cost is the older "sin costo" value. Either way there is no cost to subtract: the
 * ganancia and markup are unknown (null), never the whole clean amount shown as profit.
 */
export const resultadoOperacionTN = (op, comisionPorcentaje) => {
  const monto = parseFloat(op.precio_final_sin_iva) || 0;
  const comision = monto * (comisionPorcentaje / 100);
  const montoLimpio = monto - comision;
  const costo = op.costo_pesos_sin_iva == null ? null : parseFloat(op.costo_pesos_sin_iva);
  if (costo == null || Number.isNaN(costo) || costo === 0) {
    return { sinCosto: true, comision, montoLimpio, ganancia: null, markup: null };
  }
  const ganancia = montoLimpio - costo;
  return { sinCosto: false, comision, montoLimpio, ganancia, markup: costo > 0 ? ganancia / costo : null };
};
