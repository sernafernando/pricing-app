import PublicationCell from './PublicationCell';
import PublicationStatusPill from './PublicationStatusPill';
import PriceCell from './PriceCell';
import ErpStockCell from './ErpStockCell';
import LinkBadge from './LinkBadge';
import SkuDivergenceCell from './SkuDivergenceCell';
import LastEventCell from './LastEventCell';
import ActivityCell from './ActivityCell';
import StoreCell from './StoreCell';
import MarkupCell from './MarkupCell';
import PppLine from '../PppLine';
import SellInOutLine from '../SellInOutLine';
import {
  AgeingCell,
  FullStockCell,
  GrossCell,
  LastSaleCell,
  MarkupRealCell,
  MarkupTrendCell,
  OwnStockCell,
  TotalGaussCell,
  UnitsCell,
  UnitsTrendCell,
} from './MetricsCells';
import VariationsToggle from './VariationsToggle';
import { COLUMN_GROUPS } from '../metricasMl/metricasMlColumns';
import { formatAmount } from '../../utils/ventasMlFormat';
import { chainHeader } from '../../utils/metricasMlLevels';
import styles from './cells.module.css';

/**
 * Columns of the Publicaciones ML table (`TableShell` shape), grouped like
 * Métricas ML's board (owner-approved layout). A sortable column's `key` IS
 * the backend's `orden` value, so a header click needs no translation table;
 * Métricas' figures sort the whole filtered set, like Métricas does.
 * The sorts' default directions live with the list's params
 * (`hooks/usePublicacionesMLFilters` `DEFAULT_DIRECTION`). `label` is the
 * name the column picker shows when the header alone (7D, Tendencia...) only
 * makes sense under its group.
 */

// Métricas' own group names: the same figures read under the same headings on both screens.
const groupOf = (id) => COLUMN_GROUPS.find((group) => group.id === id).label;
const VENTAS = groupOf('ventas');
const MARKUP = groupOf('markup');
const RESULTADO = groupOf('resultado');
const ROTACION = groupOf('rotacion');
const STOCK = 'Stock';

const dash = <span className={styles.empty}>—</span>;
const orDash = (value) => (value ? value : dash);
// The cost in its own currency, as the panel's "Costo" reads it; the sort compares it in pesos.
const costText = (costo) => (costo?.amount == null ? dash : `${costo.currency ?? ''} ${formatAmount(costo.amount)}`.trim());
// Under a cost, the PPP and the cost with sell in, as Productos' cost cell draws them (`ppp` and `sell_in_out` come
// next to `costo`, only with ver_ganancia; a row without them, or without a cost, is the cost alone).
const costCell = (item) => {
  if (item.ppp === undefined || item.costo?.amount == null) return costText(item.costo);
  return (
    <div className={`${styles.stack} ${styles.stackEnd} ${styles.costLines}`}>
      <span>{costText(item.costo)}</span>
      <PppLine ppp={item.ppp} />
      <SellInOutLine sellInOut={item.sell_in_out} />
    </div>
  );
};

/**
 * Columns hidden until the user turns them on in the picker: the store and the
 * link now sit inside the Publicación cell, and the activity and the last
 * event are in the panel. The product's code, brand and cost are there to sort
 * by, as in Productos.
 */
export function defaultColumnVisibility() {
  return { codigo: false, marca: false, costo: false, vinculo: false, tienda: false, actividad: false, evento: false };
}

/**
 * The entries of `visibility` that differ from `defaults` (a column missing
 * from either is visible): the user's own picks, kept apart so the default
 * can still follow permissions that load or change later.
 */
export function columnChoicesOver(visibility, defaults) {
  return Object.fromEntries(
    Object.entries(visibility).filter(([key, visible]) => visible !== (defaults[key] ?? true)),
  );
}

