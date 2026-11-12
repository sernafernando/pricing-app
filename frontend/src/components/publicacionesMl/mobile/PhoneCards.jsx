import MarkupCell from '../MarkupCell';
import PublicationStatusPill from '../PublicationStatusPill';
import { listingKindLabel } from '../listingKindLabels';
import { AgeingCell, MarkupRealCell, StockQuantity, UnitsCell } from '../MetricsCells';
import { formatUnits } from '../../../utils/metricasMlFormat';
import styles from './PhoneCards.module.css';

/**
 * The phone layout's rows (mobile-metricas-pubml S2, S4): one card per publication, or per product in the Producto
 * view. Same figures and formatters as the table's cells, never a price: a tap opens the panel full screen.
 */

function Figure({ label, children }) {
  return (
    <span className={styles.figure}>
      <span className={styles.figureLabel}>{label}</span>
      <span className={styles.figureValue}>{children}</span>
    </span>
  );
}

function Meta({ parts, children }) {
  return (
    <span className={styles.meta}>
      {parts.filter(Boolean).map((part, index) => (
        <span key={part} className={styles.metaPart} data-separated={index > 0 || undefined}>
          {part}
        </span>
      ))}
      {children}
    </span>
  );
}

/** A publication: thumbnail, title, MLA · tipo · tienda and its state; Ventas 30D, Markup, Stock (+ Full), Ageing. */
export function PublicationCard({ item, canSeeSales, canSeeMargin, selected = false, onSelect }) {
  const full = item.stock?.full;
  return (
    <button type="button" className={styles.card} aria-current={selected || undefined} onClick={() => onSelect(item)}>
      <span className={styles.top}>
        <span className={styles.thumbnail} aria-hidden="true">
          {item.thumbnail && <img src={item.thumbnail} alt="" loading="lazy" className={styles.image} />}
        </span>
        <span className={styles.identity}>
          <span className={styles.title}>{item.title ?? 'Sin título'}</span>
          <Meta parts={[item.item_id, listingKindLabel(item.listing_kind), item.store_label]}>
            <PublicationStatusPill status={item.status} gone={item.gone} subStatus={item.sub_status} />
          </Meta>
        </span>
      </span>
      <span className={styles.figures}>
        {canSeeSales && (
          <Figure label="Ventas 30D">
            <UnitsCell value={item.metrics?.units_30d} strong />
          </Figure>
        )}
        {canSeeMargin && (
          <Figure label="Markup">
            <MarkupCell markup={item.markup} />
          </Figure>
        )}
        <Figure label="Stock">
          <StockQuantity value={item.erp_stock?.quantity ?? null} />
          {full != null && <span className={styles.figureNote}>Full {formatUnits(full)}</span>}
        </Figure>
        {canSeeSales && (
          <Figure label="Ageing">
            <AgeingCell metrics={item.metrics} />
          </Figure>
        )}
      </span>
      {item.variations_count > 1 && <span className={styles.variations}>{item.variations_count} variaciones</span>}
    </button>
  );
}

/** A product of the Producto view: name, código · marca · publicaciones; Ventas 30D, Markup 30D, Stock, Ageing. */
export function ProductCard({ node, canSeeSales, canSeeMargin, selected = false, onSelect }) {
  const count = `${formatUnits(node.count)} ${node.count === 1 ? 'publicación' : 'publicaciones'}`;
  return (
    <button type="button" className={styles.card} aria-current={selected || undefined} onClick={() => onSelect(node.key)}>
      <span className={styles.identity}>
        <span className={styles.title}>{node.label}</span>
        <Meta parts={[node.codigo, node.marca, count]} />
      </span>
      <span className={styles.figures}>
        {canSeeSales && (
          <Figure label="Ventas 30D">
            <UnitsCell value={node.metrics?.units_30d} strong />
          </Figure>
        )}
        {canSeeSales && canSeeMargin && (
          <Figure label="Markup">
            <MarkupRealCell metrics={node.metrics} />
          </Figure>
        )}
        <Figure label="Stock">
          <StockQuantity value={node.stock} />
        </Figure>
        {canSeeSales && (
          <Figure label="Ageing">
            <AgeingCell metrics={node.metrics} />
          </Figure>
        )}
      </span>
    </button>
  );
}
