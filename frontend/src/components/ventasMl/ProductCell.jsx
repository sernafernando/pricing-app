import { Package } from 'lucide-react';
import { getCategoryIcon } from '../../utils/categoryIcon';
import styles from './ProductCell.module.css';

/**
 * ProductCell — ventas-ml-rediseno PR14.T5/T6 (LISTING R28, design D13),
 * the product-identity cell unblocked by ventas-ml-producto-listado-pr10b
 * (`OrderItemOpsSummary.items` on `SaleListItem` / `SaleGroup.orders[].items`).
 *
 * `items` is ALWAYS the FULL list of items backing this cell — one order's
 * own items, or every item across a pack's orders when the caller is
 * summarizing a collapsed pack row — never a single flat title/SKU pair.
 * An order (or a pack) can carry more than one item; this component NEVER
 * silently drops the rest: it renders the first item plus an explicit
 * "+N productos" badge, mirroring the approved Stitch mockup
 * (`docs/design/ventas-ml/listado.html`, "+2 productos" badge) rather than
 * inventing a client-side aggregate title.
 *
 * Thumbnails are a PLACEHOLDER by product decision — real images arrive
 * later with the publicaciones module (see PR14b task description). The
 * placeholder box doubles as the category icon host (`item_category`,
 * LISTING R28), folded in from the PR14 leading `Categoría` column now
 * that this cell exists to hold it (see `VentasML.jsx` for the removal
 * rationale).
 */
export default function ProductCell({ items, category }) {
  const list = items || [];
  const CategoryIcon = getCategoryIcon(category);

  if (list.length === 0) {
    return (
      <div className={styles.cell} data-testid="product-cell-empty">
        {/* Even with no synced item row, `item_category` may already be
            known (PR10.T2) -- the category icon/tooltip must not
            disappear just because the item list hasn't arrived yet. */}
        <div className={styles.thumbnail} title={category || undefined}>
          {category ? (
            <CategoryIcon size={16} aria-hidden="true" role="img" aria-label={category} />
          ) : (
            <Package size={16} aria-hidden="true" />
          )}
        </div>
        <div className={styles.info}>
          <span className={styles.emptyText}>Sin datos de producto</span>
        </div>
      </div>
    );
  }

  const [primary, ...rest] = list;
  const extraCount = rest.length;
  const title = primary.title || '(sin título)';

  const metaParts = [];
  if (primary.seller_sku) metaParts.push(`SKU ${primary.seller_sku}`);
  metaParts.push(primary.item_id);
  if (primary.quantity != null) metaParts.push(`x${primary.quantity}`);

  return (
    <div className={styles.cell}>
      <div className={styles.thumbnail} title={category || undefined}>
        <CategoryIcon size={16} aria-hidden="true" role="img" aria-label={category || 'Sin categoría'} />
      </div>
      <div className={styles.info}>
        <span className={`${styles.title} ${!primary.title ? styles.titleEmpty : ''}`} title={title}>
          {title}
        </span>
        <span className={styles.meta}>{metaParts.join(' · ')}</span>
        {extraCount > 0 && (
          <span className={styles.extraBadge}>
            +{extraCount} producto{extraCount === 1 ? '' : 's'}
          </span>
        )}
      </div>
    </div>
  );
}
