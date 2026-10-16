import { formatAmount } from '../../utils/ventasMlFormat';
import { markupTone } from '../../utils/ventasMlTone';
import { isBlank } from './priceFormat';
import styles from './ProductPrices.module.css';

export const Empty = () => <span className={styles.empty}>—</span>;

/**
 * A markup painted by the app's markup scale (`markupTone`: negative, low
 * under 6%, good), the same cut points as the Métricas and Publicaciones ML
 * markups. Unknown is "—" with no colour, never 0.
 */
export function MarkupChip({ value }) {
  if (isBlank(value)) return <Empty />;
  return (
    <span className={styles.chip} data-tone={markupTone(value) ?? undefined}>
      {formatAmount(value)}%
    </span>
  );
}
