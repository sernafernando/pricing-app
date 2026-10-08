import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useReactTable, getCoreRowModel } from '@tanstack/react-table';
import { FilterX, ShieldAlert } from 'lucide-react';
import { publicacionesMlAPI } from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';
import SearchInput from '../components/SearchInput';
import { ColumnPicker, FacetChips, Pagination, SplitPanelLayout, TableShell } from '../components/kit';
import StateBanner from '../components/publicacionesMl/StateBanner';
import MarkupFilters from '../components/publicacionesMl/MarkupFilters';
import VariationRows from '../components/publicacionesMl/VariationRows';
import { DEFAULT_DIRECTION, DEFAULT_SORT, buildColumns } from '../components/publicacionesMl/columns';
import { buildStoreChips } from '../constants/tiendasOficiales';
import { useTiendasOficiales } from '../hooks/useTiendasOficiales';
import {
  FILTER_KEYS,
  PAGE_SIZE,
  PAGE_SIZES,
  buildItemsParams,
  usePublicacionesMLFilters,
} from '../hooks/usePublicacionesMLFilters';
import { buildMlItemUrl, openInMlPanel } from '../utils/mlSidePanel';
import styles from './PublicacionesML.module.css';

/**
 * Publicaciones ML -- the management screen over every publication
 * (publicaciones-ml-vista P11a, hidden route `/ml-publicaciones`).
 *
 * One request per change (`GET /ml-publications/view/items`) brings the page
 * of rows and the honest-state block; the facet counts ride along ONLY when a
 * filter changed (a page or sort change keeps the last counts). Filters, sort,
 * page and selection live in the URL (`usePublicacionesMLFilters`).
 * Ctrl/Cmd+click opens the publication in Mercado Libre; a plain click selects
 * the row (the detail panel is mounted by a later PR).
 */
// Space the table leaves for what is above and below it (header, filters, pager).
const TABLE_OFFSET = '380px';

const STATUS_OPTIONS = ['active', 'paused', 'closed', 'under_review', 'inactive', 'gone'];
const STATUS_LABELS = {
  active: 'Activas',
  paused: 'Pausadas',
  closed: 'Cerradas',
  under_review: 'En revisión',
  inactive: 'Inactivas',
  gone: 'Eliminadas',
};
const TIPO_OPTIONS = ['clasica', 'premium', 'catalogo', 'full'];
const TIPO_LABELS = { clasica: 'Clásica', premium: 'Premium', catalogo: 'Catálogo', full: 'Full' };
const VINCULO_OPTIONS = ['auto', 'manual', 'sin_producto', 'conflicto', 'no_evaluado'];
const VINCULO_LABELS = {
  auto: 'Automático',
  manual: 'Manual',
  sin_producto: 'Sin producto',
  conflicto: 'Conflicto',
  no_evaluado: 'Sin evaluar',
};
const STOCK_OPTIONS = ['sin_stock', 'full_sin_stock'];
const STOCK_LABELS = { sin_stock: 'Sin stock', full_sin_stock: 'Full sin stock' };

const EMPTY_ROWS = [];

/** What to tell the operator when a request fails (S69.1). */
function describeError(error) {
  const status = error?.response?.status;
  if (status === 503) return 'La consulta tardó demasiado. Probá con filtros más acotados o reintentá.';
  if (status === 403) return 'No tenés permiso para ver las publicaciones.';
  if (status === 422) {
    const detail = error.response.data?.error?.message;
    return detail ? `Filtro inválido: ${detail}` : 'Filtro inválido.';
  }
  return 'No se pudieron cargar las publicaciones.';
}

function ListSkeleton() {
  return (
    <div className={styles.skeleton} role="status" aria-label="Cargando publicaciones" aria-busy="true">
      {Array.from({ length: 8 }, (_, index) => (
        <div key={index} className={styles.skeletonRow} />
      ))}
    </div>
  );
}

