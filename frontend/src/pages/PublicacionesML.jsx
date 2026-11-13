import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useReactTable, getCoreRowModel } from '@tanstack/react-table';
import {
  Check,
  ChevronDown,
  Download,
  FileDown,
  FileSpreadsheet,
  FilterX,
  Gauge,
  Rows4,
  ShieldAlert,
  Users,
} from 'lucide-react';
import { publicacionesMlAPI } from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';
import SearchInput from '../components/SearchInput';
import { ColumnPicker, FacetChips, Pagination, SegmentedControl, SplitPanelLayout, SwitchChip, TableShell } from '../components/kit';
import StateBanner from '../components/publicacionesMl/StateBanner';
import MarkupFilters from '../components/publicacionesMl/MarkupFilters';
import PresenceFilters from '../components/publicacionesMl/PresenceFilters';
import AuditFilters from '../components/publicacionesMl/AuditFilters';
import PromoFilters from '../components/publicacionesMl/PromoFilters';
import ProductFilters from '../components/publicacionesMl/ProductFilters';
import PublicationKpiStrip from '../components/publicacionesMl/PublicationKpiStrip';
import { publicationKpiOptions } from '../components/publicacionesMl/publicationKpiOptions';
import PublicationStatCards from '../components/publicacionesMl/PublicationStatCards';
import PublicationCountCards from '../components/publicacionesMl/PublicationCountCards';
import PublicationPanel from '../components/publicacionesMl/PublicationPanel';
import ProductPanel from '../components/publicacionesMl/ProductPanel';
import VariationRows from '../components/publicacionesMl/VariationRows';
import AgrupadoTable from '../components/publicacionesMl/AgrupadoTable';
import ColorFilterChips from '../components/publicacionesMl/ColorFilterChips';
import ColorLayerSelect from '../components/publicacionesMl/ColorLayerSelect';
import PaintColorMenu from '../components/publicacionesMl/PaintColorMenu';
import { itemRowTone } from '../components/publicacionesMl/rowColor';
import useColorOverlay from '../components/publicacionesMl/useColorOverlay';
import { useSSEChannel } from '../hooks/useSSEChannel';
import useHiddenKpis from '../hooks/useHiddenKpis';
import useRowDensity from '../hooks/useRowDensity';
import useResizableColumns, { PUBML_COLUMN_SIZING_KEYS } from '../components/publicacionesMl/useResizableColumns';
import { PREARMADAS_LIMITE, usePrearmadasStats } from '../hooks/usePrearmadasStats';
import { useEquipos } from '../hooks/useEquipos';
import EquiposModal from '../components/EquiposModal';
import usePaintProduct from '../components/publicacionesMl/usePaintProduct';
import usePaintPublication from '../components/publicacionesMl/usePaintPublication';
import ProductoTable from '../components/publicacionesMl/ProductoTable';
import BulkActions from '../components/publicacionesMl/BulkActions';
import BulkStatusActions from '../components/publicacionesMl/BulkStatusActions';
import { resolverParams } from '../components/publicacionesMl/bulkParams';
import ExportModal from '../components/ExportModal';
import ModalInfoProducto from '../components/ModalInfoProducto';
import ShortcutsHelp from '../components/publicacionesMl/ShortcutsHelp';
import useRecalcularCuotasAuto from '../components/publicacionesMl/useRecalcularCuotasAuto';
import usePublicacionesMLKeyboard from '../components/publicacionesMl/usePublicacionesMLKeyboard';
import Toast from '../components/Toast';
import { useToast } from '../hooks/useToast';
import { withRowSelection } from '../components/publicacionesMl/rowSelection';
import useRowSelection, { selectionRow } from '../components/publicacionesMl/useRowSelection';
import useProductRows, { appendPage } from '../components/publicacionesMl/useProductRows';
import useListPrices from '../components/publicacionesMl/useListPrices';
import useTnCardPercent from '../components/publicacionesMl/useTnCardPercent';
import { useListOffsets } from '../hooks/useListOffsets';
import PriceModeSelect from '../components/publicacionesMl/PriceModeSelect';
import { canViewProductPrices, pricePermissions } from '../components/pricing/productPricePermissions';
import useInlinePriceEdit from '../components/publicacionesMl/useInlinePriceEdit';
import ModalTesla, { ModalFooterButtons } from '../components/ModalTesla';
import PricingModalTesla from '../components/PricingModalTesla';
import { buildColumns, columnChoicesOver, defaultColumnVisibility } from '../components/publicacionesMl/columns';
import {
  canUsePonerPreciosMode,
  visibilityForPonerPreciosMode,
} from '../components/publicacionesMl/ponerPreciosMode';
import { buildStoreChips } from '../constants/tiendasOficiales';
import { useTiendasOficiales } from '../hooks/useTiendasOficiales';
import {
  AGRUPAR_DIMENSIONS,
  ALL_ROWS,
  FILTER_KEYS,
  LAZY_CHUNK,
  PAGE_SIZE,
  PAGE_SIZES,
  pageOffset,
  pageSizeLabel,
  PRICE_MODES,
  PRODUCT_SORTS,
  SIN_MLA,
  buildExportParams,
  buildItemsParams,
  buildKpiParams,
  buildStatsParams,
  effectiveSortKeys,
  hasMarkupFilter,
  headerSort,
  nextSort,
  sortParams,
  usePublicacionesMLFilters,
  VIRTUALIZE_FROM,
} from '../hooks/usePublicacionesMLFilters';
import { usePublicacionesMLKpis, usePublicationStats } from '../hooks/usePublicacionesMLKpis';
import { buildMlItemUrl, openInMlPanel } from '../utils/mlSidePanel';
import { buildMlSellerListingUrl, buildMlSellerPromosUrl } from '../utils/mlSellerPanel';
import {
  canExportVista,
  exportPublicacionesCsv,
  exportPublicacionesSheets,
  resolverProductosExport,
} from '../utils/publicacionesMlExport';
import { isSheetsExportEnabled, loadGoogleIdentity } from '../utils/googleSheetsExport';
import { DIMENSION_OPTIONS } from '../utils/metricasMlLevels';
import SheetsNotice from '../components/sheets/SheetsNotice';
import useWarnBeforeUnload from '../hooks/useWarnBeforeUnload';
import useIsPhone from '../hooks/useIsPhone';
import { formatUnits } from '../utils/metricasMlFormat';
import PhoneSheet from '../components/publicacionesMl/mobile/PhoneSheet';
import PhoneToolbar from '../components/publicacionesMl/mobile/PhoneToolbar';
import PhoneList from '../components/publicacionesMl/mobile/PhoneList';
import phoneStyles from '../components/publicacionesMl/mobile/PhoneLayout.module.css';
import styles from './PublicacionesML.module.css';
import buttonStyles from '../components/publicacionesMl/toolbarButton.module.css';

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
 *
 * Keyboard: Productos' shortcuts over what this screen has (`usePublicacionesMLKeyboard`, help on `?`).
 */
// Space the table leaves for what is above and below it (header, filters, pager).
const TABLE_OFFSET = '380px';

// Every secondary action on the screen: the same button with a thin grey outline.
const quietButton = `btn-tesla sm ${buttonStyles.quiet}`;

// Productos' search operators, also understood by the backend's `normalize_q`.
const SEARCH_OPERATORS_HELP =
  'Operadores: codigo:ABC123 o ean:7790001234567 (código exacto), marca:Samsung (marca exacta), *123 (termina en)';

