import { formatAmount } from '../../utils/ventasMlFormat';
import PrecioTransfHint from '../PrecioTransfHint';
import { tnShownPrice } from './tnPrice';
import styles from './cells.module.css';

/**
 * The product's Tienda Nube price over the web transfer, as Productos' Web Transf. cell (S3): the promotional price
 * when a promotion is on, with the regular one struck through, else the regular price; each with its transfer price
 * (`PrecioTransfHint`, the card surcharge `percent` taken off; nothing without it). Nothing without a TN price.
 * `label` names it where no column header does (a panel's web transfer row).
 */
export default function TnPriceLine({ product, percent, label = null }) {
  const shown = tnShownPrice(product);
  if (!shown) return null;
  // Under a promotion the regular price is struck through.
  const promo = Boolean(product.tn_has_promotion && Number(product.tn_promotional_price) > 0);
  return (
    <div className={styles.tnPrice} data-tn-price="">
      <div className={styles.tnAmount}>
        {label && <span className={styles.tnLabel}>{label}</span>}
        <span className={styles.tnFigure}>$ {formatAmount(shown)}</span>
        <PrecioTransfHint precioTarjeta={shown} porcentaje={percent} className={styles.tnHint} />
      </div>
      {promo && Number(product.tn_price) > 0 && <s className={`${styles.tnRegular} ${styles.tnFigure}`}>$ {formatAmount(product.tn_price)}</s>}
    </div>
  );
}