export default function PublicacionesML() {
  const { filters, filterKey, setFilters, resetFilters } = usePublicacionesMLFilters();
  const { tiendas, getLabel } = useTiendasOficiales();
  const { tienePermiso } = usePermisos();
  // The markup column, filters and sort exist only for this permission (S68.1).
  const canSeeMargin = tienePermiso('ml_metricas.ver_ganancia');

  const [data, setData] = useState(null);
  const [facets, setFacets] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [columnVisibility, setColumnVisibility] = useState({});
  // Publications whose variation sub-rows are open. Their data loads on opening.
  const [expandedIds, setExpandedIds] = useState(() => new Set());
  const toggleVariations = useCallback(
    (itemId) =>
      setExpandedIds((current) => {
        const next = new Set(current);
        if (!next.delete(itemId)) next.add(itemId);
        return next;
      }),
    [],
  );

  const pageSize = filters.limite;
  const latestRequest = useRef(0);
  // The filter set the current `facets` belong to. Advances only when a
  // response that carried facets is applied, so a failure asks again.
  const facetsFor = useRef(null);

  useEffect(() => {
    const request = ++latestRequest.current;
    const wantFacets = filterKey !== facetsFor.current;
    const params = buildItemsParams(filters, pageSize, { canSeeMargin });
    if (wantFacets) params.facets = true;
    setLoading(true);
    setError(null);
    publicacionesMlAPI
      .items(params)
      .then((response) => {
        if (request !== latestRequest.current) return;
        setData(response.data);
        if (wantFacets) {
          setFacets(response.data.facets ?? null);
          facetsFor.current = filterKey;
        }
        setLoading(false);
      })
      .catch((err) => {
        if (request !== latestRequest.current) return;
        setError(err);
        setLoading(false);
      });
  }, [filters, filterKey, pageSize, reloadToken, canSeeMargin]);

  const eventsEnabled = data?.events_enabled ?? false;
  const columns = useMemo(
    () =>
      buildColumns({ eventsEnabled, canSeeMargin, expandedIds, onToggleVariations: toggleVariations }),
    [eventsEnabled, canSeeMargin, expandedIds, toggleVariations],
  );

  // The kit's ColumnPicker is TanStack-shaped; this table is the kit's, so a
  // row-less table instance carries only the visibility state both read.
  const columnDefs = useMemo(
    () => columns.map((column) => ({ id: column.key, header: column.label ?? column.header, enableHiding: column.key !== 'titulo' })),
    [columns],
  );
  const pickerTable = useReactTable({
    data: EMPTY_ROWS,
    columns: columnDefs,
    state: { columnVisibility },
    onColumnVisibilityChange: setColumnVisibility,
    getCoreRowModel: getCoreRowModel(),
  });
  const visibleColumns = columns.filter((column) => columnVisibility[column.key] !== false);

  // A shared link may carry the markup sort; without the permission it is the default one.
  const requestedSort = filters.orden === 'markup' && !canSeeMargin ? '' : filters.orden;
  const sortKey = requestedSort || DEFAULT_SORT;
  const sort = { key: sortKey, dir: (requestedSort && filters.dir) || DEFAULT_DIRECTION[sortKey] || 'desc' };
  const handleSort = (key) => {
    if (key === sort.key) setFilters({ orden: key, dir: sort.dir === 'asc' ? 'desc' : 'asc' });
    else setFilters({ orden: key, dir: DEFAULT_DIRECTION[key] ?? 'desc' });
  };

  // Ctrl/Cmd+click opens the publication in ML (side panel when the extension
  // is there); a plain click selects the row. A publication without a usable
  // permalink opens nothing, and is not selected either.
  const handleRowClick = useCallback(
    (item, event) => {
      if (event?.ctrlKey || event?.metaKey) {
        openInMlPanel(buildMlItemUrl(item.permalink));
        return;
      }
      setFilters({ sel: item.item_id });
    },
    [setFilters],
  );

  const storeChips = buildStoreChips({
    tiendas,
    getLabel,
    // The backend counts "no official store" under `none`; the chips call it `sin_tienda`.
    counts: facets?.stores ? { ...facets.stores, sin_tienda: facets.stores.none } : undefined,
    selected: filters.tiendas.join(','),
  });

  const csvChange = (key) => (value) => setFilters({ [key]: value ? value.split(',') : [] });
  const activeOf = (values) => values.join(',');
  // The markup filters are invisible (and not sent) without the permission, so they do not count either.
  const activeKeys = canSeeMargin ? FILTER_KEYS : FILTER_KEYS.filter((key) => !key.startsWith('markup_'));
  const hasActiveFilters = activeKeys.some((key) => (Array.isArray(filters[key]) ? filters[key].length > 0 : filters[key] !== ''));

  const items = data?.items ?? EMPTY_ROWS;
  const total = data?.total ?? 0;
  const offset = (filters.pagina - 1) * pageSize;
  const emptyMessage = data?.data_state?.store_empty
    ? 'Todavía no hay publicaciones sincronizadas'
    : hasActiveFilters
      ? 'Ninguna publicación coincide con los filtros'
      : 'No hay publicaciones';

  const chipGroup = (label, key, options, labels, counts) => (
    <FacetChips
      label={label}
      options={options}
      labels={labels}
      counts={counts}
      total={facets?.total}
      activeValue={activeOf(filters[key])}
      onChange={csvChange(key)}
    />
  );

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <h1>Publicaciones ML</h1>
          <p className={styles.description}>
            Todas las publicaciones de Mercado Libre: estado, precio, stock y vínculo con el producto.
          </p>
        </div>
        <div className={styles.headerActions}>
          <ColumnPicker table={pickerTable} />
        </div>
      </header>

      <StateBanner dataState={data?.data_state} />

      <section className={styles.filterCard} aria-label="Filtros">
        <div className={styles.filterBand}>
          <div className={styles.searchSlot}>
            <SearchInput
              value={filters.q}
              onChange={(value) => setFilters({ q: value })}
              debounce={400}
              placeholder="Buscar por título, MLA, SKU/EAN o producto…"
            />
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Estado:</span>
            {chipGroup('Filtrar por estado', 'estado', STATUS_OPTIONS, STATUS_LABELS, facets?.status)}
          </div>
          <span className={styles.spacer} />
          {hasActiveFilters && (
            <button type="button" className="btn-tesla ghost sm" onClick={resetFilters}>
              <FilterX size={14} />
              Limpiar filtros
            </button>
          )}
        </div>
        <div className={styles.filterBand}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Tipo:</span>
            {chipGroup('Filtrar por tipo', 'tipo', TIPO_OPTIONS, TIPO_LABELS, facets?.listing)}
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Vínculo:</span>
            {chipGroup('Filtrar por vínculo', 'vinculo', VINCULO_OPTIONS, VINCULO_LABELS, facets?.link)}
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Stock:</span>
            {chipGroup('Filtrar por stock', 'stock', STOCK_OPTIONS, STOCK_LABELS, facets?.stock)}
          </div>
        </div>
        <div className={styles.filterBand}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Tienda:</span>
            <FacetChips
              label="Filtrar por tienda oficial"
              {...storeChips}
              total={facets?.total}
              onChange={csvChange('tiendas')}
            />
          </div>
        </div>
        {canSeeMargin && (
          <div className={styles.filterBand}>
            <div className={styles.filterGroup}>
              <span className={styles.filterLabel}>Markup:</span>
              <MarkupFilters
                negative={filters.markup_neg === '1'}
                min={filters.markup_min}
                max={filters.markup_max}
                onChange={setFilters}
              />
            </div>
          </div>
        )}
      </section>

      {error ? (
        <div className={styles.errorBar} role="alert">
          <ShieldAlert size={16} aria-hidden="true" />
          <span className={styles.errorText}>{describeError(error)}</span>
          <button type="button" className="btn-tesla outline sm" onClick={() => setReloadToken((token) => token + 1)}>
            Reintentar
          </button>
        </div>
      ) : !data ? (
        <ListSkeleton />
      ) : (
        <div className={styles.listArea} aria-busy={loading}>
          <SplitPanelLayout open={false} onClose={() => setFilters({ sel: '', tab: '' })} panel={null}>
            <TableShell
              columns={visibleColumns}
              rows={items}
              getRowKey={(item) => item.item_id}
              renderSubRows={(item) =>
                item.variations_count > 1 && expandedIds.has(item.item_id) ? (
                  <VariationRows item={item} columns={visibleColumns} canSeeMargin={canSeeMargin} />
                ) : null
              }
              sort={sort}
              onSort={handleSort}
              onRowClick={handleRowClick}
              selectedKey={filters.sel || undefined}
              offset={TABLE_OFFSET}
              emptyMessage={emptyMessage}
              ariaLabel="Publicaciones de Mercado Libre"
            />
          </SplitPanelLayout>
          <div className={styles.pager}>
            <Pagination
              total={total}
              offset={offset}
              pageSize={pageSize}
              pageSizeOptions={PAGE_SIZES}
              summary={
                <span>
                  mostrando {total === 0 ? 0 : offset + 1}-{Math.min(offset + pageSize, total)} de {total} publicaciones
                </span>
              }
              onOffsetChange={(next) => setFilters({ pagina: Math.floor(next / pageSize) + 1 })}
              onPageSizeChange={(size) => setFilters({ limite: size === PAGE_SIZE ? '' : size })}
            />
          </div>
        </div>
      )}
    </div>
  );
}
