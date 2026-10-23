import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useReactTable, getCoreRowModel } from '@tanstack/react-table';
import { Download, FileSpreadsheet, FilterX, ShieldAlert } from 'lucide-react';
import { publicacionesMlAPI } from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';
import SearchInput from '../components/SearchInput';
import { ColumnPicker, FacetChips, Pagination, SegmentedControl, SplitPanelLayout, SwitchChip, TableShell } from '../components/kit';
import StateBanner from '../components/publicacionesMl/StateBanner';
import MarkupFilters from '../components/publicacionesMl/MarkupFilters';
import PresenceFilters from '../components/publicacionesMl/PresenceFilters';
import ProductFilters from '../components/publicacionesMl/ProductFilters';
import PublicationKpiStrip from '../components/publicacionesMl/PublicationKpiStrip';
import PublicationPanel from '../components/publicacionesMl/PublicationPanel';
import ProductPanel from '../components/publicacionesMl/ProductPanel';
import VariationRows from '../components/publicacionesMl/VariationRows';
import AgrupadoTable from '../components/publicacionesMl/AgrupadoTable';
import ProductoTable from '../components/publicacionesMl/ProductoTable';
import BulkActions from '../components/publicacionesMl/BulkActions';
import { withProductSelection } from '../components/publicacionesMl/productSelection';
import useProductRows from '../components/publicacionesMl/useProductRows';
import { buildColumns, columnChoicesOver, defaultColumnVisibility } from '../components/publicacionesMl/columns';
import { buildStoreChips } from '../constants/tiendasOficiales';
import { useTiendasOficiales } from '../hooks/useTiendasOficiales';
import {
  AGRUPAR_DIMENSIONS,
  DEFAULT_DIRECTION,
  FILTER_KEYS,
  PAGE_SIZE,
  PAGE_SIZES,
  buildExportParams,
  buildItemsParams,
  buildKpiParams,
  effectiveSort,
  hasMarkupFilter,
  usePublicacionesMLFilters,
} from '../hooks/usePublicacionesMLFilters';
import { usePublicacionesMLKpis } from '../hooks/usePublicacionesMLKpis';
import { buildMlItemUrl, openInMlPanel } from '../utils/mlSidePanel';
import { buildMlSellerListingUrl, buildMlSellerPromosUrl, openMlSellerUrl } from '../utils/mlSellerPanel';
import { canExportVista, exportPublicacionesCsv, exportPublicacionesSheets } from '../utils/publicacionesMlExport';
import { isSheetsExportEnabled, loadGoogleIdentity } from '../utils/googleSheetsExport';
import { DIMENSION_OPTIONS } from '../utils/metricasMlLevels';
import SheetsNotice from '../components/sheets/SheetsNotice';
import useWarnBeforeUnload from '../hooks/useWarnBeforeUnload';
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
 * the row, which opens the detail panel beside the table (`sel`, `tab` in the URL).
 *
 * `vista=producto` swaps the list for one row per product, like Métricas ML's
 * Producto view (`ProductoTable`, `/view/products`), each opening into its
 * publications; it pages and sorts the products, and `/items` is asked only for
 * the honest-state block and the facet counts, as in the tree.
 *
 * `vista=agrupado` swaps the list for the tree (the levels of the `agrupar`
 * dimension, marca > categoría > subcategoría by default, > producto > [familia]
 * > publicación, `AgrupadoTable`): the tree loads its own
 * levels from `/view/groups`, so `/items` is asked only for what the screen
 * shares (the honest-state block and the facet counts, one row).
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
const VINCULO_OPTIONS = ['auto', 'manual', 'sin_producto', 'conflicto', 'no_evaluado', 'sku_divergente'];
const VINCULO_LABELS = {
  auto: 'Automático',
  manual: 'Manual',
  sin_producto: 'Sin producto',
  conflicto: 'Conflicto',
  no_evaluado: 'Sin evaluar',
  // Not a link state: the automatic links whose ML seller SKU names another product (or none), to fix in ML.
  sku_divergente: 'SKU distinto del producto',
};
// One chip per stock column, each filtering its own source: our own stock at ML, Full and the ERP's -- never a sum.
const STOCK_OPTIONS = ['propio_sin_stock', 'full_sin_stock', 'erp_sin_stock'];
const STOCK_LABELS = { propio_sin_stock: 'Sin stock propio', full_sin_stock: 'Full sin stock', erp_sin_stock: 'Sin stock ERP' };

