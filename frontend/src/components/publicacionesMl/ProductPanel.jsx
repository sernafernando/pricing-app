import { ChevronRight } from 'lucide-react';
import { CopyButton } from '../kit';
import { buildColumns } from './columns';
import { describeLoadError } from './loadErrors';
import MarkupCell from './MarkupCell';
import { UnitsCell } from './MetricsCells';
import PublicationStatusPill from './PublicationStatusPill';
import PanelShell from './panel/PanelShell';
import { Field, Fields, Section } from './panel/PanelParts';
import { amount, count } from './panel/format';
import useProductPanel, { NO_PRODUCT_KEY } from './panel/useProductPanel';
import panelStyles from './panel/panel.module.css';
import styles from './ProductPanel.module.css';

/** What to tell the operator when the product cannot be loaded. */
const describeError = (error) =>
  describeLoadError(error, {
    notFound: 'El producto ya no existe.',
    forbidden: 'No tiene permiso para ver este producto.',
    fallback: 'No se pudo cargar el producto.',
  });

// The columns whose cell reads only `metrics`: the same ones a product row of ProductoTable draws.
const PRODUCT_FIGURES = new Set([
  'unidades_7d',
  'unidades_30d',
  'units_trend',
  'markup_30d',
  'markup_trend',
  'facturado_30d',
  'total_gauss_30d',
  'last_sale',
  'ageing',
]);

const publicationsLabel = (n) => `${n} ${n === 1 ? 'publicación' : 'publicaciones'}`;

/**
 * The panel of one product of the Producto view, beside the table: the product (its code, brand and publication
 * count), the sum of its publications' Métricas ML figures under the page's filters, and those publications, each
 * one opening its own panel (`onSelectItem`). The "Sin producto" row (`productKey` '0') has no code or brand,
 * only its figures and publications.
 *
 * The figures are the columns of the list (`buildColumns`) a product row draws, so the permissions hide exactly
 * what ProductoTable hides: nothing without `canSeeSales`, no markup or Total Gauss without `canSeeMargin`.
 *
 * @param {object} props
 * @param {object} props.filters The page's filters.
 * @param {string} props.productKey The product row's `key` (the URL's `prod`).
 * @param {() => void} props.onClose
 * @param {(itemId: string) => void} props.onSelectItem Opens a publication's panel.
 * @param {boolean} [props.canSeeSales] `ml_metricas.ver`.
 * @param {boolean} [props.canSeeMargin] `ml_metricas.ver_ganancia`.
 */
export default function ProductPanel({ filters, productKey, onClose, onSelectItem, canSeeSales = false, canSeeMargin = false }) {
  const { summary, items, loading, error, reload, loadMore, hasMore } = useProductPanel(filters, productKey);
  const withoutProduct = productKey === NO_PRODUCT_KEY;
  const figures = buildColumns({ eventsEnabled: false, canSeeSales, canSeeMargin, producto: true }).filter((column) =>
    PRODUCT_FIGURES.has(column.key),
  );

  return (
    <PanelShell
      title={summary?.label ?? (withoutProduct ? 'Sin producto' : 'Producto')}
      meta={
        summary && (
          <div className={panelStyles.meta}>
            {summary.codigo && (
              <>
                <span className={panelStyles.itemId}>{summary.codigo}</span>
                <CopyButton value={summary.codigo} label="Copiar código" compact />
              </>
            )}
            {summary.marca && <span className={styles.brand}>{summary.marca}</span>}
            <span className={styles.count}>{publicationsLabel(summary.count)}</span>
          </div>
        )
      }
      onClose={onClose}
      loading={loading && !summary}
      loadingLabel="Cargando producto"
      error={error ? describeError(error) : null}
      onRetry={reload}
    >
      {!loading && !error && !summary && <p className={`${panelStyles.note} ${styles.empty}`}>Los filtros actuales no incluyen este producto.</p>}

      {summary && (
        <div className={panelStyles.body}>
          {figures.length > 0 && (
            <Section title="Cifras">
              <p className={panelStyles.note}>Con los filtros actuales</p>
              <Fields>
                {figures.map((column) => (
                  <Field key={column.key} label={column.label ?? column.header}>
                    {column.render({ metrics: summary.metrics })}
                  </Field>
                ))}
              </Fields>
            </Section>
          )}

          <Section title="Publicaciones">
            {items.length > 0 && (
              <ul className={styles.items}>
                {items.map((item) => (
                  <li key={item.item_id}>
                    <button type="button" className={styles.item} onClick={() => onSelectItem(item.item_id)}>
                      <span className={styles.itemHead}>
                        <span className={panelStyles.itemId}>{item.item_id}</span>
                        <PublicationStatusPill status={item.status} gone={item.gone} subStatus={item.sub_status} />
                        <ChevronRight size={14} aria-hidden="true" className={styles.chevron} />
                      </span>
                      <span className={styles.itemTitle}>{item.title ?? 'Sin título'}</span>
                      <span className={styles.figures}>
                        <span className={styles.figure}>
                          <span className={styles.figureLabel}>Precio</span>
                          {amount(item.price?.amount) ?? '—'}
                        </span>
                        <span className={styles.figure}>
                          <span className={styles.figureLabel}>Stock</span>
                          {count(item.stock?.available) ?? '—'}
                        </span>
                        {canSeeSales && (
                          <span className={styles.figure}>
                            <span className={styles.figureLabel}>Ventas 30D</span>
                            <UnitsCell value={item.metrics?.units_30d} />
                          </span>
                        )}
                        {canSeeMargin && (
                          <span className={styles.figure}>
                            <span className={styles.figureLabel}>Markup</span>
                            <MarkupCell markup={item.markup} />
                          </span>
                        )}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {loading && <p className={panelStyles.note}>Cargando publicaciones…</p>}
            {!loading && !error && items.length === 0 && (
              <p className={panelStyles.note}>Ninguna publicación coincide con los filtros.</p>
            )}
            {hasMore && !loading && (
              <button type="button" className={`btn-tesla outline sm ${styles.more}`} onClick={loadMore}>
                Ver más
              </button>
            )}
          </Section>
        </div>
      )}
    </PanelShell>
  );
}
