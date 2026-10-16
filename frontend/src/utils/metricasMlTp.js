/**
 * "Costos TP" on the Métricas ML board (backend P4, `costos_tp`): the request param, the words the screen uses
 * and how a Total TP reads. Nothing here computes a TP figure -- the API does.
 */

export const TP_MARKUP_HINT = 'Usa el costo TP en las operaciones de la tienda TP-Link';

/** The board's query for the toggle: absent while off, so the request is exactly the one made without it. */
export function tpRequestParams(on) {
  return on ? { costos_tp: true } : {};
}

const TP_OFF = 'Se desactivó "Costos TP".';
const TP_ERRORS = {
  403: `No tenés permiso para ver los costos TP. ${TP_OFF}`,
  503: `Los costos TP no están disponibles: no hay una tienda TP-Link configurada. ${TP_OFF}`,
};

/** The message for a status the TP view answers with (403 no profit view, 503 no TP store); `null` otherwise. */
export function tpErrorMessage(status) {
  return TP_ERRORS[status] ?? null;
}

/** The hover text of the "lines without a TP cost" count. */
export function tpIncompleteTitle(count) {
  return `${count} ${count === 1 ? 'venta' : 'ventas'} de la tienda TP-Link sin costo TP: el Total TP está incompleto`;
}

/**
 * How a Total TP reads: `complete`, `partial` (known, but some TP lines lack a TP cost), `incomplete` (unknown
 * because every TP line lacks it) or `none` (no TP-store sale at all). Unknown is never 0.
 */
export function tpCellState(value, incompletos) {
  const known = value !== null && value !== undefined;
  const missing = incompletos || 0;
  let kind = 'none';
  if (known) kind = missing > 0 ? 'partial' : 'complete';
  else if (missing > 0) kind = 'incomplete';
  return { known, incompletos: missing, kind };
}
