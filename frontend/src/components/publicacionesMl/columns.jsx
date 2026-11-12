import PublicationCell from './PublicationCell';
import PublicationStatusPill from './PublicationStatusPill';
import ListingKindBadge from './ListingKindBadge';
import PriceCell from './PriceCell';
import ErpStockCell from './ErpStockCell';
import LinkBadge from './LinkBadge';
import SkuDivergenceCell from './SkuDivergenceCell';
import LastEventCell from './LastEventCell';
import ActivityCell from './ActivityCell';
import StoreCell from './StoreCell';
import MarkupCell from './MarkupCell';
import CostoCell from '../CostoCell';
import { priceColumns } from './priceColumns';
import {
  AgeingCell,
  FullStockCell,
  GrossCell,
  LastSaleCell,
  MarkupRealCell,
  MarkupTrendCell,
  TotalStockCell,
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
// The cost and its cost with sell in on one line, the PPP and the pesos in its tooltip, as Productos' cost cell
// (S10b; `ppp` and `sell_in_out` come next to `costo`, only with ver_ganancia; a row without them is the cost alone).
const costAmount = (monto, moneda) => `${moneda ?? ''} ${formatAmount(monto)}`.trim();
const costCell = (item) => {
  if (item.ppp === undefined || item.costo?.amount == null) return costText(item.costo);
  return (
    <CostoCell
      monto={item.costo.amount}
      moneda={item.costo.currency}
      ppp={item.ppp}
      sellInOut={item.sell_in_out}
      format={costAmount}
    />
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
 * `agrupado` (the tree view): the page makes the tree unsortable; its first
 * column names the chain of levels of `dimension`, like Métricas ML.
 * `producto` (the Producto view) names the first column "Producto › Publicación".
 * Neither adds a column of its own (S6): a parent row's count and negatives sit
 * in its first cell and its Tipo, Estado and Precio summarize its publications.
 * `skuDivergence` (the `sku_divergente` link filter is on) adds, right after
 * Publicación, the publication's SKU next to the product it names and the
 * linked product (`SkuDivergenceCell`).
 * `prices` (`useListPrices`, only for who sees Productos' prices) adds, right after Precio, Productos' price columns
 * of `priceMode` ('normal' | 'cuotas' | 'pvp', S11); the tree has none. `priceEdit` makes them editable (S11c);
 * `onCalculatePrice` adds Productos' Calcular button (P3c); `priceOffsets` (`useListOffsets`) Productos' "markup con
 * offsets" under the clásica markup; `tnCardPercent`, the Tienda Nube card surcharge for the Web Transf. column's
 * transfer hint (S3).
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
  priceMode = 'normal',
  prices = null,
  priceEdit = null,
  onCalculatePrice = null,
  priceOffsets = null,
  tnCardPercent = null,
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
      // The room the figure columns leave goes here (`fill`); the user can drag it wider or narrower (`resizable`).
      width: 440,
      minWidth: 240,
      fill: true,
      resizable: true,
      resizeLabel: producto ? 'Producto' : 'Publicación',
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
    // No column a level leaves empty (S6): a parent row's publication count (and, Agrupado, its negatives) is its first
    // cell's second line, and its Tipo, Estado and Precio summarize its publications (`NodeCells`).
    // The listing type at a glance, before its state: the list's default order (Clásica, then 3, 6, 9, 12 cuotas).
    // Agrupado's parent rows sum up whole brands and categories in compact badges on one line ("C 33", "3 30", … "12 24";
    // "● 111" per state), so the tree starts Tipo and Estado wide enough to hold them, with room left for a wider fallback font (CI's DejaVu). Producto's rows hold a product's
    // few publications: the list's widths fit them and leave the money columns their room.
    { key: 'tipo', header: 'Tipo', width: agrupado ? 216 : 110, sortable: true, render: (item) => <ListingKindBadge kind={item.listing_kind} /> },
    {
      key: 'estado',
      header: 'Estado',
      width: agrupado ? 128 : 104,
      render: (item) => <PublicationStatusPill status={item.status} gone={item.gone} subStatus={item.sub_status} />,
    },
    { key: 'precio', header: 'Precio', width: 136, sortable: true, align: 'center', fit: true, render: (item) => <PriceCell price={item.price} /> },
    ...(prices && !agrupado
      ? priceColumns(priceMode, { prices, canSeeMargin, edit: priceEdit, onCalculate: onCalculatePrice, offsets: priceOffsets, tnCardPercent })
      : []),
    ...withSales([
      {
        key: 'unidades_7d',
        group: VENTAS,
        header: '7D',
        label: 'Ventas 7D',
        width: 60,
        sortable: true,
        align: 'center',
        fit: true,
        render: (item) => <UnitsCell value={item.metrics?.units_7d} />,
      },
      {
        key: 'unidades_30d',
        group: VENTAS,
        header: '30D',
        label: 'Ventas 30D',
        width: 68,
        sortable: true,
        align: 'center',
        fit: true,
        render: (item) => <UnitsCell value={item.metrics?.units_30d} strong />,
      },
      {
        key: 'units_trend',
        group: VENTAS,
        header: 'Tendencia',
        label: 'Tendencia de ventas',
        width: 112,
        align: 'center',
        fit: true,
        render: (item) => <UnitsTrendCell metrics={item.metrics} />,
      },
    ]),
    ...withMargin([
      {
        key: 'markup',
        group: MARKUP,
        header: 'Actual',
        label: 'Markup actual',
        width: 110,
        sortable: true,
        align: 'center',
        fit: true,
        render: (item) => <MarkupCell markup={item.markup} />,
      },
      ...withSales([
        {
          key: 'markup_30d',
          group: MARKUP,
          header: 'Real 30D',
          label: 'Markup real 30D',
          width: 72,
          sortable: true,
          align: 'center',
          fit: true,
          render: (item) => <MarkupRealCell metrics={item.metrics} />,
        },
        {
          key: 'markup_trend',
          group: MARKUP,
          header: 'Tendencia',
          label: 'Tendencia de markup',
          width: 112,
          align: 'center',
          fit: true,
          render: (item) => <MarkupTrendCell metrics={item.metrics} />,
        },
      ]),
    ]),
    ...withSales([
      {
        key: 'facturado_30d',
        group: RESULTADO,
        header: 'Facturado 30D',
        width: 140,
        sortable: true,
        align: 'center',
        fit: true,
        render: (item) => <GrossCell metrics={item.metrics} />,
      },
      ...withMargin([
        {
          key: 'total_gauss_30d',
          group: RESULTADO,
          header: 'Total Gauss 30D',
          width: 140,
          sortable: true,
          align: 'center',
          fit: true,
          render: (item) => <TotalGaussCell metrics={item.metrics} />,
        },
      ]),
      { key: 'last_sale', group: ROTACION, header: 'Última venta', width: 96, align: 'center', fit: true, render: (item) => <LastSaleCell metrics={item.metrics} /> },
      { key: 'ageing', group: ROTACION, header: 'Ageing', width: 64, align: 'center', fit: true, render: (item) => <AgeingCell metrics={item.metrics} /> },
    ]),
    // The ERP stock, the Full stock and their total. Never ML's published quantity (not a stock) nor its available sum.
    {
      key: 'stock_erp',
      group: STOCK,
      header: 'ERP',
      label: 'Stock ERP',
      width: 68,
      sortable: true,
      align: 'center',
      fit: true,
      render: (item) => <ErpStockCell erpStock={item.erp_stock} />,
    },
    {
      key: 'stock_full',
      group: STOCK,
      header: 'Full',
      label: 'Stock Full',
      width: 60,
      sortable: true,
      align: 'center',
      fit: true,
      render: (item) => <FullStockCell stock={item.stock} />,
    },
    {
      key: 'stock_total',
      group: STOCK,
      header: 'Total',
      label: 'Stock total',
      width: 60,
      sortable: true,
      align: 'center',
      fit: true,
      render: (item) => <TotalStockCell total={item.stock_total} />,
    },
    // Hidden by default (`defaultColumnVisibility`): the picker brings them back.
    { key: 'codigo', header: 'Código', width: 130, sortable: true, render: (item) => orDash(item.link?.codigo) },
    { key: 'marca', header: 'Marca', width: 130, sortable: true, render: (item) => orDash(item.link?.marca) },
    ...withMargin([
      { key: 'costo', header: 'Costo', width: 130, sortable: true, align: 'center', fit: true, render: costCell },
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