/**
 * `eventsEnabled` false drops the last-event column altogether (S56.2).
 * `canSeeSales` (`ml_metricas.ver`) adds Métricas ML's figures of each
 * publication (`row.metrics`): VENTAS, RESULTADO's Facturado and ROTACIÓN.
 * `canSeeMargin` (`ml_metricas.ver_ganancia`) adds MARKUP's Actual -- the
 * markup at today's price, the worst variation (what its sort and filters
 * use) -- and, with `canSeeSales` too, the real 30-day markup, its trend and
 * Total Gauss. Without a permission there is no column, not a column of dashes.
 * STOCK is three figures from three sources, never summed: our own and Full
 * (ML) and the ERP's.
 * `expandedIds` / `onToggleVariations` drive the expand toggle of publications
 * with more than one variation; without `onToggleVariations` there is none.
 * `agrupado` (the tree view) adds the node figures -- publication count and,
 * with the margin, negatives; the page makes the tree unsortable.
 * Its first column names the chain of levels of `dimension`, like Métricas ML.
 * `producto` (the Producto view) adds the products' publication count and
 * names the first column "Producto › Publicación".
 * `skuDivergence` (the `sku_divergente` link filter is on) adds, right after
 * Publicación, the publication's SKU next to the product it names and the
 * linked product (`SkuDivergenceCell`).
 */
