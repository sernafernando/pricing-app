import { Lock } from 'lucide-react';
import { formatAmount } from '../../utils/ventasMlFormat';
import { formatPct } from '../../utils/metricasMlFormat';
import { costoConOffset, markupConOffset, requiereTipoCambio } from '../../utils/offsetsGanancia';
import styles from './cells.module.css';

/**
 * Productos' "markup con offsets": `markup` (percent) over the cost the `offsets` discount, or null while they load,
 * when none reaches the product, or when the cost needs a USD rate there is not.
 */
function markupWithOffsets(product, markup, offsets) {
  if (!offsets) return null;
  const needsRate = requiereTipoCambio(product, offsets);
  if (needsRate && !offsets.tipoCambio) return null;
  return markupConOffset(markup, costoConOffset(product, { ...offsets, tipoCambio: needsRate ? offsets.tipoCambio : null }));
}

/**
 * One of Productos' prices of a row's product (`column`: its `price` and `markup` fields, and `takesPart`, the flag
 * without which Productos shows no price). The markup only with `canSeeMargin`. No product reads "—" ("…" while
 * its prices are on their way), and so does a price that is not there: never 0. `markupScale` turns the markup the
 * listing sends into a percentage (the best offer's comes as a fraction). A failed request (`failed`) reads
 * "sin datos", never "—", so it is not taken for a product with no price. `column.details(product)`, when the
 * column has it, lists lines drawn under the price (the best offer's, as Productos).
 *
 * `offsets` (the clásica column only, `useListOffsets`) adds Productos' "markup con offsets" under the markup: the
 * same net price over the cost the offsets discount. None while they load, when none reaches the product, or when
 * the cost needs a USD rate there is not.
 */
export default function ListPriceCell({ product, column, loading, failed, canSeeMargin, offsets = null }) {
  if (failed) {
    return (
      <span className={styles.empty} title="No se pudieron cargar los precios de Productos">
        sin datos
      </span>
    );
  }
  if (!product) return <span className={styles.empty}>{loading ? '…' : '—'}</span>;
  const amount = product[column.price];
  if (amount == null || Number(amount) <= 0 || (column.takesPart && !product[column.takesPart])) {
    return <span className={styles.empty}>—</span>;
  }
  const raw = product[column.markup];
  const markup = raw == null ? null : Number(raw) * column.markupScale;
  const withOffsets = canSeeMargin && markup != null ? markupWithOffsets(product, markup, offsets) : null;
  return (
    <div className={`${styles.stack} ${styles.stackEnd}`}>
      <span className={styles.amount}>{formatAmount(amount)}</span>
      {canSeeMargin && markup != null && (
        <span className={styles.markup} data-negative={Number(markup) < 0 ? '' : undefined}>
          {formatPct(markup)}
        </span>
      )}
      {withOffsets != null && (
        <span className={styles.markupOffset} title="Markup con offsets aplicados" data-negative={withOffsets < 0 ? '' : undefined}>
          → {formatPct(withOffsets)}
        </span>
      )}
      {column.details?.(product).map((line, index, lines) => (
        <span key={line} className={styles.priceDetail} data-price-detail="">
          {line}
          {index === lines.length - 1 && column.locked?.(product) && (
            <Lock size={10} className={styles.detailLock} role="img" aria-label="% conservado en cambios masivos" />
          )}
        </span>
      ))}
    </div>
  );
}
