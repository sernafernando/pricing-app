import PublicationCell from './PublicationCell';
import PublicationStatusPill from './PublicationStatusPill';
import PriceCell from './PriceCell';
import StockCell from './StockCell';
import LinkBadge from './LinkBadge';
import LastEventCell from './LastEventCell';
import ActivityCell from './ActivityCell';
import StoreCell from './StoreCell';

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
};

/** `eventsEnabled` false drops the last-event column altogether (S56.2). */
export function buildColumns({ eventsEnabled }) {
  const columns = [
    { key: 'titulo', header: 'Publicación', width: 340, sortable: true, render: (item) => <PublicationCell item={item} /> },
    {
      key: 'estado',
      header: 'Estado',
      width: 120,
      render: (item) => <PublicationStatusPill status={item.status} gone={item.gone} subStatus={item.sub_status} />,
    },
    { key: 'precio', header: 'Precio', width: 160, sortable: true, align: 'right', render: (item) => <PriceCell price={item.price} /> },
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
