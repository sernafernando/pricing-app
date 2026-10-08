import PublicationCell from './PublicationCell';
import PublicationStatusPill from './PublicationStatusPill';
import PriceCell from './PriceCell';
import StockCell from './StockCell';
import LinkBadge from './LinkBadge';
import LastEventCell from './LastEventCell';
import ActivityCell from './ActivityCell';
import StoreCell from './StoreCell';
import MarkupCell from './MarkupCell';
import VariationsToggle from './VariationsToggle';
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
 * `eventsEnabled` false drops the last-event column altogether (S56.2).
 * `canSeeMargin` (`ml_metricas.ver_ganancia`) is what lets the markup column
 * exist at all: without it there is no column, not a column of dashes.
 * `expandedIds` / `onToggleVariations` drive the expand toggle of publications
 * with more than one variation; without `onToggleVariations` there is none.
 */
export function buildColumns({ eventsEnabled, canSeeMargin = false, expandedIds, onToggleVariations }) {
  const columns = [
    {
      key: 'titulo',
      header: 'Publicación',
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
            header: (
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
