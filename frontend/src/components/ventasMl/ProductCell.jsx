import { CornerDownRight, Package } from 'lucide-react';
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
 * NEVER TRUNCATED TO NOTHING. The title used to sit in a one-line ellipsis
 * capped at 240px, so widening the column showed the same eight words:
 * the content did not depend on the column, it ignored it. Now the title
 * wraps (up to two lines, clamped -- the full text stays in `title`) and the
 * SKU · MLA · xN line wraps instead of clipping, so the cell grows with the
 * column and still says everything at its narrowest.
 *
 * `variant="member"` is the indented sub-row inside an opened pack: no
 * thumbnail, a "↳" lead, title and meta on one flowing line (design
 * `listado.html`, "Pack Sub-row").
 *
 * Thumbnails are a PLACEHOLDER by product decision — real images arrive
 * later with the publicaciones module. The placeholder box doubles as the
 * category icon host (`item_category`, LISTING R28).
 */
export default function ProductCell({ items, category, variant = 'row', isPack = false }) {
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
            <CategoryIcon size={16} role="img" aria-label={category} />
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
  if (primary.item_id) metaParts.push(primary.item_id);
  if (primary.quantity != null) metaParts.push(`x${primary.quantity}`);

  if (variant === 'member') {
    return (
      <div className={styles.memberCell}>
        <CornerDownRight size={14} className={styles.memberLead} aria-hidden="true" />
        <div className={styles.memberInfo}>
          <span className={`${styles.memberTitle} ${!primary.title ? styles.titleEmpty : ''}`} title={title}>
            {title}
          </span>
          <span className={styles.meta}>{metaParts.join(' · ')}</span>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.cell}>
      <div className={`${styles.thumbnail} ${isPack ? styles.thumbnailPack : ''}`} title={category || undefined}>
        {category ? (
          <CategoryIcon size={16} role="img" aria-label={category} />
        ) : (
          // No category to announce: the icon is decorative here, so it stays
          // out of the accessibility tree instead of reading "Sin categoría".
          <CategoryIcon size={16} aria-hidden="true" />
        )}
      </div>
      <div className={styles.info}>
        <span
          className={`${styles.title} ${!primary.title ? styles.titleEmpty : ''}`}
          title={title}
          data-product-title
        >
          {title}
        </span>
        <span className={styles.metaRow}>
          <span className={styles.meta}>{metaParts.join(' · ')}</span>
          {extraCount > 0 && (
            <span className={styles.extraBadge}>
              +{extraCount} producto{extraCount === 1 ? '' : 's'}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}
