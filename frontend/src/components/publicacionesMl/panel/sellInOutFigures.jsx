import { formatPct } from '../../../utils/metricasMlFormat';
import cellStyles from '../cells.module.css';
import { amount } from './format';

/*
 * The markup of a publication with the sell out of its product today ("c/ SO"), as Rentabilidad (Resumen) and the
 * panel header show it: one rendering, so both always agree. No cost with sell in (costo SI T5 PR B: costo SI
 * already holds the sell in).
 */

/** The key of this publication's markup in `sell_in_out.markups_sell_in_out` (backend `detail.SELL_IN_OUT_KEY`). */
const SELL_IN_OUT_KEY = 'publicacion';

const isBlank = (value) => value === null || value === undefined;

/** A marked-down figure: an unknown amount, with what it means in the tooltip. */
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
 * The publication's "c/ SO" markup: its sell out added to the profit, over the costo SI; nothing without sell out
 * (D1: the sell in is already inside the costo SI). "Pendiente" when the sell out's amount is unknown (no rate or
 * base): never a made-up figure.
 */
export function SellInOutMarkup({ sellInOut }) {
  return sellInOutMarkup(sellInOut);
}

/**
 * `SellInOutMarkup` with its "c/ SO" label, or nothing at all when there is nothing to show (no sell out
 * today), so the label never stands alone.
 */
export function SellInOutMarkupLine({ sellInOut, className, labelClassName, labelTitle }) {
  const value = sellInOutMarkup(sellInOut);
  if (value == null) return null;
  return (
    <span className={className}>
      <span className={labelClassName} title={labelTitle}>
        c/ SO{' '}
      </span>
      {value}
    </span>
  );
}

function sellInOutMarkup(sellInOut) {
  const sellOut = sellInOut?.sell_out;
  if (!sellOut) return null; // D1: no markup with sell in, it is already inside the costo SI
  const conSellOut = sellInOut.markups_sell_in_out?.[SELL_IN_OUT_KEY];
  if (!isBlank(conSellOut)) {
    return (
      <span title={`Con sell out ($ ${amount(sellOut.monto_unit)} por unidad, sin IVA)`}>
        <MarkupValue value={conSellOut} />
      </span>
    );
  }
  if (isBlank(sellOut.monto_unit)) {
    return <Muted title="Falta el tipo de cambio o la base para calcular el markup">Pendiente</Muted>;
  }
  return null;
}
