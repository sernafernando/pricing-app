import { formatPppMonto } from '../hooks/useProductosOffsets';
import { sellInOrigen } from '../utils/sellInOrigen';

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

function sellInTitle(sellIn) {
  const origen = sellInOrigen(sellIn); // a purchase lot or the % of cost bonuses (T25c)
  return `Descuento de sell in por unidad: ${ars(sellIn.descuento_unit)} · ${origen}`;
}

/**
 * Subordinate companion line for the sell in / sell out figures of a product
 * today (backend `sell_in_out`, sell-in-sell-out T9). Renders next to the PPP
 * line under the real cost/markup value, never replacing it.
 *
 * - `sellInOut` null/undefined → renders nothing: the row stays as it was.
 * - Without `markupKey` (cost cell): the cost with sell in, in ARS, with the
 *   discount per unit and the remaining units of the purchase lot as tooltip.
 *   Nothing when only sell out applies (the cost does not change).
 * - With `markupKey`: the markup with sell in (`markups_sell_in`) and with
 *   sell in + sell out (`markups_sell_in_out`; labelled "c/ sell out" when
 *   there is no sell in), same keys and scale as the PPP markups.
 * - An unknown amount (no ARS cost, or a sell out without rate/base) shows as
 *   "pendiente", never as a made-up number. A key that was not recorded is
 *   omitted, never replaced by a sibling key.
 */
export default function SellInOutLine({ sellInOut, markupKey }) {
  if (!sellInOut) return null;
  const sellIn = sellInOut.sell_in ?? null;
  const sellOut = sellInOut.sell_out ?? null;

  if (!markupKey) {
    if (!sellIn) return null;
    const costo = sellIn.costo === null || sellIn.costo === undefined ? PENDIENTE : ars(sellIn.costo);
    return (
      <div className="sell-in-out-line" title={sellInTitle(sellIn)}>
        {`c/ sell in: ${costo}`}
      </div>
    );
  }

  const partes = [];

  if (sellIn) {
    const valor = formatPppMonto(sellInOut.markups_sell_in?.[markupKey], markupKey);
    const sinCosto = sellIn.costo === null || sellIn.costo === undefined;
    if (valor !== null || sinCosto) {
      partes.push({ label: 'c/ sell in', valor: valor ?? PENDIENTE, title: sellInTitle(sellIn) });
    }
  }

  if (sellOut) {
    const label = sellIn ? 'c/ sell in + sell out' : 'c/ sell out';
    const sinMonto =
      sellOut.monto_unit === null ||
      sellOut.monto_unit === undefined ||
      Boolean(sellIn && (sellIn.costo === null || sellIn.costo === undefined));
    const valor = sinMonto ? null : formatPppMonto(sellInOut.markups_sell_in_out?.[markupKey], markupKey);
    if (valor !== null || sinMonto) {
      partes.push({ label, valor: valor ?? PENDIENTE, title: sellOutTitle(sellOut) });
    }
  }

  if (partes.length === 0) return null;

  return (
    <div className="sell-in-out-line">
      {partes.map((parte) => (
        <span key={parte.label} className="sell-in-out-line__item" title={parte.title}>
          {`${parte.label}: ${parte.valor}`}
        </span>
      ))}
    </div>
  );
}
