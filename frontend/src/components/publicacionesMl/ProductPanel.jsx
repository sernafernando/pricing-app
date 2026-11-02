import { useRef, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { CopyButton } from '../kit';
import { usePermisos } from '../../contexts/PermisosContext';
import ProductoMLAsPanel from '../promociones/ProductoMLAsPanel';
import ProductPrices from '../pricing/ProductPrices';
import ListPriceGroup from './panel/ListPriceGroup';
import { canViewProductPrices, pricePermissions } from '../pricing/productPricePermissions';
import { buildColumns } from './columns';
import { PRODUCT_FIGURES } from './productFigures';
import { describeLoadError } from './loadErrors';
import MarkupCell from './MarkupCell';
import { UnitsCell } from './MetricsCells';
import PublicationStatusPill from './PublicationStatusPill';
import PanelShell from './panel/PanelShell';
import PanelTabs from './panel/PanelTabs';
import ProductBanAction from './panel/ProductBanAction';
import ProductCatalogCompetition from './panel/ProductCatalogCompetition';
import ProductChangesTab from './panel/ProductChangesTab';
import ProductCuotasConfig from './panel/ProductCuotasConfig';
import ProductIdentity from './panel/ProductIdentity';
import ProductPrearmadas from './panel/ProductPrearmadas';
import ProductPurchases from './panel/ProductPurchases';
import SellInLotes from '../sellIn/SellInLotes';
import ProductPxq from './panel/ProductPxq';
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

const publicationsLabel = (n) => `${n} ${n === 1 ? 'publicación' : 'publicaciones'}`;

/**
 * The page's filters the publication tree understands, as Productos hands them to it (`filtroPromoTipos`,
 * `filtroPromoEstado`, `filtroTiendaOficial`, `filtroPxq`). The stores go in the URL's vocabulary (`sin_tienda`), which
 * is the tree endpoint's too. The tree knows no other filter: it marks the publications these leave out (behind
 * "ver todos") and shows the rest, whatever the page's other filters say.
 */
const NO_PROMO_TYPES = [];
const treeFilters = (filters) => ({
  promoTipos: filters.promo_tipos ?? NO_PROMO_TYPES,
  promoEstado: filters.promo_estado || undefined,
  tiendaOficial: filters.tiendas?.length > 0 ? filters.tiendas.join(',') : undefined,
  conPxq: filters.pxq === 'con_pxq',
});

const RESUMEN = { key: 'resumen', label: 'Resumen' };
const PRECIOS = { key: 'precios', label: 'Precios' };
const CAMBIOS = { key: 'cambios', label: 'Cambios' };

/**
 * The panel of one product of the Producto view, beside the table: the product (its code, brand, prearmadas badge
 * and publication count), the sum of its publications' Métricas ML figures under the page's filters, and those
 * publications: a product's as Productos' publication tree (`ProductoMLAsPanel`: familias, catálogo, vinculadas and
 * promos, with its own controls, each publication opening its own panel from its "Abrir" button), under the page's
 * promo, store and wholesale filters (`treeFilters`); the "Sin producto" row's, having no product to read a tree of,
 * as a list, each one opening its own panel (`onSelectItem`).
 * The prearmadas badge is the one Productos shows
 * (`ProductPrearmadas`, `produccion.ver_prearmadas_stats`). The "Sin producto" row (`productKey` '0') has no code
 * or brand, only its figures and publications.
 *
 * The figures are the columns of the list (`buildColumns`) a product row draws, so the permissions hide exactly
 * what ProductoTable hides: nothing without `canSeeSales`, no markup or Total Gauss without `canSeeMargin`.
 *
 * Those go under the Resumen tab, after the product's SKU and EAN (`ProductIdentity`, editable with
 * `ml_publicaciones.editar_producto`), its last purchases (`ProductPurchases`, `productos.ver_info_compras`) and its
 * sell-in lots in FIFO order (`SellInLotes`, hidden when the API refuses it), and
 * after the publications comes the catalog competition of those in a catalog (`ProductCatalogCompetition`,
 * `promos.ver`) and the wholesale prices of each (`ProductPxq`, `pxq.ver`), for "Sin producto" too since both belong
 * to each publication, and last the product's ban (`ProductBanAction`, gated by itself).
 * Precios mounts the product's prices (the same `ProductPrices` a publication's Precios tab mounts), and under them
 * its instalment settings (`ProductCuotasConfig`, whose save recalculates the instalments: the prices are read
 * again and the list reloaded), for whoever may see them, and Cambios the changes made to the
 * product in the app, with who made each one (`ProductChangesTab`); "Sin producto" has neither. Opening another
 * product goes back to
 * Resumen. A price write reloads the page's list (`onListReload`).
 *
 * @param {object} props
 * @param {object} props.filters The page's filters.
 * @param {string} props.productKey The product row's `key` (the URL's `prod`).
 * @param {() => void} props.onClose
 * @param {(itemId: string) => void} props.onSelectItem Opens a publication's panel.
 * @param {boolean} [props.canSeeSales] `ml_metricas.ver`.
 * @param {boolean} [props.canSeeMargin] `ml_metricas.ver_ganancia`.
 * @param {() => void} [props.onListReload] Asks the page to reload its list (a price write changes price and markup).
 */
export default function ProductPanel({
  filters,
  productKey,
  onClose,
  onSelectItem,
  canSeeSales = false,
  canSeeMargin = false,
  onListReload,
  priceGroup = null,
}) {
  const { summary, items, loading, error, reload, loadMore, hasMore } = useProductPanel(filters, productKey);
  const { tienePermiso } = usePermisos();
  // The tree's caches, as Productos keeps them: per panel, keyed by product and filters.
  const mlasCacheRef = useRef(new Map());
  const promosCacheRef = useRef(new Map());
  const catalogCompetitionCacheRef = useRef(new Map());
  const pxqCacheRef = useRef(new Map());
  // The open tab belongs to the product it was opened on: another product starts on Resumen.
  const [openTab, setOpenTab] = useState({ productKey, key: RESUMEN.key });
  // Bumped when the instalment settings recalculated the instalments: `ProductPrices` reads its prices again (an open
  // price edit stays as typed).
  const [pricesReadAgain, setPricesReadAgain] = useState(0);
  const onCuotasRecalculated = () => {
    setPricesReadAgain((n) => n + 1);
    onListReload?.();
  };
  const withoutProduct = productKey === NO_PRODUCT_KEY;
  const productItemId = summary?.productoItemId;
  const tabs =
    productItemId == null ? [RESUMEN] : canViewProductPrices(tienePermiso) ? [RESUMEN, PRECIOS, CAMBIOS] : [RESUMEN, CAMBIOS];
  const activeKey = (openTab.productKey === productKey && tabs.find((tab) => tab.key === openTab.key)?.key) || RESUMEN.key;
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
            {productItemId != null && <ProductPrearmadas key={productItemId} productItemId={productItemId} />}
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
        <PanelTabs tabs={tabs} activeKey={activeKey} onTabChange={(key) => setOpenTab({ productKey, key })} label="Secciones del producto">
          {activeKey === CAMBIOS.key ? (
            <ProductChangesTab key={productItemId} productItemId={productItemId} />
          ) : activeKey === PRECIOS.key ? (
            <>
              <ListPriceGroup productItemId={productItemId} canSeeMargin={canSeeMargin} priceGroup={priceGroup} />
              <ProductPrices
                productItemId={productItemId}
                // Read again after the instalment settings or after a list write (the group above): both counters only
                // ever go up, so their sum changes whenever either does.
                readAgain={pricesReadAgain + (priceGroup?.version ?? 0)}
                permissions={pricePermissions(tienePermiso)}
                onWritten={onListReload}
                showCost={canSeeMargin}
              />
              <ProductCuotasConfig key={productItemId} productItemId={productItemId} onRecalculated={onCuotasRecalculated} />
            </>
          ) : (
            <>
              {productItemId != null && <ProductIdentity key={`identity-${productItemId}`} productItemId={productItemId} publications={items} />}
              {productItemId != null && <ProductPurchases key={`purchases-${productItemId}`} productItemId={productItemId} />}
              {productItemId != null && <SellInLotes key={`lotes-${productItemId}`} productItemId={productItemId} container={Section} />}
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
                {productItemId != null ? (
                  <div className={styles.tree}>
                    <ProductoMLAsPanel
                      itemId={productItemId}
                      mlasCacheRef={mlasCacheRef}
                      promosCacheRef={promosCacheRef}
                      catalogCompetitionCacheRef={catalogCompetitionCacheRef}
                      pxqCacheRef={pxqCacheRef}
                      {...treeFilters(filters)}
                      onOpenPublication={onSelectItem}
                    />
                  </div>
                ) : (
                  <>
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
                  </>
                )}
              </Section>
              <ProductCatalogCompetition key={`catalog-${productKey}`} publications={items} />
              <ProductPxq key={`pxq-${productKey}`} publications={items} />

              {productItemId != null && (
                <ProductBanAction key={`ban-${productItemId}`} productItemId={productItemId} description={summary.label} />
              )}
            </>
          )}
        </PanelTabs>
      )}
    </PanelShell>
  );
}
