import { formatAmount } from '../../utils/ventasMlFormat';
import PrecioTransfHint from '../PrecioTransfHint';
import { tnShownPrice } from './tnPrice';
import styles from './cells.module.css';

/**
 * The product's Tienda Nube price over the web transfer, as Productos' Web Transf. cell (S3): the promotional price
 * when a promotion is on, with the regular one struck through, else the regular price; each with its transfer price
 * (`PrecioTransfHint`, the card surcharge `percent` taken off; nothing without it). Nothing without a TN price.
 */
export default function TnPriceLine({ product, percent }) {
  const shown = tnShownPrice(product);
  if (!shown) return null;
  // Under a promotion the regular price is struck through.
  const promo = Boolean(product.tn_has_promotion && product.tn_promotional_price);
  return (
    <div className={styles.tnPrice} data-tn-price="">
      <div className={styles.tnAmount}>
        <span>$ {formatAmount(shown)}</span>
        <PrecioTransfHint precioTarjeta={shown} porcentaje={percent} className={styles.tnHint} />
      </div>
      {promo && Number(product.tn_price) > 0 && <s className={styles.tnRegular}>$ {formatAmount(product.tn_price)}</s>}
    </div>
  );
}
