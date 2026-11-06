import { SELL_IN_OUT_LABEL, formatSellInOutPct, isSellInOutShown } from './sellInOutMarkup';
import styles from './promociones.module.css';

const TITLE = 'Markup con el sell in y el sell out de hoy del producto';

/**
 * The backend's `markup_sell_in_out` (the promo's net with the product's sell in / sell out today,
 * the Precios tab rule) as an extra figure next to a promo markup, with the Precios tab's label
 * "c/ sell in/out". Renders nothing when it is null: the product has neither today.
 * No computation here, only rendering.
 */
export default function SellInOutMarkupExtra({ value, format = formatSellInOutPct, className }) {
  if (!isSellInOutShown(value)) return null;
  return (
    <span className={[styles.sellInOutExtra, className].filter(Boolean).join(' ')} title={TITLE}>
      <span className={styles.sellInOutLabel}>{SELL_IN_OUT_LABEL}</span> {format(value)}
    </span>
  );
}
