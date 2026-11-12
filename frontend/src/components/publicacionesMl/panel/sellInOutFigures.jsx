import { formatPct } from '../../../utils/metricasMlFormat';
import { sellInOrigen } from '../../../utils/sellInOrigen';
import cellStyles from '../cells.module.css';
import { formatMoneda, isForeign } from './costoMoneda';
import { amount } from './format';

/*
 * The cost and the markup of a publication with the sell in / sell out of its product today, as Rentabilidad
 * (Resumen) and the panel header show them: one rendering, so both always agree.
 */

/** The key of this publication's markup in `sell_in_out.markups_sell_in[_out]` (backend `detail.SELL_IN_OUT_KEY`). */
const SELL_IN_OUT_KEY = 'publicacion';

const isBlank = (value) => value === null || value === undefined;

/** A marked-down figure: an unknown amount, or no sell in at all, with what it means in the tooltip. */
const Muted = ({ title, children }) => (
  <span className={cellStyles.empty} title={title}>
    {children}
  </span>
);

export const MarkupValue = ({ value }) => (
  <span className={cellStyles.markup} data-negative={value < 0 ? '' : undefined}>
    {formatPct(value)}
  </span>
);

/**
 * The cost of the purchase lot the next sale takes its sell in from, with its discount and units left, in the cost's
 * own currency (S10: the backend converts it at the rate it converted the cost with); the pesos in the tooltip.
 */
export function SellInCost({ sellIn, format = amount }) {
  if (!sellIn) return <Muted title="Sin sell in vigente">-</Muted>;
  const origen = sellInOrigen(sellIn); // a purchase lot or the % of cost bonuses (T25c)
  const pesos = `$ ${amount(sellIn.descuento_unit)}`;
  const enMoneda = isForeign(sellIn.moneda_costo);
  const lines = [];
  if (enMoneda && !isBlank(sellIn.descuento_unit_moneda)) {
    lines.push(`Descuento por unidad: ${formatMoneda(sellIn.descuento_unit_moneda, sellIn.moneda_costo)} (${pesos})`);
    if (!isBlank(sellIn.costo)) lines.push(`c/ sell in en pesos: $ ${amount(sellIn.costo)}`);
  } else {
    lines.push(`Descuento por unidad: ${pesos}`);
  }
  lines.push(origen);
  const detalle = lines.join('\n');
  const costo = enMoneda ? sellIn.costo_moneda : sellIn.costo;
  if (isBlank(costo)) return <Muted title={detalle}>Sin tipo de cambio</Muted>;
  return <span title={detalle}>{formatMoneda(costo, enMoneda ? sellIn.moneda_costo : 'ARS', format)}</span>;
}

/**
 * The publication's markup with sell in and sell out when there is sell out, else with sell in only.
 * "Pendiente" when an amount is unknown (a lot without a cost in pesos, a sell out without its rate
 * or base): never a made-up figure.
 */
export function SellInOutMarkup({ sellInOut }) {
  return sellInOutMarkup(sellInOut);
}

/**
 * `SellInOutMarkup` with its "c/ sell in/out" label, or nothing at all when there is nothing to show (no sell in nor
 * sell out today), so the label never stands alone.
 */
export function SellInOutMarkupLine({ sellInOut, className, labelClassName, labelTitle }) {
  const value = sellInOutMarkup(sellInOut);
  if (value == null) return null;
  return (
    <span className={className}>
      <span className={labelClassName} title={labelTitle}>
        c/ sell in/out{' '}
      </span>
      {value}
    </span>
  );
}

function sellInOutMarkup(sellInOut) {
  if (!sellInOut) return null;
  const { sell_in: sellIn, sell_out: sellOut } = sellInOut;
  const conSellOut = sellInOut.markups_sell_in_out?.[SELL_IN_OUT_KEY];
  if (!isBlank(conSellOut)) {
    return (
      <span title={`Con sell in y sell out (sell out: $ ${amount(sellOut.monto_unit)} por unidad, sin IVA)`}>
        <MarkupValue value={conSellOut} />
      </span>
    );
  }
  const sellOutPendiente = Boolean(sellOut) && isBlank(sellOut.monto_unit);
  const conSellIn = sellInOut.markups_sell_in?.[SELL_IN_OUT_KEY];
  if (isBlank(conSellIn)) {
    const costoPendiente = Boolean(sellIn) && isBlank(sellIn.costo);
    if (costoPendiente || sellOutPendiente) {
      return <Muted title="Falta el tipo de cambio o la base para calcular el markup">Pendiente</Muted>;
    }
    return null;
  }
  return (
    <span title={sellOutPendiente ? 'Con sell in; el sell out está pendiente' : 'Con sell in'}>
      <MarkupValue value={conSellIn} />
    </span>
  );
}