const STATUS_OPTIONS = ['active', 'paused', 'closed', 'under_review', 'inactive', 'gone'];
const STATUS_LABELS = {
  active: 'Activas',
  paused: 'Pausadas',
  closed: 'Cerradas',
  under_review: 'En revisión',
  inactive: 'Inactivas',
  gone: 'Eliminadas',
};
// The state's dot in the Estado filter, the same tones as a node's states in the tree.
const STATUS_TONES = {
  active: 'success',
  paused: 'warning',
  under_review: 'warning',
  closed: 'neutral',
  inactive: 'neutral',
  gone: 'danger',
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
// One chip per stock source, each filtering its own: Full and the ERP's -- never a sum.
const STOCK_OPTIONS = ['full_sin_stock', 'erp_sin_stock', 'erp_con_stock'];
const STOCK_LABELS = {
  full_sin_stock: 'Full sin stock',
  erp_sin_stock: 'Sin stock ERP',
  erp_con_stock: 'Con stock ERP',
};

const EMPTY_ROWS = [];

// Métricas ML's order (Producto | Publicación | Agrupado). The publication list stays the default: it is this
// screen's own unit, and every link without `vista` already opens it.
const VISTA_OPTIONS = [
  { value: 'producto', label: 'Producto' },
  { value: 'publicacion', label: 'Publicaciones' },
  // The publication rows with Productos' price columns (owner, 2026-10-28): prices out of the main list.
  { value: 'precios', label: 'Precios' },
  { value: 'agrupado', label: 'Agrupado' },
];

// Métricas ML's dimension picker, limited to the dimensions the tree's `/groups` takes.
const AGRUPAR_OPTIONS = DIMENSION_OPTIONS.filter((option) => AGRUPAR_DIMENSIONS.includes(option.value));

// The phone's "Cargar 20 más" (mobile-metricas-pubml S2): the next publications after the page, 20 at a time.
const PHONE_CHUNK = 20;

// The phone's sort picker: the table headers' sortable figures a card shows, each with the permission it needs.
const PHONE_SORTS = [
  { value: 'unidades_30d', label: 'Ventas 30D', sales: true },
  { value: 'facturado_30d', label: 'Facturado 30D', sales: true },
  { value: 'markup', label: 'Markup', margin: true, list: true },
  { value: 'markup_30d', label: 'Markup 30D', sales: true, margin: true, product: true },
  { value: 'stock_erp', label: 'Stock ERP', list: true },
  { value: 'tipo', label: 'Tipo', list: true },
  { value: 'actividad', label: 'Última actividad', list: true },
  { value: 'titulo', label: 'Título' },
];

function phoneSortOptions({ producto, canSeeSales, canSeeMargin }) {
  return PHONE_SORTS.filter(
    (option) =>
      (!option.sales || canSeeSales) &&
      (!option.margin || canSeeMargin) &&
      (producto ? !option.list && PRODUCT_SORTS.includes(option.value) : !option.product),
  );
}

/** What to tell the operator when a request fails (S69.1). */
function describeError(error) {
  const status = error?.response?.status;
  if (status === 503) {
    // A promo or wholesale-price filter whose source is down is not a slow query: say which one failed.
    const body = error.response.data?.error;
    if (body?.code === 'filtro_no_disponible' && body.message) return body.message;
    return 'La consulta tardó demasiado. Probá con filtros más acotados o reintentá.';
  }
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

// Productos' price lists (its export modal), each behind its own permission; the button shows with any of them.
const PRICE_LIST_EXPORT_PERMISSIONS = [
  'productos.exportar_vista_actual',
  'productos.exportar_rebate',
  'productos.exportar_web_transferencia',
  'productos.exportar_clasica',
  'productos.exportar_pvp',
];

const PRICE_LIST_SET =
  'Se exportan los productos vinculados a las publicaciones de los filtros actuales; las publicaciones sin producto vinculado quedan afuera.';

// The r / w / o toggles (S9): the `pricePermissions` flag each needs, and its name in the messages.
const TOGGLE_PERMISSION = {
  rebate: ['canToggleRebate', 'el rebate'],
  web: ['canToggleWebTransf', 'web transferencia'],
  tarjetas: ['canToggleOutOfCards', 'fuera de tarjetas'],
};

/** A request's params without its sort: the tree's one-row facets request orders nothing. */
function withoutSort({ orden, dir, ...params }) {
  void orden, dir;
  return params;
}

export default function PublicacionesML() {
  const { tienePermiso } = usePermisos();
  // Phones (<= 768px) get their own layout: cards, a filters sheet and the panel full screen (mobile-metricas-pubml).
  const isPhone = useIsPhone();
  // The phone's open bottom sheet: 'filtros', 'acciones' or none.
  const [phoneSheet, setPhoneSheet] = useState(null);
  const closePhoneSheet = () => setPhoneSheet(null);
  // The markup column, filters and sort exist only for this permission (S68.1).
  const canSeeMargin = tienePermiso('ml_metricas.ver_ganancia');
  const { filters, filterKey, setFilters, resetFilters } = usePublicacionesMLFilters({ canSeeMargin });
  const { tiendas, getLabel } = useTiendasOficiales();
  // The strip is Métricas' numbers: it needs `ml_metricas.ver`; the table does not.
  const canSeeKpis = tienePermiso('ml_metricas.ver');
  // The rows' Métricas figures (`metrics`) are Métricas' numbers too: same permission as the strip.
  const canSeeSales = canSeeKpis;
  // Productos' price columns (S11): for who sees Productos' prices, as Productos and the panel's Precios tab.
  const canSeePrices = canViewProductPrices(tienePermiso);
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
  const baseColumnVisibility = useMemo(
    () => ({ ...columnDefaults, ...columnChoices }),
    [columnDefaults, columnChoices],
  );
  const setColumnVisibility = useCallback(
    (updater) =>
      setColumnChoices((choices) => {
        const current = { ...columnDefaults, ...choices };
        const next = typeof updater === 'function' ? updater(current) : updater;
        return columnChoicesOver(next, columnDefaults);
      }),
    [columnDefaults],
  );
  // Workflow mode (S1–S3). Local flag — never the URL `modo` / PRICE_MODES.
  const [ponerPreciosMode, setPonerPreciosMode] = useState(false);
  // Promos Ver competencia: widen the split and show same-bucket ranking col 2.
  const [competenciaWide, setCompetenciaWide] = useState(false);
  const [filtersCollapsed, setFiltersCollapsed] = useState(false);
  const vistaBeforeMode = useRef(null);
  const canPonerPrecios = canUsePonerPreciosMode(tienePermiso);
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

  const { equipos, loaded: equiposLoaded, recargar: recargarEquipos } = useEquipos();
  // Team management, as in Productos: any user may create and run their own teams, so no permission gates it.
  const [equiposOpen, setEquiposOpen] = useState(false);
  // The rows are asked on a team layer only once the teams say it is the user's: a link to another team's layer
  // would answer 403 and flash a false error before ColorLayerSelect drops it. Until then nothing is asked.
  const layerPending = filters.equipo !== '' && !equiposLoaded;
  const layerKnown =
    filters.equipo === '' || equipos.some((equipo) => !equipo.es_global && String(equipo.id) === filters.equipo);
  const rowFilters = useMemo(() => (layerKnown ? filters : { ...filters, equipo: '' }), [filters, layerKnown]);
  // What is painted, on the layer and filters the rows were asked on, since the rows loaded -- here or by
  // anyone -- repaints them without asking the list again (the trees would close their open branches).
  const colorOverlay = useColorOverlay(rowFilters.equipo, filterKey);
  useSSEChannel('producto_color:changed', colorOverlay.apply);
  useSSEChannel('publicacion_color:changed', colorOverlay.applyOwn);
  const getItemTone = useCallback(
    (item) => itemRowTone(item, colorOverlay.colors, colorOverlay.own),
    [colorOverlay.colors, colorOverlay.own],
  );

  const pageSize = filters.limite;
  // A long page (200, 500, Todos) renders only the rows in view; a short one, however many rows it expands to, as before.
  const virtualizeFrom = pageSize > VIRTUALIZE_FROM ? VIRTUALIZE_FROM : undefined;
  const agrupado = filters.vista === 'agrupado';
  const producto = filters.vista === 'producto';
  const precios = filters.vista === 'precios';
  // The main list sums up publications, not products (owner, 2026-10-28).
  const publicacion = filters.vista === 'publicacion';
  // Productos' Sin MLA: products with no publication, so nothing a publication strip or action could act on.
  const sinMla = filters.mla === SIN_MLA;
  // The views that load their own rows: `/items` brings them only the state and the facets.
  const ownRows = agrupado || producto;
  const latestRequest = useRef(0);
  // The filter set the current `facets` belong to. Advances only when a
  // response that carried facets is applied, so a failure asks again.
  const facetsFor = useRef(null);

  // "Todos" in the Publicación / Precios list is asked in parts (filtros S4): LAZY_CHUNK rows from the page's offset,
  // and the next part each time the table's end comes into view (`loadMoreItems`).
  const lazy = !ownRows && pageSize === ALL_ROWS;
  // The list's parts: the request they belong to, its params (no facets), the next offset and the page's end.
  const parts = useRef(null);
  // A part of "Todos" that failed: said under the table with its own "Reintentar", never a list cut short in silence.
  const [moreError, setMoreError] = useState(false);

  // What `/items` is asked with. The selection and the tab are not part of it: choosing a row asks for nothing.
  // The tree does not apply the markup filters (`/groups` has none), so neither do its facet counts; nor is it
  // sorted, so its one-row facets request never asks for a Métricas sort (a ranking of the whole set).
  const requestKey = JSON.stringify(
    ownRows
      ? { ...withoutSort(buildItemsParams(rowFilters, 1, { canSeeMargin: false })), offset: 0 }
      : { ...buildItemsParams(rowFilters, pageSize, { canSeeMargin, canSeeSales }), ...(lazy && { limit: LAZY_CHUNK }) },
  );

  useEffect(() => {
    if (layerPending) return;
    const request = ++latestRequest.current;
    const wantFacets = filterKey !== facetsFor.current;
    const asked = JSON.parse(requestKey);
    const params = wantFacets ? { ...asked, facets: true } : asked;
    parts.current = null;
    setMoreError(false);
    setLoading(true);
    setError(null);
    publicacionesMlAPI
      .items(params)
      .then((response) => {
        if (request !== latestRequest.current) return;
        setData(response.data);
        // "Todos" ends at the list's total, however many rows that is (filas-sin-limite S1). Any other page can be
        // continued too: the phone's "Cargar 20 más" asks for the rows after it (mobile-metricas-pubml S2).
        const end = Math.max(asked.offset, response.data.total ?? 0);
        parts.current = { request, params: asked, next: asked.offset + asked.limit, end, busy: false };
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
  }, [requestKey, filterKey, reloadToken, layerPending, lazy]);

  // The next part of "Todos": the same params from the next offset, appended to the rows (once each, by MLA). The
  // total, the data state and the facets stay the first part's. A part of a list that is no longer the current one
  // (a filter, sort or reload asked again) is dropped; a failed part leaves the rows as they are and says so
  // (`moreError`), and its "Reintentar" calls this again for the same offset.
  const loadNextItems = useCallback((chunk) => {
    const current = parts.current;
    if (!current || current.busy || current.next >= current.end || current.request !== latestRequest.current) return;
    current.busy = true;
    const offset = current.next;
    const limit = Math.min(chunk, current.end - offset);
    publicacionesMlAPI
      .items({ ...current.params, offset, limit })
      .then((response) => {
        if (current.request !== latestRequest.current) return;
        current.next = offset + limit;
        current.busy = false;
        setMoreError(false);
        setData((shown) => ({ ...shown, items: appendPage(shown?.items ?? EMPTY_ROWS, response.data?.items ?? []) }));
      })
      .catch(() => {
        current.busy = false;
        if (current.request === latestRequest.current) setMoreError(true);
      });
  }, []);
  const loadMoreItems = useCallback(() => loadNextItems(LAZY_CHUNK), [loadNextItems]);
  const loadMoreCards = () => loadNextItems(PHONE_CHUNK);

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
      const result = await exporter(filters.vista, buildExportParams(rowFilters, { canSeeMargin, canSeeSales }));
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
  // Productos' price lists over the linked products of the filtered publications, resolved as a bulk action's set.
  const canExportPriceLists = PRICE_LIST_EXPORT_PERMISSIONS.some((codigo) => tienePermiso(codigo));
  const [priceListsOpen, setPriceListsOpen] = useState(false);
  const resolvePriceListProducts = () => resolverProductosExport(resolverParams(rowFilters, canSeeMargin));

  const searchRef = useRef(null);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const { toast, showToast, hideToast } = useToast();

  // Like the rows, the strip and the bulk sets ask only a layer known to be the user's (it matters with `colores`).
  const kpis = usePublicacionesMLKpis(buildKpiParams(rowFilters, periodo), canSeeKpis && !layerPending && !sinMla);
  // The KPI cards the viewer hid, from the "Indicadores" picker (only while the strip shows); requests never change.
  const kpiData = kpis.data?.kpis;
  const kpiOptions = useMemo(() => (canSeeKpis && !sinMla ? publicationKpiOptions(kpiData) : []), [canSeeKpis, sinMla, kpiData]);
  const { isVisible: kpiVisible, pickerTable: kpiPicker } = useHiddenKpis('publicaciones-ml.kpis-ocultos', kpiOptions);
  // "Filas finas": the tables' Sheets-like density, remembered per browser; only the look changes.
  const { dense, toggleDense } = useRowDensity('publicaciones-ml.filas-finas');
  // The first column's width, dragged by the user (S5): the list and the Producto view each keep their own.
  const listSizing = useResizableColumns(PUBML_COLUMN_SIZING_KEYS.lista);
  const productSizing = useResizableColumns(PUBML_COLUMN_SIZING_KEYS.producto);
  const treeSizing = useResizableColumns(PUBML_COLUMN_SIZING_KEYS.agrupado);
  const stats = usePublicationStats(buildStatsParams(rowFilters), !layerPending && !publicacion);
  const productRows = useProductRows({
    filters: rowFilters,
    pageSize,
    canSeeSales,
    canSeeMargin,
    enabled: producto && !layerPending,
  });

  // Productos' prearmadas badge beside each product row: the first PREARMADAS_LIMITE products, as Productos asks them.
  const prearmadasItemIds = useMemo(
    () =>
      producto
        ? productRows.rows
            .filter((row) => row.type === 'node' && row.node.productoItemId != null)
            .slice(0, PREARMADAS_LIMITE)
            .map((row) => row.node.productoItemId)
        : EMPTY_ROWS,
    [producto, productRows.rows],
  );
  const { statsById: prearmadasStats } = usePrearmadasStats(prearmadasItemIds);

  // Productos' prices of the products on show: the publications' linked products, or the product rows themselves.
  // The tree loads its rows by itself and has no price columns.
  const listedProductIds = useMemo(
    () =>
      producto
        ? productRows.rows.map((row) =>
            row.type === 'node' ? row.node.productoItemId : row.type === 'item' ? row.item.link?.producto_item_id : null,
          )
        : (data?.items ?? EMPTY_ROWS).map((item) => item.link?.producto_item_id),
    [producto, productRows.rows, data],
  );
  // A panel or bulk write reloads the list (`reloadList`): the prices are read again with it. Read in every list
  // view, not only Precios: the r / w / o shortcuts toggle the focused row's product from these prices.
  const listPrices = useListPrices(listedProductIds, canSeePrices && !agrupado, reloadToken);
  // Productos' Tienda Nube card surcharge, for the Web Transf. column's transfer hint (S3).
  const tnCardPercent = useTnCardPercent(canSeePrices);
  // Productos' "markup con offsets" under the clásica markup: the offsets are about the cost, so only with the margin.
  // Not in the tree, which has no price columns (a panel's Precios tab asks its own).
  const listOffsets = useListOffsets(canSeePrices && canSeeMargin && !agrupado);
  // The rows checked for the bulk actions: a publication checks itself, a product row (Producto view) its product.
  // As in Productos (S12d), Shift+click checks a range of the rows on show, the title header checks the page, and the
  // selection outlives a filter, page or view change. The Agrupado tree keeps its rows to itself: no range nor page.
  const listedRows = useMemo(
    () =>
      producto
        ? productRows.rows.map((row) => selectionRow(row.type === 'node' ? row.node : row.type === 'item' ? row.item : null))
        : (data?.items ?? EMPTY_ROWS).map(selectionRow),
    [producto, productRows.rows, data],
  );
  const rowSelection = useRowSelection(agrupado ? EMPTY_ROWS : listedRows);
  const { checked: checkedRows, productIds: checkedIds, itemIds: checkedItemIds, clear: clearChecked } = rowSelection;
  // Pause / activate act on exactly the checked rows: each checked publication, and every publication of a checked
  // product row (S2); never the other publications of a checked publication's product.
  const checkedStatus = useMemo(
    () => ({
      itemIds: checkedItemIds,
      productIds: [...checkedRows.values()].filter((row) => !row.itemId).map((row) => row.productId),
    }),
    [checkedRows, checkedItemIds],
  );
  // A price typed in a cell (S11c), and the rebate / web transfer edited in theirs (S1), are saved as Productos does;
  // the list is reloaded after it, as after a panel write (its prices with it).
  const priceEditor = useInlinePriceEdit({ onWritten: reloadList });
  const { message: priceMessage } = priceEditor;
  useEffect(() => {
    if (priceMessage) showToast(priceMessage.text, priceMessage.tone === 'ok' ? 'success' : 'error');
  }, [priceMessage, showToast]);
  const priceWritePermissions = useMemo(() => pricePermissions(tienePermiso), [tienePermiso]);
  // Productos' pricing modal (P3c), with Productos' own gate (`puedeEditar`): any price edit or rebate/web toggle.
  const canCalculatePrice = ['canEditClasica', 'canEditMlCuotas', 'canToggleRebate', 'canToggleWebTransf'].some(
    (flag) => priceWritePermissions[flag],
  );
  // Productos' Auto-recalcular cuotas (S12f2), where a price can be written: button and Alt+R, as in Productos.
  const autoRecalc = useRecalcularCuotasAuto();
  const [pricingProduct, setPricingProduct] = useState(null);
  const priceEdit = useMemo(
    () => ({ permissions: priceWritePermissions, onSave: priceEditor.save, onToggle: priceEditor.editToggle, saving: priceEditor.saving }),
    [priceWritePermissions, priceEditor.save, priceEditor.editToggle, priceEditor.saving],
  );
  // What the panels' Precios tab takes from the list: Calcular (Productos' pricing modal), the Tienda Nube card
  // surcharge and the reload counter its prices are read again with.
  const priceGroup = useMemo(
    () => ({ onCalculate: canCalculatePrice ? setPricingProduct : null, tnCardPercent, version: reloadToken }),
    [canCalculatePrice, tnCardPercent, reloadToken],
  );
  const cyclePriceMode = () => {
    const next = PRICE_MODES[(PRICE_MODES.indexOf(filters.modo) + 1) % PRICE_MODES.length];
    setFilters({ modo: next === PRICE_MODES[0] ? '' : next });
  };

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
        priceMode: filters.modo,
        // Productos' price columns live in the Precios view only (owner, 2026-10-28).
        prices: canSeePrices && precios ? listPrices : null,
        priceEdit,
        onCalculatePrice: canCalculatePrice ? setPricingProduct : null,
        priceOffsets: listOffsets,
        tnCardPercent,
      }),
    [
      eventsEnabled,
      canSeeMargin,
      canSeeSales,
      expandedIds,
      toggleVariations,
      agrupado,
      producto,
      filters.agrupar,
      filters.familias,
      skuDivergence,
      filters.modo,
      canSeePrices,
      listPrices,
      precios,
      priceEdit,
      canCalculatePrice,
      listOffsets,
      tnCardPercent,
    ],
  );

  // In mode: fixed S3 preset overlay (user picker choices come back on exit).
  const columnVisibility = useMemo(() => {
    if (!ponerPreciosMode) return baseColumnVisibility;
    return visibilityForPonerPreciosMode(columns.map((column) => column.key));
  }, [ponerPreciosMode, baseColumnVisibility, columns]);

  const togglePonerPreciosMode = () => {
    if (ponerPreciosMode) {
      setPonerPreciosMode(false);
      setFiltersCollapsed(false);
      const prior = vistaBeforeMode.current;
      vistaBeforeMode.current = null;
      if (prior != null && prior !== filters.vista) {
        setFilters({ vista: prior === 'publicacion' ? '' : prior, mla: '' });
      }
      return;
    }
    vistaBeforeMode.current = filters.vista;
    if (filters.vista !== 'publicacion') {
      setFilters({ vista: '', mla: '' });
    }
    setFiltersCollapsed(false);
    setPonerPreciosMode(true);
  };

  // The kit's ColumnPicker is TanStack-shaped; this table is the kit's, so a
  // row-less table instance carries only the visibility state both read.
  const columnDefs = useMemo(
    () => columns.map((column) => ({ id: column.key, header: column.label ?? column.header, enableHiding: column.key !== 'titulo' })),
    [columns],
  );
  const pickerTable = useReactTable({
    data: EMPTY_ROWS,
    columns: columnDefs,
    state: { columnVisibility: baseColumnVisibility },
    onColumnVisibilityChange: setColumnVisibility,
    getCoreRowModel: getCoreRowModel(),
  });
  const visibleColumns = useMemo(
    () => columns.filter((column) => columnVisibility[column.key] !== false),
    [columns, columnVisibility],
  );
  const selection = useMemo(
    () => ({ checked: checkedRows, onToggle: rowSelection.onToggle, togglePage: rowSelection.togglePage, pageState: rowSelection.pageState }),
    [checkedRows, rowSelection.onToggle, rowSelection.togglePage, rowSelection.pageState],
  );
  const selectableColumns = useMemo(() => withRowSelection(visibleColumns, selection), [visibleColumns, selection]);

  // What the list really applies: a sort the user may not ask for (a shared link) falls back on the default --
  // the listing type, then Facturado 30D for who sees the sales (like Métricas) or the activity otherwise.
  // The Producto view sorts the products by their own figures (`effectiveProductSort`).
  const sort = producto ? productRows.sort : headerSort(effectiveSortKeys(filters, { canSeeSales, canSeeMargin }));
  // The product panel's open tab outlives the panel, which unmounts while one of its publications is open, so
  // "Volver" lands on the tab it left. Only for that trip: picking a product, or closing the panel (the close
  // button or a filter change), starts it again on its first tab.
  const [productTab, setProductTab] = useState(null);
  if (!filters.prod && productTab) setProductTab(null);
  // A publication's panel takes the place of its product's (`sel` over `prod`); closing either closes the panel.
  const closePanel = () => {
    setCompetenciaWide(false);
    setFilters({ sel: '', tab: '', prod: '' });
  };

  useEffect(() => {
    setCompetenciaWide(false);
  }, [filters.sel, filters.tab]);
  const selectProduct = (key) => {
    setProductTab(null);
    setFilters({ prod: key, sel: '', tab: '' });
  };
  const selectProductItem = (itemId) => setFilters({ sel: itemId, tab: '' });
  const backToProduct = () => setFilters({ sel: '', tab: '' });
  const backLabel = filters.prod
    ? productRows.rows.find((row) => row.type === 'node' && row.node.key === filters.prod)?.node.label
    : undefined;
  const changeTab = (tab) => setFilters({ tab });
  // Shift+click adds a column to the sort, like Productos: any column, the markup and Métricas' figures included.
  const handleSort = (key, event) => {
    if (event?.shiftKey) window.getSelection()?.removeAllRanges(); // Shift+click also extends the text selection
    setFilters(sortParams(nextSort(sort.keys, key, { shift: Boolean(event?.shiftKey) })));
  };

  // Ctrl/Cmd+click opens the publication in ML, Alt+click in the seller panel
  // and Shift+click its promotions, all in the extension's side panel when it
  // is there (a new tab otherwise); a plain click selects the row. A
  // publication without a usable permalink (or MLA) opens nothing, and is not
  // selected either.
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
        openInMlPanel(sellerUrl(item.item_id));
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
  const activeFilterKeys = activeKeys.filter((key) => (Array.isArray(filters[key]) ? filters[key].length > 0 : filters[key] !== ''));
  const hasActiveFilters = activeFilterKeys.length > 0;
  // The phone's "Filtros (n)": the filters on, the search apart (it has its own box).
  const filterCount = activeFilterKeys.filter((key) => key !== 'q').length;

  const items = data?.items ?? EMPTY_ROWS;
  // The copy shortcuts act on the focused publication of the list (the Producto and Agrupado rows load their own).
  const paintProduct = usePaintProduct({ equipo: rowFilters.equipo, onPainted: colorOverlay.apply, showToast });
  const paintPublication = usePaintPublication({ equipo: rowFilters.equipo, onPainted: colorOverlay.applyOwn, showToast });
  // The product of a focused row: a publication's linked product, or the product row itself (Producto view). The
  // Agrupado tree keeps its rows to itself.
  const productIdOfRow = (key) => {
    const row = producto ? productRows.rows.find((candidate) => candidate.id === key) : null;
    return producto
      ? row?.type === 'node'
        ? row.node.productoItemId
        : row?.item?.link?.producto_item_id
      : items.find((item) => item.item_id === key)?.link?.producto_item_id;
  };
  // Ctrl+I: Productos' information modal of the focused row's product.
  const [infoProductId, setInfoProductId] = useState(null);
  const showInfo = (key) => {
    if (agrupado) {
      showToast('La información del producto funciona en las vistas Publicaciones, Precios y Producto', 'error');
      return;
    }
    const productId = productIdOfRow(key);
    if (productId == null) {
      showToast('La publicación no tiene producto vinculado', 'error');
      return;
    }
    setInfoProductId(productId);
  };
  // A digit paints the focused row as what it is (S3, S4): a publication alone, never its product; a product row
  // (Producto view) its product.
  const paintRow = (key, color) => {
    if (agrupado) {
      showToast('Pintar con el teclado funciona en las vistas Publicaciones, Precios y Producto', 'error');
      return;
    }
    const { itemId, productId } = selectionOfRow(key);
    if (itemId) paintPublication(itemId, color);
    else if (productId != null) paintProduct(productId, color);
    else if (producto && productRows.rows.find((row) => row.id === key)?.type === 'node') {
      // The "Sin producto" row: no product to paint, its publications are painted one by one.
      showToast('Las publicaciones sin producto se pintan de a una: abrí la fila', 'error');
    }
  };
  // The selection entry of a focused row. In the Producto view only a product or a publication row: its "more" and
  // state rows are focusable too, and check nothing.
  const selectionOfRow = (key) => {
    if (!producto) return selectionRow(items.find((item) => item.item_id === key));
    const row = productRows.rows.find((candidate) => candidate.id === key);
    return selectionRow(row?.type === 'node' ? row.node : row?.type === 'item' ? row.item : null);
  };
  const extendRow = (key) => {
    const { key: rowKey } = selectionOfRow(key);
    if (rowKey != null) rowSelection.extendTo(rowKey);
  };
  // r / w / o (S9): flip the focused row's product rebate, web transfer or "fuera de tarjetas", as in Productos. They
  // write from the product's own figures (its stored percentages), so they wait for its prices.
  const toggleRow = (key, kind) => {
    const [permission, name] = TOGGLE_PERMISSION[kind];
    if (!priceWritePermissions[permission]) {
      showToast(`No tenés permiso para cambiar ${name}`, 'error');
      return;
    }
    const productId = productIdOfRow(key);
    if (productId == null) {
      showToast('La publicación no tiene producto vinculado', 'error');
      return;
    }
    const product = listPrices.byId.get(productId);
    if (!product) {
      showToast('Los precios del producto todavía no están cargados', 'error');
      return;
    }
    priceEditor.toggle(kind, product);
  };
  // F6 / F7 step through [Global, ...the user's teams], wrapping around, as in Productos.
  const cycleLayer = (delta) => {
    const teams = equipos.filter((equipo) => !equipo.es_global);
    const layers = ['', ...teams.map((equipo) => String(equipo.id))];
    if (layers.length <= 1) return;
    const next = layers[(Math.max(0, layers.indexOf(filters.equipo)) + delta + layers.length) % layers.length];
    setFilters({ equipo: next });
    showToast(`Capa: ${next ? teams.find((equipo) => String(equipo.id) === next).nombre : 'Global'}`, 'info');
  };
  // Ctrl+K / Ctrl+Shift+P ask BulkActions for a modal; `at` makes each press a new request.
  const [bulkRequest, setBulkRequest] = useState(null);
  const filterCardRef = useRef(null);
  const openFilter = (name) => filterCardRef.current?.querySelector(`[data-filter="${name}"]`)?.click();
  const { navigating } = usePublicacionesMLKeyboard({
    searchRef,
    onBulkAction: (key) => setBulkRequest({ key, at: performance.now() }),
    onOpenFilter: openFilter,
    onPaintRow: paintRow,
    onCycleLayer: cycleLayer,
    onCycleMode: canSeePrices && precios ? cyclePriceMode : undefined,
    onToggleRow: canSeePrices && !agrupado ? toggleRow : undefined,
    // Shift+Up / Shift+Down check the row moved to, from the last row checked (S12d, as in Productos).
    onExtendRow: agrupado ? undefined : extendRow,
    findRow: (key) => (ownRows ? undefined : items.find((item) => item.item_id === key)),
    // While an export runs the key is still taken from the browser, and starts nothing.
    onExport: canExportVista(filters.vista) ? () => !exporting && handleExport() : undefined,
    onToggleAutoRecalc: canCalculatePrice ? autoRecalc.toggle : undefined,
    onShowInfo: showInfo,
    onToggleHelp: () => setShowShortcuts((open) => !open),
    // The open side panel takes Escape first (closing it gives its row the focus back).
    keepRowOnEscape: Boolean(filters.sel || filters.prod),
    showToast,
  });
  const total = producto ? productRows.total : (data?.total ?? 0);
  const unit = producto ? 'productos' : 'publicaciones';
  const offset = pageOffset(filters.pagina, pageSize);
  const emptyMessage = data?.data_state?.store_empty
    ? 'Todavía no hay publicaciones sincronizadas'
    : hasActiveFilters
      ? 'Ninguna publicación coincide con los filtros'
      : 'No hay publicaciones';

  // Each group's "Todas" is its own facet total (the rows without that group's selection), never the list's total:
  // choosing "Eliminadas" must not turn "Todas" into the deleted count.
  const chipGroup = (label, key, options, labels, axis, tones) => (
    <FacetChips
      label={label}
      tones={tones}
      options={options}
      labels={labels}
      counts={facets?.[axis]}
      total={facets?.totals?.[axis]}
      activeValue={activeOf(filters[key])}
      onChange={csvChange(key)}
    />
  );

  const estadoGroup = (
    <div className={styles.filterGroup}>
      <span className={styles.filterLabel}>Estado</span>
      {chipGroup('Filtrar por estado', 'estado', STATUS_OPTIONS, STATUS_LABELS, 'status', STATUS_TONES)}
    </div>
  );
  // The layer and what paints on it wrap together.
  const layerGroup = (
    <div className={styles.filterGroup}>
      <ColorLayerSelect
        value={filters.equipo}
        onChange={(equipo) => setFilters({ equipo })}
        equipos={equipos}
        loaded={equiposLoaded}
        labelClassName={styles.filterLabel}
      />
      <PaintColorMenu
        checked={checkedStatus}
        offPageCount={agrupado ? 0 : rowSelection.offPageCount}
        equipo={rowFilters.equipo}
        onPainted={colorOverlay.apply}
        onPaintedOwn={colorOverlay.applyOwn}
        onClearChecked={clearChecked}
      />
      {/* Icon-only: the toolbar's first row has no room for a label at 1366 px. The phone's filters sheet has room
          for its word. */}
      <button
        type="button"
        className={`btn-tesla ${isPhone ? '' : 'icon-only '}sm ${buttonStyles.quiet}`}
        onClick={() => setEquiposOpen(true)}
        aria-label="Equipos"
        title="Equipos: crear y administrar tus equipos"
      >
        <Users size={14} aria-hidden="true" />
        {isPhone && 'Equipos'}
      </button>
      {/* Closing reloads the teams, so the layer offers what was just created, renamed or deleted. */}
      <EquiposModal
        isOpen={equiposOpen}
        onClose={() => {
          setEquiposOpen(false);
          recargarEquipos();
        }}
      />
    </div>
  );
  const filterBands = (
    <>
      <div className={styles.filterBand} hidden={ponerPreciosMode && filtersCollapsed}>
        <div className={styles.filterGroup}>
          <span className={styles.filterLabel}>Tipo</span>
          {chipGroup('Filtrar por tipo', 'tipo', TIPO_OPTIONS, TIPO_LABELS, 'listing')}
        </div>
        <div className={styles.filterGroup}>
          <span className={styles.filterLabel}>Vínculo</span>
          {chipGroup('Filtrar por vínculo', 'vinculo', VINCULO_OPTIONS, VINCULO_LABELS, 'link')}
        </div>
        <div className={styles.filterGroup}>
          <span className={styles.filterLabel}>Stock</span>
          {chipGroup('Filtrar por stock', 'stock', STOCK_OPTIONS, STOCK_LABELS, 'stock')}
        </div>
      </div>
      <div className={styles.filterBand} hidden={ponerPreciosMode && filtersCollapsed}>
        <div className={styles.filterGroup}>
          <span className={styles.filterLabel}>Tienda</span>
          <FacetChips
            label="Filtrar por tienda oficial"
            {...storeChips}
            total={facets?.totals?.stores}
            onChange={csvChange('tiendas')}
          />
        </div>
        {layerGroup}
        {/* Productos' color filter, on the layer on show (Capa). */}
        <div className={styles.filterGroup}>
          <span className={styles.filterLabel}>Color</span>
          <ColorFilterChips value={filters.colores} onChange={(colores) => setFilters({ colores })} />
        </div>
      </div>
      <div className={styles.filterBand} hidden={ponerPreciosMode && filtersCollapsed}>
        <ProductFilters filters={filters} setFilters={setFilters} labelClassName={styles.filterLabel} facet={facets?.product ?? null} />
        {/* Same band as the product filters, behind a button: a band of its own pushed the list's header below
            the fold at 1366x768. */}
        <PresenceFilters filters={filters} setFilters={setFilters} canSeeMargin={canSeeMargin} />
        <AuditFilters filters={filters} setFilters={setFilters} />
        <PromoFilters filters={filters} setFilters={setFilters} />
        {/* Productos' price columns (S11): how the rows are looked at, like the Capa; the header has no room left. */}
        {canSeePrices && precios && (
          <PriceModeSelect
            value={filters.modo}
            onChange={(value) => setFilters({ modo: value === PRICE_MODES[0] ? '' : value })}
            labelClassName={styles.filterLabel}
          />
        )}
      </div>
      {showMarkupFilters && (
        <div className={styles.filterBand} hidden={ponerPreciosMode && filtersCollapsed}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Markup</span>
            <MarkupFilters
              negative={filters.markup_neg === '1'}
              min={filters.markup_min}
              max={filters.markup_max}
              onChange={setFilters}
            />
          </div>
        </div>
      )}
    </>
  );
  const detailPanel = filters.sel ? (
      <PublicationPanel
        itemId={filters.sel}
        tab={filters.tab}
        onTabChange={changeTab}
        onClose={closePanel}
        onListReload={reloadList}
        dataState={data?.data_state}
        onBack={filters.prod ? backToProduct : undefined}
        backLabel={backLabel}
        priceGroup={canSeePrices ? priceGroup : null}
        ponerPreciosMode={ponerPreciosMode}
        competenciaWide={competenciaWide}
        onCompetenciaWideChange={setCompetenciaWide}
      />
    ) : filters.prod ? (
      <ProductPanel
        filters={rowFilters}
        productKey={filters.prod}
        onClose={closePanel}
        onSelectItem={selectProductItem}
        canSeeSales={canSeeSales}
        canSeeMargin={canSeeMargin}
        onListReload={reloadList}
        priceGroup={canSeePrices ? priceGroup : null}
        tabState={productTab}
        onTabStateChange={setProductTab}
      />
    ) : null;
  // The tree asks on mount: it waits for the layer like the other views.
  const agrupadoTable = !layerPending && (
    <AgrupadoTable
      columns={selectableColumns}
      filters={rowFilters}
      familias={filters.familias === '1'}
      dimension={filters.agrupar}
      colorOverlay={colorOverlay.colors}
      ownColorOverlay={colorOverlay.own}
      canSeeMargin={canSeeMargin}
      expandedIds={expandedIds}
      onSelectItem={handleRowClick}
      selectedKey={filters.sel || undefined}
      offset={TABLE_OFFSET}
      emptyMessage={emptyMessage}
      columnWidths={treeSizing.columnWidths}
      onColumnResize={treeSizing.onColumnResize}
    />
  );
  const overlays = (
    <>
      {showShortcuts && <ShortcutsHelp onClose={() => setShowShortcuts(false)} />}
      {/* Productos' "Modo Navegación" notice, without a toast over the rows: the "?" key by the filters lights up,
          and this line tells a screen reader. */}
      {navigating && (
        <div className={styles.srOnly} role="status">
          Modo navegación activo: Esc para salir, ? para ver los atajos
        </div>
      )}
      <ModalInfoProducto isOpen={infoProductId != null} itemId={infoProductId} onClose={() => setInfoProductId(null)} />
      {priceEditor.pending && (
        <ModalTesla
          isOpen
          onClose={priceEditor.saving ? () => {} : priceEditor.cancel}
          title={priceEditor.pending.kind === 'zero' ? 'Borrar precio' : 'Markup negativo'}
          size="sm"
          footer={
            <ModalFooterButtons
              // A write on its way finishes anyway: the confirmation stays until it does.
              onCancel={priceEditor.saving ? () => {} : priceEditor.cancel}
              onConfirm={priceEditor.confirm}
              confirmText={priceEditor.pending.kind === 'zero' ? 'Borrar el precio' : 'Guardar igual'}
              confirmLoading={priceEditor.saving}
            />
          }
        >
          <p>{priceEditor.warning}</p>
        </ModalTesla>
      )}
      <PricingModalTesla
        isOpen={Boolean(pricingProduct)}
        producto={pricingProduct}
        onClose={() => setPricingProduct(null)}
        onSave={() => {
          setPricingProduct(null);
          reloadList();
        }}
      />
      {priceListsOpen && (
        <ExportModal
          onClose={() => setPriceListsOpen(false)}
          filtrosActivos={{}}
          showToast={showToast}
          resolverProductos={resolvePriceListProducts}
          descripcionConjunto={PRICE_LIST_SET}
        />
      )}
      <Toast toast={toast} onClose={hideToast} />
    </>
  );

  const listErrorBar = error && (
    <div className={styles.errorBar} role="alert">
      <ShieldAlert size={16} aria-hidden="true" />
      <span className={styles.errorText}>{describeError(error)}</span>
      <button type="button" className="btn-tesla outline sm" onClick={() => setReloadToken((token) => token + 1)}>
        Reintentar
      </button>
    </div>
  );
  const pagination = (
      <Pagination
        total={total}
        offset={offset}
        pageSize={pageSize}
        pageSizeOptions={PAGE_SIZES}
        pageSizeLabel={pageSizeLabel}
        allRowsSize={ALL_ROWS}
        summary={
          <span>
            mostrando {total === 0 ? 0 : offset + 1}-{pageSize === ALL_ROWS ? total : Math.min(offset + pageSize, total)}{' '}
            de {total} {unit}
          </span>
        }
        onOffsetChange={(next) => setFilters({ pagina: Math.floor(next / pageSize) + 1 })}
        onPageSizeChange={(size) => setFilters({ limite: size === PAGE_SIZE ? '' : size })}
      />
  );

  if (isPhone) {
    const phoneRows = producto ? productRows.rows.filter((row) => row.type === 'node').map((row) => row.node) : items;
    const remaining = producto ? 0 : total - offset - items.length;
    const listPhase = error && !ownRows ? 'error' : !data && !ownRows ? 'loading' : 'ready';
    return (
      <div className={phoneStyles.page}>
        <PhoneToolbar
          ref={searchRef}
          filters={filters}
          setFilters={setFilters}
          filterCount={filterCount}
          showMarkupFilters={showMarkupFilters}
          onOpenFilters={() => setPhoneSheet('filtros')}
          onOpenMenu={() => setPhoneSheet('acciones')}
          searchPlaceholder="Título, MLA, SKU/EAN o producto"
        />
        <div className={phoneStyles.banners}>
          {exportError && (
            <div className={styles.errorBar} role="alert">
              <ShieldAlert size={16} aria-hidden="true" />
              <span className={styles.errorText}>{exportError}</span>
            </div>
          )}
          <SheetsNotice notice={exportingSheets ? { processing: true } : sheetsNotice} onClose={() => setSheetsNotice(null)} />
          <StateBanner dataState={data?.data_state} />
          {listErrorBar}
        </div>
        {canSeeKpis && !sinMla && (
          <div className={phoneStyles.kpis}>
            <PublicationKpiStrip
              state={kpis}
              periodo={periodo}
              onPeriodChange={setPeriodo}
              isVisible={kpiVisible}
              markupNotice={showMarkupFilters && hasMarkupFilter(filters)}
            />
          </div>
        )}
        <SplitPanelLayout
          open={Boolean(filters.sel || filters.prod)}
          onClose={closePanel}
          ariaLabel={filters.sel ? 'Detalle de la publicación' : 'Detalle del producto'}
          panel={detailPanel}
        >
          {agrupado ? (
            <div className={phoneStyles.wideTable}>{agrupadoTable}</div>
          ) : listPhase === 'loading' ? (
            <ListSkeleton />
          ) : listPhase === 'ready' ? (
            <PhoneList
              mode={producto ? 'producto' : 'publicacion'}
              rows={phoneRows}
              total={total}
              sort={sort}
              sortOptions={phoneSortOptions({ producto, canSeeSales, canSeeMargin })}
              onSort={(key) => handleSort(key)}
              canSeeSales={canSeeSales}
              canSeeMargin={canSeeMargin}
              selectedKey={producto ? filters.prod : filters.sel}
              onSelect={producto ? selectProduct : handleRowClick}
              emptyMessage={producto ? (hasActiveFilters ? 'Ningún producto coincide con los filtros' : 'No hay productos') : emptyMessage}
              loading={loading || (producto && productRows.loading)}
              footer={
                producto ? (
                  pagination
                ) : (
                  <>
                    {moreError && (
                      <div className={styles.errorBar} role="alert">
                        <ShieldAlert size={16} aria-hidden="true" />
                        <span className={styles.errorText}>No se pudieron traer más publicaciones.</span>
                      </div>
                    )}
                    {remaining > 0 && (
                      <button type="button" className={phoneStyles.more} onClick={loadMoreCards}>
                        Cargar {Math.min(PHONE_CHUNK, remaining)} más
                      </button>
                    )}
                  </>
                )
              }
            />
          ) : null}
        </SplitPanelLayout>
        <PhoneSheet
          open={phoneSheet === 'filtros'}
          title="Filtros"
          onClose={closePhoneSheet}
          headerAction={
            <button type="button" className="btn-tesla ghost sm" onClick={resetFilters} disabled={!hasActiveFilters}>
              Limpiar
            </button>
          }
          footer={
            <button type="button" className={`btn-tesla primary ${phoneStyles.sheetFooter}`} onClick={closePhoneSheet}>
              Ver {formatUnits(total)} {unit}
            </button>
          }
        >
          <div className={styles.phoneFilters}>
            {estadoGroup}
            {filterBands}
          </div>
        </PhoneSheet>
        <PhoneSheet open={phoneSheet === 'acciones'} title="Acciones" onClose={closePhoneSheet}>
          <div className={phoneStyles.menu}>
            {!sinMla && (
              <BulkStatusActions filters={rowFilters} canSeeMargin={canSeeMargin} onDone={reloadList} checked={checkedStatus} />
            )}
            <BulkActions
              filters={rowFilters}
              checkedIds={checkedIds}
              checkedPublications={checkedItemIds.length}
              checkedRowCount={checkedRows.size}
              offPageCount={agrupado ? 0 : rowSelection.offPageCount}
              onClearChecked={clearChecked}
              canSeeMargin={canSeeMargin}
              onDone={reloadList}
              openRequest={bulkRequest}
            />
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
        </PhoneSheet>
        {overlays}
      </div>
    );
  }

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
          {!ponerPreciosMode && (
            <SegmentedControl
              label="Vista"
              options={VISTA_OPTIONS}
              value={filters.vista}
              onChange={(value) => setFilters({ vista: value === 'publicacion' ? '' : value, mla: '' })}
            />
          )}
          {!ponerPreciosMode && agrupado && (
            <SegmentedControl
              label="Agrupar por"
              options={AGRUPAR_OPTIONS}
              value={filters.agrupar}
              onChange={(value) => setFilters({ agrupar: value === AGRUPAR_DIMENSIONS[0] ? '' : value })}
            />
          )}
          {!ponerPreciosMode && agrupado && (
            <SwitchChip
              label="Con familias"
              title="Agrupa las publicaciones de una misma familia dentro de cada producto"
              checked={filters.familias === '1'}
              onChange={(checked) => setFilters({ familias: checked ? '1' : '' })}
            />
          )}
          <BulkActions
            filters={rowFilters}
            checkedIds={checkedIds}
            checkedPublications={checkedItemIds.length}
            checkedRowCount={checkedRows.size}
            offPageCount={agrupado ? 0 : rowSelection.offPageCount}
            onClearChecked={clearChecked}
            canSeeMargin={canSeeMargin}
            onDone={reloadList}
            openRequest={bulkRequest}
          />
          {!sinMla && (
            <BulkStatusActions
              filters={rowFilters}
              canSeeMargin={canSeeMargin}
              onDone={reloadList}
              checked={checkedStatus}
            />
          )}
          <span className={styles.spacer} />
          {!ponerPreciosMode && <ColumnPicker table={pickerTable} iconOnly buttonClassName={quietButton} />}
          {!ponerPreciosMode && kpiOptions.length > 0 && (
            <ColumnPicker
              table={kpiPicker}
              label="Indicadores"
              icon={Gauge}
              groupLabel="Elegir indicadores visibles"
              iconOnly
              buttonClassName={quietButton}
            />
          )}
          <button
            type="button"
            className={`${quietButton} icon-only`}
            aria-pressed={dense}
            aria-label="Filas finas"
            title="Filas finas"
            onClick={toggleDense}
          >
            <Rows4 size={14} />
          </button>
          {canExportVista(filters.vista) && (
            <button
              type="button"
              className={quietButton}
              aria-label={exporting ? 'Exportando…' : 'Exportar CSV'}
              title="Exportar CSV"
              onClick={handleExport}
              disabled={exporting}
            >
              <Download size={14} />
              {exporting ? 'Exportando…' : 'Exportar'}
            </button>
          )}
          {sheetsEnabled && canExportVista(filters.vista) && (
            <button type="button" className={quietButton} onClick={handleSheetsExport} disabled={exportingSheets}>
              <FileSpreadsheet size={14} />
              {exportingSheets ? 'Exportando a Sheets…' : 'Exportar a Sheets'}
            </button>
          )}
          {canExportPriceLists && (
            <button type="button" className={quietButton} onClick={() => setPriceListsOpen(true)}>
              <FileDown size={14} />
              Listas de precios
            </button>
          )}
          {/* The screen's one filled button. */}
          {canPonerPrecios && (
            <button
              type="button"
              className={`btn-tesla sm ${buttonStyles.primary}`}
              aria-pressed={ponerPreciosMode}
              onClick={togglePonerPreciosMode}
            >
              {ponerPreciosMode && <Check size={14} aria-hidden="true" />}
              Poner precios
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

      {!ponerPreciosMode && canSeeKpis && !sinMla && (
        <PublicationKpiStrip
          state={kpis}
          periodo={periodo}
          onPeriodChange={setPeriodo}
          isVisible={kpiVisible}
          markupNotice={showMarkupFilters && hasMarkupFilter(filters)}
        />
      )}

      {!ponerPreciosMode &&
        (publicacion ? (
          <PublicationCountCards facets={facets} filters={filters} onApply={setFilters} />
        ) : (
          <PublicationStatCards
            state={stats}
            filters={filters}
            canSeeMargin={canSeeMargin}
            sinMla={producto}
            onApply={setFilters}
            onReset={resetFilters}
            onRetry={stats.reload}
            markupNotice={showMarkupFilters && hasMarkupFilter(filters)}
          />
        ))}

      <section className={styles.filterCard} aria-label="Filtros" ref={filterCardRef}>
        <div className={styles.filterBand}>
          <div className={styles.searchSlot} title={SEARCH_OPERATORS_HELP}>
            <SearchInput
              ref={searchRef}
              value={filters.q}
              onChange={(value) => setFilters({ q: value })}
              debounce={400}
              placeholder="Buscar título, MLA, SKU/EAN o producto"
            />
          </div>
          {estadoGroup}
          <span className={styles.spacer} />
          {/* The row's tools wrap together, to the right end of the next line when the chips take the width. */}
          <div className={styles.filterTools}>
            {ponerPreciosMode && (
              <button
                type="button"
                className={quietButton}
                aria-expanded={!filtersCollapsed}
                onClick={() => setFiltersCollapsed((collapsed) => !collapsed)}
              >
                <ChevronDown
                  size={14}
                  aria-hidden="true"
                  className={filtersCollapsed ? styles.filterChevronCollapsed : undefined}
                />
                {filtersCollapsed ? 'Mostrar filtros' : 'Minimizar filtros'}
              </button>
            )}
            {canCalculatePrice && (
              <button
                type="button"
                className={quietButton}
                aria-pressed={autoRecalc.enabled}
                title="Recalcular las cuotas al guardar un precio (Alt+R)"
                onClick={autoRecalc.toggle}
              >
                {autoRecalc.enabled ? <Check size={14} aria-hidden="true" /> : null}
                Auto-recalcular
              </button>
            )}
            {/* A still "?" key instead of a notice over the rows: lit while a row has the keyboard (Esc leaves). */}
            <button
              type="button"
              className={`${quietButton} ${styles.shortcutsKey}`}
              data-navigating={navigating ? '' : undefined}
              aria-label="Atajos de teclado"
              title={navigating ? 'Modo navegación: Esc para salir, ? para ver los atajos' : 'Atajos de teclado (?)'}
              onClick={() => setShowShortcuts(true)}
            >
              <kbd aria-hidden="true">?</kbd>
              <span aria-hidden="true">atajos</span>
            </button>
            {hasActiveFilters && (
              <button type="button" className={quietButton} onClick={resetFilters}>
                <FilterX size={14} />
                Limpiar filtros
              </button>
            )}
          </div>
        </div>
        {filterBands}
      </section>

      {listErrorBar}

      {/* In the tree and the Producto view `/items` only brings the state and the facets: its failure leaves their rows (which have their own errors) on screen. */}
      {error && !ownRows ? null : !data && !ownRows ? (
        <ListSkeleton />
      ) : (
        <div className={styles.listArea} aria-busy={loading}>
          <SplitPanelLayout
            open={Boolean(filters.sel || filters.prod)}
            onClose={closePanel}
            width={ponerPreciosMode ? 'md' : competenciaWide ? 'xl' : 'lg'}
            expanded={competenciaWide}
            resizeKey={ponerPreciosMode ? 'publicaciones-ml-poner-precios' : 'publicaciones-ml'}
            ariaLabel={filters.sel ? 'Detalle de la publicación' : 'Detalle del producto'}
            panel={detailPanel}
          >
            {/* The kit's TableShell takes no density: this box marks the table inside it ("Filas finas"). */}
            <div className={styles.tableDensity} data-density={dense ? 'dense' : 'normal'}>
              {producto ? (
                <ProductoTable
                  tree={productRows}
                  virtualizeFrom={virtualizeFrom}
                  onEndReached={pageSize === ALL_ROWS ? productRows.loadMoreProducts : undefined}
                  columns={selectableColumns}
                  selection={selection}
                  colorOverlay={colorOverlay.colors}
                  ownColorOverlay={colorOverlay.own}
                  prearmadasStats={prearmadasStats}
                  listingById={listPrices.byId}
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
                  columnWidths={productSizing.columnWidths}
                  onColumnResize={productSizing.onColumnResize}
                />
              ) : agrupado ? (
                agrupadoTable
              ) : (
                <TableShell
                  columns={selectableColumns}
                  rows={items}
                  getRowKey={(item) => item.item_id}
                  getRowTone={getItemTone}
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
                  columnWidths={listSizing.columnWidths}
                  onColumnResize={listSizing.onColumnResize}
                  virtualizeFrom={virtualizeFrom}
                  onEndReached={lazy ? loadMoreItems : undefined}
                />
              )}
              {lazy && moreError && (
                <div className={styles.errorBar} role="alert">
                  <ShieldAlert size={16} aria-hidden="true" />
                  <span className={styles.errorText}>No se pudieron traer más publicaciones.</span>
                  <button type="button" className="btn-tesla outline sm" onClick={loadMoreItems}>
                    Reintentar
                  </button>
                </div>
              )}
            </div>
          </SplitPanelLayout>
          {!agrupado && (
            <div className={styles.pager}>
              {pagination}
            </div>
          )}
        </div>
      )}
      {overlays}
    </div>
  );
}
