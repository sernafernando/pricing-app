import { formatPppMonto } from '../hooks/useProductosOffsets';

const PENDIENTE = 'pendiente';

function ars(monto) {
  return `ARS $${monto.toFixed(2)}`;
}

function sellOutTitle(sellOut) {
  if (sellOut.monto_unit === null || sellOut.monto_unit === undefined) {
    return 'Monto de sell out pendiente: falta el tipo de cambio o la base de la campaña';
  }
  const campanas = (sellOut.campana_ids ?? []).map((id) => `#${id}`).join(', ');
  return `Sell out por unidad: ${ars(sellOut.monto_unit)} · Campañas: ${campanas}`;
}

/**
 * Subordinate companion line for the markup with sell out of a product today
 * (backend `sell_in_out`, sell-in-sell-out T9). Renders next to the PPP line
 * under the real cost/markup value, never replacing it.
 *
 * - `sellInOut` null/undefined, or no sell out → renders nothing: the row stays
 *   as it was. There is no sell in (costo SI T5 PR B; D1: markups are over
 *   costo SI and sell out adds to the sale's profit).
 * - The cost cell is `CostoCell` (S10b: one line, in the cost's currency).
 * - `markupKey`: the markup with sell out (`markups_sell_in_out`, labelled
 *   "c/ SO"), same keys and scale as the PPP markups.
 * - A sell out without rate/base shows as "pendiente", never as a made-up
 *   number. A key that was not recorded is omitted, never replaced by a
 *   sibling key.
 */
export default function SellInOutLine({ sellInOut, markupKey }) {
  const sellOut = sellInOut?.sell_out ?? null;
  if (!sellOut) return null;

  const sinMonto = sellOut.monto_unit === null || sellOut.monto_unit === undefined;
  const valor = sinMonto ? null : formatPppMonto(sellInOut.markups_sell_in_out?.[markupKey], markupKey);
  if (valor === null && !sinMonto) return null;

  return (
    <div className="sell-in-out-line">
      <span className="sell-in-out-line__item" title={sellOutTitle(sellOut)}>
        {`c/ SO: ${valor ?? PENDIENTE}`}
      </span>
    </div>
  );
}
