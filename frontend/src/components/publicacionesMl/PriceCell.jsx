import { formatAmount } from '../../utils/ventasMlFormat';
import { publicationListLabel } from '../../constants/mlPublicationTypes';
import styles from './cells.module.css';

/**
 * Price of a publication. `amount` is what the buyer pays; `regular_amount`
 * (struck through) is shown only when there is a promotion under it. The
 * `productos_fallback` source means ML gave no price and the figure is the one
 * from Productos, so it says so. Under the amount: ERP list type from
 * `publicaciones_ml` (`lista_nombre` / `pricelist_id`), never `listing_type_id`.
 * Null amount -> "—", never 0.
 */
export default function PriceCell({ price }) {
  if (price?.amount == null) return <span className={styles.empty}>—</span>;
  const hasRegular = price.regular_amount != null && Number(price.regular_amount) !== Number(price.amount);
  const promotion = [price.promotion_type, price.campaign].filter(Boolean).join(' · ');
  const listLabel = publicationListLabel(price);
  return (
    <div className={`${styles.stack} ${styles.stackEnd}`}>
      <span className={styles.amount}>{formatAmount(price.amount)}</span>
      {listLabel && <span className={styles.note}>{listLabel}</span>}
      {hasRegular && <span className={styles.regular}>{formatAmount(price.regular_amount)}</span>}
      {promotion && <span className={styles.note}>{promotion}</span>}
      {price.source === 'productos_fallback' && (
        <span className={styles.badge} title="ML no informó precio: se muestra el de Productos">
          precio de Productos
        </span>
      )}
    </div>
  );
}