const EMPTY_ROWS = [];

// Métricas ML's order (Producto | Publicación | Agrupado). The publication list stays the default: it is this
// screen's own unit, and every link without `vista` already opens it.
const VISTA_OPTIONS = [
  { value: 'producto', label: 'Producto' },
  { value: 'publicacion', label: 'Publicaciones' },
  { value: 'agrupado', label: 'Agrupado' },
];

// Métricas ML's dimension picker, limited to the dimensions the tree's `/groups` takes.
const AGRUPAR_OPTIONS = DIMENSION_OPTIONS.filter((option) => AGRUPAR_DIMENSIONS.includes(option.value));

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
  // The strip is Métricas' numbers: it needs `ml_metricas.ver`; the table does not.
  const canSeeKpis = tienePermiso('ml_metricas.ver');
  // The rows' Métricas figures (`metrics`) are Métricas' numbers too: same permission as the strip.
  const canSeeSales = canSeeKpis;
  // The period belongs to the strip alone: it is not a filter and never reaches `/items`.
  const [periodo, setPeriodo] = useState(30);

  const [data, setData] = useState(null);
  const [facets, setFacets] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  // The panel asks for a reload after a write (a promotion changes price and
  // markup). That one keeps the rows the operator has open; a user-triggered
  // reload starts from collapsed. In the agrupado view only `/items` (state,
  // facets) is asked again: the tree is not reloaded, so its rows keep the old
  // figures until the tree is next opened. The follow-up reads at ~5s and ~65s
  // only happen while the Promos tab stays open; leaving it cancels them, and
  // the row keeps the figures of the first reload until the next one.
  const keepExpanded = useRef(0); // number of the request that keeps the open rows
  const reloadList = useCallback(() => {
    keepExpanded.current = latestRequest.current + 1;
    setReloadToken((token) => token + 1);
  }, []);
  // The user's own picks from the column picker, over a permission-based
  // default (permissions may load after the first render).
  const [columnChoices, setColumnChoices] = useState({});
  const columnDefaults = useMemo(() => defaultColumnVisibility(), []);
  const columnVisibility = useMemo(() => ({ ...columnDefaults, ...columnChoices }), [columnDefaults, columnChoices]);
  const setColumnVisibility = useCallback(
    (updater) =>
      setColumnChoices((choices) => {
        const current = { ...columnDefaults, ...choices };
        const next = typeof updater === 'function' ? updater(current) : updater;
        return columnChoicesOver(next, columnDefaults);
      }),
    [columnDefaults],
  );
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

  // The products checked for the bulk pricing actions (a publication checks its linked product). They belong to
  // the list they were picked from: another filter or view starts with none.
  const [checkedIds, setCheckedIds] = useState(() => new Set());
  const toggleChecked = useCallback(
    (productId) =>
      setCheckedIds((current) => {
        const next = new Set(current);
        if (!next.delete(productId)) next.add(productId);
        return next;
      }),
    [],
  );
  const clearChecked = useCallback(() => setCheckedIds(new Set()), []);
  useEffect(clearChecked, [filterKey, filters.vista, clearChecked]);

  const pageSize = filters.limite;
  const agrupado = filters.vista === 'agrupado';
  const producto = filters.vista === 'producto';
  // The views that load their own rows: `/items` brings them only the state and the facets.
  const ownRows = agrupado || producto;
  const latestRequest = useRef(0);
  // The filter set the current `facets` belong to. Advances only when a
  // response that carried facets is applied, so a failure asks again.
  const facetsFor = useRef(null);

  // What `/items` is asked with. The selection and the tab are not part of it: choosing a row asks for nothing.
  // The tree does not apply the markup filters (`/groups` has none), so neither do its facet counts; nor is it
  // sorted, so its one-row facets request never asks for a Métricas sort (a ranking of the whole set).
  const requestKey = JSON.stringify(
    ownRows
      ? { ...buildItemsParams(filters, 1, { canSeeMargin: false }), offset: 0 }
      : buildItemsParams(filters, pageSize, { canSeeMargin, canSeeSales }),
  );

  useEffect(() => {
    const request = ++latestRequest.current;
    const wantFacets = filterKey !== facetsFor.current;
    const params = JSON.parse(requestKey);
    if (wantFacets) params.facets = true;
    setLoading(true);
    setError(null);
    publicacionesMlAPI
      .items(params)
      .then((response) => {
        if (request !== latestRequest.current) return;
        setData(response.data);
        // A new list (page, sort, filter) starts with every row collapsed.
        if (keepExpanded.current !== request) setExpandedIds(new Set());
        keepExpanded.current = 0;
        if (wantFacets) {
          setFacets(response.data.facets ?? null);
          facetsFor.current = filterKey;
        }
        setLoading(false);
      })
      .catch((err) => {
        if (request !== latestRequest.current) return;
        keepExpanded.current = 0;
        setError(err);
        setLoading(false);
      });
  }, [requestKey, filterKey, reloadToken]);

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(null);
  const [exportingSheets, setExportingSheets] = useState(false);
  // The sheet is written from this page: a reload or a closed tab would cut it halfway.
  useWarnBeforeUnload(exportingSheets);
  // What "Exportar a Sheets" left to say that is not an error: a cancelled popup, or the link to the new sheet (shown even when its tab opened: a browser can block it silently).
  const [sheetsNotice, setSheetsNotice] = useState(null);
  const sheetsEnabled = isSheetsExportEnabled();
  useEffect(() => {
    if (sheetsEnabled) loadGoogleIdentity().catch(() => {}); // ready before the click; a failure shows on the click
  }, [sheetsEnabled]);
  // A refusal belongs to the list it was asked for: narrowing the filters or changing the view clears it, and a
  // refusal that arrives after the operator left that list is dropped (the file of a success is still the one asked for).
  const exportList = `${filters.vista}|${filterKey}`;
  const currentExportList = useRef(exportList);
  useEffect(() => {
    currentExportList.current = exportList;
    setExportError(null);
    setSheetsNotice(null);
  }, [exportList]);
  // The CSV of the view on screen, with the list's own filters and sort (the Agrupado tree has no export).
  // "Exportar a Sheets" sends the same view and request to a new Google Sheet, straight from the click (the Google
  // popup needs it); a cancelled popup and the link to the new sheet are notes, not refusals.
  const runExport = async (exporter, setBusy) => {
    const askedFor = exportList;
    setBusy(true);
    setExportError(null);
    setSheetsNotice(null);
    try {
      const result = await exporter(filters.vista, buildExportParams(filters, { canSeeMargin, canSeeSales }));
      if (result?.url) setSheetsNotice({ url: result.url });
    } catch (err) {
      if (askedFor !== currentExportList.current) return;
      if (err.cancelled) setSheetsNotice({ text: err.message });
      else setExportError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const handleExport = () => runExport(exportPublicacionesCsv, setExporting);
  const handleSheetsExport = () => runExport(exportPublicacionesSheets, setExportingSheets);

  const kpis = usePublicacionesMLKpis(buildKpiParams(filters, periodo), canSeeKpis);
  const productRows = useProductRows({ filters, pageSize, canSeeSales, canSeeMargin, enabled: producto });

  const eventsEnabled = data?.events_enabled ?? false;
  // The divergence filter brings its own column: the SKU next to the product it names and the linked one.
  const skuDivergence = filters.vinculo.includes('sku_divergente');
  const columns = useMemo(
    () =>
      buildColumns({
        eventsEnabled,
        canSeeMargin,
        canSeeSales,
        expandedIds,
        onToggleVariations: toggleVariations,
        agrupado,
        producto,
        dimension: filters.agrupar,
        familias: filters.familias === '1',
        skuDivergence,
      }),
    [eventsEnabled, canSeeMargin, canSeeSales, expandedIds, toggleVariations, agrupado, producto, filters.agrupar, filters.familias, skuDivergence],
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
  const visibleColumns = useMemo(
    () => columns.filter((column) => columnVisibility[column.key] !== false),
    [columns, columnVisibility],
  );
  const selection = useMemo(() => ({ checked: checkedIds, onToggle: toggleChecked }), [checkedIds, toggleChecked]);
  const selectableColumns = useMemo(() => withProductSelection(visibleColumns, selection), [visibleColumns, selection]);

  // What the list really applies: a sort the user may not ask for (a shared link) falls back on the default --
  // Facturado 30D for who sees the sales, like Métricas; the activity otherwise.
  // The Producto view sorts the products by their own figures (`effectiveProductSort`).
  const sort = producto ? productRows.sort : effectiveSort(filters, { canSeeSales, canSeeMargin });
  // A publication's panel takes the place of its product's (`sel` over `prod`); closing either closes the panel.
  const closePanel = () => setFilters({ sel: '', tab: '', prod: '' });
  const selectProduct = (key) => setFilters({ prod: key, sel: '', tab: '' });
  const selectProductItem = (itemId) => setFilters({ sel: itemId, tab: '' });
  const backToProduct = () => setFilters({ sel: '', tab: '' });
  const backLabel = filters.prod
    ? productRows.rows.find((row) => row.type === 'node' && row.node.key === filters.prod)?.node.label
    : undefined;
  const changeTab = (tab) => setFilters({ tab });
  const handleSort = (key) => {
    if (key === sort.key) setFilters({ orden: key, dir: sort.dir === 'asc' ? 'desc' : 'asc' });
    else setFilters({ orden: key, dir: DEFAULT_DIRECTION[key] ?? 'desc' });
  };

  // Ctrl/Cmd+click opens the publication in ML (side panel when the extension
  // is there); Alt+click opens it in the seller panel, Shift+click its
  // promotions; a plain click selects the row. A publication without a usable
  // permalink (or MLA) opens nothing, and is not selected either.
  const handleRowClick = useCallback(
    (item, event) => {
      if (event?.ctrlKey || event?.metaKey) {
        openInMlPanel(buildMlItemUrl(item.permalink));
        return;
      }
      const sellerUrl = event?.altKey ? buildMlSellerListingUrl : event?.shiftKey ? buildMlSellerPromosUrl : null;
      if (sellerUrl) {
        // Shift+click also extends the text selection over the table: drop it.
        window.getSelection()?.removeAllRanges();
        openMlSellerUrl(sellerUrl(item.item_id));
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
  // The markup filters are invisible (and not sent) without the permission, or in the tree, so they do not count either.
  const showMarkupFilters = canSeeMargin && !ownRows;
  const activeKeys = showMarkupFilters ? FILTER_KEYS : FILTER_KEYS.filter((key) => !key.startsWith('markup_'));
  const hasActiveFilters = activeKeys.some((key) => (Array.isArray(filters[key]) ? filters[key].length > 0 : filters[key] !== ''));

  const items = data?.items ?? EMPTY_ROWS;
  const total = producto ? productRows.total : (data?.total ?? 0);
  const unit = producto ? 'productos' : 'publicaciones';
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
          <SegmentedControl
            label="Vista"
            options={VISTA_OPTIONS}
            value={filters.vista}
            onChange={(value) => setFilters({ vista: value === 'publicacion' ? '' : value })}
          />
          {agrupado && (
            <SegmentedControl
              label="Agrupar por"
              options={AGRUPAR_OPTIONS}
              value={filters.agrupar}
              onChange={(value) => setFilters({ agrupar: value === AGRUPAR_DIMENSIONS[0] ? '' : value })}
            />
          )}
          {agrupado && (
            <SwitchChip
              label="Con familias"
              title="Agrupa las publicaciones de una misma familia dentro de cada producto"
              checked={filters.familias === '1'}
              onChange={(checked) => setFilters({ familias: checked ? '1' : '' })}
            />
          )}
          <BulkActions
            filters={filters}
            checkedIds={checkedIds}
            onClearChecked={clearChecked}
            canSeeMargin={canSeeMargin}
            onDone={reloadList}
          />
          <ColumnPicker table={pickerTable} />
          {canExportVista(filters.vista) && (
            <button type="button" className="btn-tesla outline sm" onClick={handleExport} disabled={exporting}>
              <Download size={14} />
              {exporting ? 'Exportando…' : 'Exportar CSV'}
            </button>
          )}
          {sheetsEnabled && canExportVista(filters.vista) && (
            <button type="button" className="btn-tesla outline sm" onClick={handleSheetsExport} disabled={exportingSheets}>
              <FileSpreadsheet size={14} />
              {exportingSheets ? 'Exportando a Sheets…' : 'Exportar a Sheets'}
            </button>
          )}
        </div>
      </header>

      {exportError && (
        <div className={styles.errorBar} role="alert">
          <ShieldAlert size={16} aria-hidden="true" />
          <span className={styles.errorText}>{exportError}</span>
        </div>
      )}
      <SheetsNotice notice={exportingSheets ? { processing: true } : sheetsNotice} onClose={() => setSheetsNotice(null)} />

      <StateBanner dataState={data?.data_state} />

      {canSeeKpis && (
        <PublicationKpiStrip
          state={kpis}
          periodo={periodo}
          onPeriodChange={setPeriodo}
          markupNotice={showMarkupFilters && hasMarkupFilter(filters)}
        />
      )}

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
        <div className={styles.filterBand}>
          <ProductFilters filters={filters} setFilters={setFilters} labelClassName={styles.filterLabel} />
          {/* Same band as the product filters, behind a button: a band of its own pushed the list's header below
              the fold at 1366x768. */}
          <PresenceFilters filters={filters} setFilters={setFilters} labelClassName={styles.filterLabel} />
        </div>
        {showMarkupFilters && (
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

      {error && (
        <div className={styles.errorBar} role="alert">
          <ShieldAlert size={16} aria-hidden="true" />
          <span className={styles.errorText}>{describeError(error)}</span>
          <button type="button" className="btn-tesla outline sm" onClick={() => setReloadToken((token) => token + 1)}>
            Reintentar
          </button>
        </div>
      )}

      {/* In the tree and the Producto view `/items` only brings the state and the facets: its failure leaves their rows (which have their own errors) on screen. */}
      {error && !ownRows ? null : !data && !ownRows ? (
        <ListSkeleton />
      ) : (
        <div className={styles.listArea} aria-busy={loading}>
          <SplitPanelLayout
            open={Boolean(filters.sel || filters.prod)}
            onClose={closePanel}
            width="lg"
            ariaLabel={filters.sel ? 'Detalle de la publicación' : 'Detalle del producto'}
            panel={
              filters.sel ? (
                <PublicationPanel
                  itemId={filters.sel}
                  tab={filters.tab}
                  onTabChange={changeTab}
                  onClose={closePanel}
                  onListReload={reloadList}
                  dataState={data?.data_state}
                  onBack={filters.prod ? backToProduct : undefined}
                  backLabel={backLabel}
                />
              ) : filters.prod ? (
                <ProductPanel
                  filters={filters}
                  productKey={filters.prod}
                  onClose={closePanel}
                  onSelectItem={selectProductItem}
                  canSeeSales={canSeeSales}
                  canSeeMargin={canSeeMargin}
                  onListReload={reloadList}
                />
              ) : null
            }
          >
            {producto ? (
              <ProductoTable
                tree={productRows}
                columns={selectableColumns}
                selection={selection}
                canSeeMargin={canSeeMargin}
                expandedIds={expandedIds}
                onSelectItem={handleRowClick}
                onSelectProduct={selectProduct}
                selectedKey={filters.sel || undefined}
                selectedProductKey={filters.prod || undefined}
                sort={sort}
                onSort={handleSort}
                offset={TABLE_OFFSET}
                emptyMessage={hasActiveFilters ? 'Ningún producto coincide con los filtros' : 'No hay productos'}
              />
            ) : agrupado ? (
              <AgrupadoTable
                columns={selectableColumns}
                filters={filters}
                familias={filters.familias === '1'}
                dimension={filters.agrupar}
                canSeeMargin={canSeeMargin}
                expandedIds={expandedIds}
                onSelectItem={handleRowClick}
                selectedKey={filters.sel || undefined}
                offset={TABLE_OFFSET}
                emptyMessage={emptyMessage}
              />
            ) : (
              <TableShell
                columns={selectableColumns}
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
            )}
          </SplitPanelLayout>
          {!agrupado && (
            <div className={styles.pager}>
              <Pagination
                total={total}
                offset={offset}
                pageSize={pageSize}
                pageSizeOptions={PAGE_SIZES}
                summary={
                  <span>
                    mostrando {total === 0 ? 0 : offset + 1}-{Math.min(offset + pageSize, total)} de {total} {unit}
                  </span>
                }
                onOffsetChange={(next) => setFilters({ pagina: Math.floor(next / pageSize) + 1 })}
                onPageSizeChange={(size) => setFilters({ limite: size === PAGE_SIZE ? '' : size })}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
