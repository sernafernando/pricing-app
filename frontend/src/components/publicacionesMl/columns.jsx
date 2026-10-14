import PublicationCell from './PublicationCell';
import PublicationStatusPill from './PublicationStatusPill';
import PriceCell from './PriceCell';
import StockCell from './StockCell';
import LinkBadge from './LinkBadge';
import LastEventCell from './LastEventCell';
import ActivityCell from './ActivityCell';
import StoreCell from './StoreCell';
import MarkupCell from './MarkupCell';
import { Markup30dCell, Sales30dCell } from './SalesCells';
import VariationsToggle from './VariationsToggle';
import { chainHeader } from '../../utils/metricasMlLevels';
import styles from './cells.module.css';

/**
 * Columns of the Publicaciones ML table (`TableShell` shape). A sortable
 * column's `key` IS the backend's `orden` value, so a header click needs no
 * translation table. `DEFAULT_DIRECTION` mirrors the backend's default per sort.
 */
export const DEFAULT_SORT = 'actividad';

export const DEFAULT_DIRECTION = {
  actividad: 'desc',
  titulo: 'asc',
  precio: 'asc',
  stock_full: 'desc',
  // Worst variation first: the most negative markup on top.
  markup: 'asc',
};

/**
 * Columns hidden until the user turns them on in the picker: when "Markup 30d"
 * is on screen it replaces the worst-variation markup, but that column (and
 * the markup filters and sort that depend on it) stays available. A user who
 * cannot see "Markup 30d" keeps the worst-variation markup visible.
 */
export function defaultColumnVisibility({ canSeeSales = false, canSeeMargin = false } = {}) {
  return canSeeSales && canSeeMargin ? { markup: false } : {};
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
 * `canSeeMargin` (`ml_metricas.ver_ganancia`) is what lets the markup column
 * exist at all: without it there is no column, not a column of dashes.
 * `expandedIds` / `onToggleVariations` drive the expand toggle of publications
 * with more than one variation; without `onToggleVariations` there is none.
 * `agrupado` (the tree view) adds the node figures -- publication count and,
 * with the margin, negatives -- and names the markup column for what a node
 * shows (a range, not the "peor variación" sort); the page makes it unsortable.
 * Its first column names the chain of levels of `dimension`, like Métricas ML.
 * `canSeeSales` (`ml_metricas.ver`) adds "Ventas 30d"; with `canSeeMargin`
 * too, "Markup 30d" -- the real markup of those sales, from Métricas ML.
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
}) {
  const columns = [
    {
      key: 'titulo',
      // The tree goes past Métricas' levels: [familia ›] publicación under each product.
      header: agrupado ? `${chainHeader(dimension)}${familias ? ' › Familia' : ''} › Publicación` : 'Publicación',
      label: 'Publicación',
      width: 340,
      sortable: true,
      render: (item) =>
        onToggleVariations && item.variations_count > 1 ? (
          <div className={styles.withToggle}>
            <VariationsToggle item={item} expanded={expandedIds?.has(item.item_id) ?? false} onToggle={onToggleVariations} />
            <PublicationCell item={item} />
          </div>
        ) : (
          <PublicationCell item={item} />
        ),
    },
    ...(agrupado
      ? [
          { key: 'publicaciones', header: 'Publicaciones', width: 120, align: 'right', render: () => null },
          ...(canSeeMargin ? [{ key: 'negativos', header: 'Negativos', width: 110, align: 'right', render: () => null }] : []),
        ]
      : []),
    {
      key: 'estado',
      header: 'Estado',
      width: 120,
      render: (item) => <PublicationStatusPill status={item.status} gone={item.gone} subStatus={item.sub_status} />,
    },
    { key: 'precio', header: 'Precio', width: 160, sortable: true, align: 'right', render: (item) => <PriceCell price={item.price} /> },
    ...(canSeeMargin
      ? [
          {
            key: 'markup',
            header: agrupado ? (
              'Markup'
            ) : (
              <>
                Markup <span className={styles.sortHint}>peor variación</span>
              </>
            ),
            label: 'Markup',
            width: 170,
            sortable: true,
            align: 'right',
            render: (item) => <MarkupCell markup={item.markup} />,
          },
        ]
      : []),
    ...(canSeeSales
      ? [{ key: 'ventas_30d', header: 'Ventas 30d', width: 140, align: 'right', render: (item) => <Sales30dCell sales={item.sales_30d} /> }]
      : []),
    ...(canSeeSales && canSeeMargin
      ? [{ key: 'markup_30d', header: 'Markup 30d', width: 120, align: 'right', render: (item) => <Markup30dCell sales={item.sales_30d} /> }]
      : []),
    { key: 'stock_full', header: 'Stock', width: 140, sortable: true, align: 'right', render: (item) => <StockCell stock={item.stock} /> },
    { key: 'vinculo', header: 'Vínculo', width: 170, render: (item) => <LinkBadge link={item.link} /> },
    { key: 'tienda', header: 'Tienda', width: 140, render: (item) => <StoreCell item={item} /> },
    { key: 'actividad', header: 'Última actividad', width: 150, sortable: true, render: (item) => <ActivityCell item={item} /> },
  ];
  if (eventsEnabled) {
    columns.push({ key: 'evento', header: 'Último evento', width: 200, render: (item) => <LastEventCell event={item.last_event} /> });
  }
  return columns;
}