export function buildColumns({
  eventsEnabled,
  canSeeMargin = false,
  canSeeSales = false,
  expandedIds,
  onToggleVariations,
  agrupado = false,
  dimension = 'marca',
  familias = false,
  producto = false,
  skuDivergence = false,
}) {
  const withSales = (columns) => (canSeeSales ? columns : []);
  const withMargin = (columns) => (canSeeMargin ? columns : []);
  const columns = [
    {
      key: 'titulo',
      // The tree goes past Métricas' levels: [familia ›] publicación under each product.
      header: agrupado
        ? `${chainHeader(dimension)}${familias ? ' › Familia' : ''} › Publicación`
        : producto
          ? 'Producto › Publicación'
          : 'Publicación',
      label: 'Publicación',
      width: 360,
      sortable: true,
      // `after` (the product checkbox, when selecting) goes after the variations toggle: the toggle leads the
      // pinned cell at the row's depth, where the variations' sub-rows and state row line up one level in.
      render: (item, after = null) =>
        onToggleVariations && item.variations_count > 1 ? (
          <div className={styles.withToggle}>
            <VariationsToggle item={item} expanded={expandedIds?.has(item.item_id) ?? false} onToggle={onToggleVariations} />
            {after}
            <PublicationCell item={item} />
          </div>
        ) : after ? (
          <div className={styles.withToggle}>
            {after}
            <PublicationCell item={item} />
          </div>
        ) : (
          <PublicationCell item={item} />
        ),
    },
    ...(skuDivergence
      ? [{ key: 'sku_divergencia', header: 'SKU distinto', width: 260, render: (item) => <SkuDivergenceCell item={item} /> }]
      : []),
    ...(agrupado || producto
      ? [{ key: 'publicaciones', header: 'Publicaciones', width: 120, align: 'right', render: () => null }]
      : []),
    ...(agrupado ? withMargin([{ key: 'negativos', header: 'Negativos', width: 110, align: 'right', render: () => null }]) : []),
    {
      key: 'estado',
      header: 'Estado',
      width: 120,
      render: (item) => <PublicationStatusPill status={item.status} gone={item.gone} subStatus={item.sub_status} />,
    },
    { key: 'precio', header: 'Precio', width: 150, sortable: true, align: 'right', render: (item) => <PriceCell price={item.price} /> },
    ...withSales([
      {
        key: 'unidades_7d',
        group: VENTAS,
        header: '7D',
        label: 'Ventas 7D',
        width: 70,
        sortable: true,
        align: 'right',
        render: (item) => <UnitsCell value={item.metrics?.units_7d} />,
      },
      {
        key: 'unidades_30d',
        group: VENTAS,
        header: '30D',
        label: 'Ventas 30D',
        width: 80,
        sortable: true,
        align: 'right',
        render: (item) => <UnitsCell value={item.metrics?.units_30d} strong />,
      },
      {
        key: 'units_trend',
        group: VENTAS,
        header: 'Tendencia',
        label: 'Tendencia de ventas',
        width: 120,
        align: 'center',
        render: (item) => <UnitsTrendCell metrics={item.metrics} />,
      },
    ]),
    ...withMargin([
      {
        key: 'markup',
        group: MARKUP,
        header: 'Actual',
        label: 'Markup actual',
        width: 150,
        sortable: true,
        align: 'right',
        render: (item) => <MarkupCell markup={item.markup} />,
      },
      ...withSales([
        {
          key: 'markup_30d',
          group: MARKUP,
          header: 'Real 30D',
          label: 'Markup real 30D',
          width: 100,
          sortable: true,
          align: 'right',
          render: (item) => <MarkupRealCell metrics={item.metrics} />,
        },
        {
          key: 'markup_trend',
          group: MARKUP,
          header: 'Tendencia',
          label: 'Tendencia de markup',
          width: 140,
          align: 'center',
          render: (item) => <MarkupTrendCell metrics={item.metrics} />,
        },
      ]),
    ]),
    ...withSales([
      {
        key: 'facturado_30d',
        group: RESULTADO,
        header: 'Facturado 30D',
        width: 170,
        sortable: true,
        align: 'right',
        render: (item) => <GrossCell metrics={item.metrics} />,
      },
      ...withMargin([
        {
          key: 'total_gauss_30d',
          group: RESULTADO,
          header: 'Total Gauss 30D',
          width: 170,
          sortable: true,
          align: 'right',
          render: (item) => <TotalGaussCell metrics={item.metrics} />,
        },
      ]),
      { key: 'last_sale', group: ROTACION, header: 'Última venta', width: 120, render: (item) => <LastSaleCell metrics={item.metrics} /> },
      { key: 'ageing', group: ROTACION, header: 'Ageing', width: 90, align: 'center', render: (item) => <AgeingCell metrics={item.metrics} /> },
    ]),
    // ML's own stock and Full stock, and the ERP's: three sources, never one sum.
    {
      key: 'stock_propio',
      group: STOCK,
      header: 'Propio',
      label: 'Stock propio',
      width: 90,
      sortable: true,
      align: 'right',
      render: (item) => <OwnStockCell stock={item.stock} />,
    },
    {
      key: 'stock_full',
      group: STOCK,
      header: 'Full',
      label: 'Stock Full',
      width: 80,
      sortable: true,
      align: 'right',
      render: (item) => <FullStockCell stock={item.stock} />,
    },
    {
      key: 'stock_erp',
      group: STOCK,
      header: 'ERP',
      label: 'Stock ERP',
      width: 120,
      sortable: true,
      align: 'right',
      render: (item) => <ErpStockCell erpStock={item.erp_stock} />,
    },
    // Hidden by default (`defaultColumnVisibility`): the picker brings them back.
    { key: 'codigo', header: 'Código', width: 130, sortable: true, render: (item) => orDash(item.link?.codigo) },
    { key: 'marca', header: 'Marca', width: 130, sortable: true, render: (item) => orDash(item.link?.marca) },
    ...withMargin([
      { key: 'costo', header: 'Costo', width: 130, sortable: true, align: 'right', render: costCell },
    ]),
    { key: 'vinculo', header: 'Vínculo', width: 170, render: (item) => <LinkBadge link={item.link} /> },
    { key: 'tienda', header: 'Tienda', width: 140, render: (item) => <StoreCell item={item} /> },
    { key: 'actividad', header: 'Última actividad', width: 150, sortable: true, render: (item) => <ActivityCell item={item} /> },
  ];
  if (eventsEnabled) {
    columns.push({ key: 'evento', header: 'Último evento', width: 200, render: (item) => <LastEventCell event={item.last_event} /> });
  }
  return columns;
}
