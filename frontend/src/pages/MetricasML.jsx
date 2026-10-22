import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useReactTable, getCoreRowModel } from '@tanstack/react-table';
import { AlertTriangle, Clock, Download, FileSpreadsheet, FilterX, ShieldAlert, TrendingDown } from 'lucide-react';
import api from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';
import DateRangeFilter from '../components/DateRangeFilter';
import SearchInput from '../components/SearchInput';
import ProductFiltersPanel from '../components/shared/ProductFiltersPanel';
import FacetChips from '../components/ventasMl/FacetChips';
import ColumnPicker from '../components/ventasMl/ColumnPicker';
import Pagination from '../components/ventasMl/Pagination';
import SegmentedControl from '../components/metricasMl/SegmentedControl';
import ToggleChips from '../components/metricasMl/ToggleChips';
import SwitchChip from '../components/metricasMl/SwitchChip';
import AdsAppliedBanner from '../components/metricasMl/AdsAppliedBanner';
import AdsKpiBlock from '../components/metricasMl/AdsKpiBlock';
import AdsUnattributedPanel from '../components/metricasMl/AdsUnattributedPanel';
import AdsModeControl from '../components/metricasMl/AdsModeControl';
import MetricasKpiStrip from '../components/metricasMl/MetricasKpiStrip';
import BoardTable from '../components/metricasMl/BoardTable';
import { adsRequestParams } from '../utils/metricasMlAds';
import { TP_SOLO_DIMENSION, tpErrorMessage, tpRequestParams, tpSoloSortKey } from '../utils/metricasMlTp';
import { isTpSolo } from '../components/ventasMl/tpMode';
import { DIMENSION_OPTIONS, buildBoardColumns } from '../components/metricasMl/metricasMlColumns';
import { buildStoreChips } from '../constants/tiendasOficiales';
import { useTiendasOficiales } from '../hooks/useTiendasOficiales';
import { currentMonthRange } from '../utils/dateRangePresets';
import { buildMetricasMLParams } from '../utils/metricasMlParams';
import { nodeId } from '../utils/metricasMlLevels';
import { exportMetricasCsv } from '../utils/ventasMlExport';
import { exportMetricasSheets, isSheetsExportEnabled, loadGoogleIdentity } from '../utils/googleSheetsExport';
import { timeAgo } from '../utils/ventasMlFormat';
import {
  AGEING_BUCKET_TONES,
  AGEING_LABELS,
  AGEING_OPTIONS,
  PUB_STATUS_LABELS,
  PUB_STATUS_OPTIONS,
  PUB_TYPE_LABELS,
  PUB_TYPE_OPTIONS,
  STOCK_LABELS,
  STOCK_OPTIONS,
  formatUnits,
} from '../utils/metricasMlFormat';
import styles from './MetricasML.module.css';

/**
 * Métricas ML — the "stock-market board" of how each PRODUCT sells and
 * earns on Mercado Libre, and which PUBLICATION of it performs best
 * (ODD `metricas-ml-tablero` T4, design `docs/design/metricas-ml/tablero.png`).
 *
 * One request per filter change (`GET /ml-metricas/board`) brings the page
 * of rows, the KPI strip (whole filtered set) and every chip count; a
 * product's publications load when it is expanded, under the SAME filters
 * (`buildMetricasMLParams` is the one place params are built). Margin
 * figures exist only when the backend says `can_see_margin`.
 */

const DEFAULT_PRESET = 'mesActual';
const DEFAULT_PAGE_SIZE = 50;
// Ageing buckets whose rows, by definition, sold nothing in the last 30 days.
const STALE_AGEING_BUCKETS = new Set(['from_31_to_60', 'over_60']);
// The board's period cap (`MAX_PERIOD_DAYS` in `routers/ml_metricas.py`).
const MAX_PERIOD_DAYS = 366;
const PERIOD_LIMIT_MESSAGE = 'El período máximo es de 1 año';
const EMPTY_PRODUCT_FILTERS = { marcas: [], categorias: [], subcategorias: [], pms: [] };
const PERIOD_LABELS = {
  hoy: 'hoy',
  ayer: 'ayer',
  '3d': '3D',
  '7d': '7D',
  '14d': '14D',
  '30d': '30D',
  mesActual: 'mes',
  '3m': '3M',
};
const GROUP_OPTIONS = [
  { value: 'product', label: 'Producto' },
  { value: 'publication', label: 'Publicación' },
  { value: 'group', label: 'Agrupado' },
];
// A node of the "Agrupado" tree opens into the level below it this many rows at
// a time ("Ver más" loads the next page of THAT node).
const GROUP_NODES_PAGE = 100;
const GROUP_NODES_URL = '/ml-metricas/board/group-nodes';
const COMPARE_OPTIONS = [
  { value: 'periodo_anterior', label: 'Período anterior' },
  { value: 'anio_anterior', label: 'Mismo período año pasado' },
];
const ALERTS = [
  { value: 'sin_ventas_30d', label: 'Sin ventas 30d', icon: AlertTriangle, tone: 'warning' },
  { value: 'ageing_60d', label: 'Ageing > 60d', icon: Clock, tone: 'danger' },
  { value: 'margen_cayendo', label: 'Markup cayendo', icon: TrendingDown, tone: 'danger', margin: true },
];

const ROWS_WITHOUT_OPERATIONS_HINT = 'Sin operaciones en el período, pero hay filas de esta tienda con los filtros actuales';

/** The tooltip of each store chip that counts 0 operations but still selects rows (`stores_with_rows`). */
function storeChipHints({ options, counts }, facets) {
  const withRows = new Set(facets?.stores_with_rows ?? []);
  const hints = {};
  for (const value of options) {
    if (!counts?.[value] && value.split(',').some((id) => withRows.has(id))) hints[value] = ROWS_WITHOUT_OPERATIONS_HINT;
  }
  return hints;
}

/** `next` after `previous`, without any row `previous` already has: a metric
 * that moved between two pages shifts the order, and a repeated row would
 * duplicate its React key. */
function appendNew(previous, next) {
  const seen = new Set(previous.map((row) => row.key));
  return [...previous, ...next.filter((row) => !seen.has(row.key))];
}

// Total TP exists only with "Costos TP" on (the backend answers 422 otherwise): turning it off leaves that sort.
function withoutTpSort(sort) {
  return sort.key === 'total_tp' ? { key: 'gross', desc: true } : sort;
}

// The current month in Argentina time, the same default as Ventas ML.
function defaultRange() {
  const { desde, hasta } = currentMonthRange();
  return { desde, hasta };
}

export default function MetricasML() {
  const { permisos, tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('ml_metricas.ver');
  // A `tplink.solo` user (backend P5b): the TP store group with TP costs always on, no Gauss figure, no PM, and
  // "Agrupado" by tienda only. The backend enforces it; the screen offers nothing it would refuse.
  const tpSolo = isTpSolo(permisos);
  const dimensionOptions = tpSolo ? DIMENSION_OPTIONS.filter((option) => option.value === TP_SOLO_DIMENSION) : DIMENSION_OPTIONS;
  // The ads toggle subtracts from Total Gauss and markup: same permission as the backend's (it answers 403 otherwise).
  // A `tplink.solo` user has the profit view without it (backend `_viewer`), so it gets the toggle too.
  const puedeVerGanancia = tpSolo || tienePermiso('ml_metricas.ver_ganancia');
  const latestRequestRef = useRef(0);

  const [range, setRange] = useState(() => ({ ...defaultRange(), filtro: DEFAULT_PRESET }));
  const [compararCon, setCompararCon] = useState('periodo_anterior');
  const [groupBy, setGroupBy] = useState('product');
  // What the "Agrupado" view sums by (ignored by the other views).
  const [dimension, setDimension] = useState('marca');
  const [searchQuery, setSearchQuery] = useState('');
  const [productFilters, setProductFilters] = useState(EMPTY_PRODUCT_FILTERS);
  const [storeFilter, setStoreFilter] = useState('');
  const { tiendas, getLabel } = useTiendasOficiales();
  const [pubStatus, setPubStatus] = useState([]);
  const [pubType, setPubType] = useState([]);
  const [pubStatusExclude, setPubStatusExclude] = useState([]);
  const [pubTypeExclude, setPubTypeExclude] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [stock, setStock] = useState([]);
  const [stockExclude, setStockExclude] = useState([]);
  const [ageing, setAgeing] = useState([]);
  const [ageingExclude, setAgeingExclude] = useState([]);
  // "Solo con ventas en el período": on by default -- a short period shows
  // what sold in it, not the whole catalog (ODD "Período y stock" PS1).
  const [soloConVentas, setSoloConVentas] = useState(true);
  // The ads toggle's position (`off | mla | todo`); a view mode, so "Limpiar filtros" leaves it alone.
  const [publicidad, setPublicidad] = useState('off');
  // "Costos TP" (TP cost on the TP store's operations, Total TP next to Total Gauss): off by default, a view mode
  // like the ads toggle. `tpError` says why the board turned it back off (403 / 503) until it is turned on again.
  const [costosTp, setCostosTp] = useState(false);
  const [tpError, setTpError] = useState(null);
  const [sort, setSort] = useState({ key: 'gross', desc: true });
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const [board, setBoard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [errorKind, setErrorKind] = useState(null);
  // A 422 (a period or filter the board refuses) is the operator's to fix:
  // its message is shown as is, never the generic "error al cargar".
  const [rejectedMessage, setRejectedMessage] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  // What each open row opened into, by node id (the path of keys down to it, so
  // the same key under two parents is two nodes): a product's publications or
  // a node's next level (`{ loading, rows, total, level, fetched, error }`).
  const [subRows, setSubRows] = useState({});
  const [columnVisibility, setColumnVisibility] = useState({});
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(null);
  const [exportingSheets, setExportingSheets] = useState(false);
  // What "Exportar a Sheets" left to say that is not an error: a cancelled popup, or the link to the new sheet (shown even when its tab opened: a browser can block it silently).
  const [sheetsNotice, setSheetsNotice] = useState(null);
  const sheetsEnabled = isSheetsExportEnabled();
  useEffect(() => {
    if (sheetsEnabled) loadGoogleIdentity().catch(() => {}); // ready before the click; a failure shows on the click
  }, [sheetsEnabled]);

  const filterParams = useMemo(
    () => ({
      ...buildMetricasMLParams({
        fechaDesde: range.desde,
        fechaHasta: range.hasta,
        compararCon,
        groupBy,
        dimension,
        searchQuery,
        productFilters,
        storeFilter,
        pubStatus,
        pubType,
        pubStatusExclude,
        pubTypeExclude,
        alerts,
        stock,
        stockExclude,
        ageing,
        ageingExclude,
        soloConVentas,
        tpSolo,
      }),
      ...adsRequestParams(puedeVerGanancia ? publicidad : 'off'),
      ...tpRequestParams(tpSolo || (puedeVerGanancia && costosTp)),
    }),
    [
      range,
      compararCon,
      groupBy,
      dimension,
      searchQuery,
      productFilters,
      storeFilter,
      pubStatus,
      pubType,
      pubStatusExclude,
      pubTypeExclude,
      alerts,
      stock,
      stockExclude,
      ageing,
      ageingExclude,
      soloConVentas,
      publicidad,
      costosTp,
      puedeVerGanancia,
      tpSolo,
    ],
  );

  // Changing WHAT is filtered resets WHERE you are: page 1, nothing open.
  const withReset = (setter) => (...args) => {
    setter(...args);
    setOffset(0);
  };

  // A request with TP costs the API refuses (403 without the profit view, 503 without a TP store): say why and
  // turn the toggle off, which reloads the board without them. True when it handled the failure. A `tplink.solo`
  // user has no toggle: the failure is the board's own.
  const rejectTp = useCallback((params, err) => {
    const message = params.costos_tp && !tpSolo ? tpErrorMessage(err?.response?.status) : null;
    if (!message) return false;
    setTpError(message);
    setCostosTp(false);
    setSort(withoutTpSort);
    setOffset(0);
    return true;
  }, [tpSolo]);

  // A Total Gauss sort picked before `tplink.solo` arrived is a Total TP sort from then on: the stored key follows,
  // so the Total TP header's click flips the direction instead of starting over (set during render, no stale commit).
  const normalizedSortKey = tpSoloSortKey(sort.key, tpSolo);
  if (normalizedSortKey !== sort.key) setSort({ ...sort, key: normalizedSortKey });
  const sortKey = normalizedSortKey;

  const cargar = useCallback(async () => {
    if (!puedeVer) return;
    const requestId = ++latestRequestRef.current;
    setLoading(true);
    setErrorKind(null);
    const params = { ...filterParams, sort: sortKey, sort_dir: sort.desc ? 'desc' : 'asc', limit: pageSize, offset };
    try {
      const { data } = await api.get('/ml-metricas/board', { params });
      if (requestId !== latestRequestRef.current) return;
      setBoard(data);
      setExpanded(new Set());
      setSubRows({});
    } catch (err) {
      if (requestId !== latestRequestRef.current) return;
      if (rejectTp(params, err)) return;
      const status = err?.response?.status;
      if (status === 422) {
        const data = err.response.data;
        setRejectedMessage(data?.error?.message || data?.detail || PERIOD_LIMIT_MESSAGE);
        setErrorKind('rejected');
      } else {
        setErrorKind(status === 403 ? 'forbidden' : 'generic');
      }
      setBoard(null);
    } finally {
      if (requestId === latestRequestRef.current) setLoading(false);
    }
  }, [puedeVer, filterParams, sortKey, sort.desc, pageSize, offset, rejectTp]);

  useEffect(() => {
    cargar();
  }, [cargar]);

  // Opens or closes a row and loads what it opens into: a product's
  // publications, or the level below a node of the "Agrupado" tree. `path` is
  // the keys from the top down to the row (just its own for a top-level row);
  // `more` asks for the next page of that node.
  const toggleExpand = useCallback(
    async (row, { more = false, path = [row.key] } = {}) => {
      const id = nodeId(path);
      const isGroup = groupBy === 'group';
      if (!more) {
        setExpanded((prev) => {
          const next = new Set(prev);
          if (next.has(id)) next.delete(id);
          else next.add(id);
          return next;
        });
      }
      // A loaded (or loading) answer is reused; a FAILED one is not, so
      // collapsing and expanding again retries.
      const cached = subRows[id];
      if (!more && (expanded.has(id) || (cached && !cached.error))) return;
      // The board's request generation: `cargar` bumps it on every filter
      // change and resets the sub-rows. An answer that arrives after that
      // belongs to the OLD filters and is dropped, never cached.
      const generation = latestRequestRef.current;
      const previous = more ? cached?.rows || [] : [];
      // How many rows the SERVER has handed out (dropped repeats included).
      const fetched = more ? cached?.fetched || 0 : 0;
      const level = more ? cached?.level : undefined;
      setSubRows((prev) => ({ ...prev, [id]: { ...(more ? prev[id] : {}), loading: true, rows: previous, level } }));
      try {
        const request = isGroup
          ? api.get(GROUP_NODES_URL, {
              params: {
                ...filterParams,
                path: id,
                sort: sortKey,
                sort_dir: sort.desc ? 'desc' : 'asc',
                limit: GROUP_NODES_PAGE,
                offset: fetched,
              },
            })
          : api.get(`/ml-metricas/board/products/${row.product_item_id}/publications`, { params: filterParams });
        const { data } = await request;
        if (generation !== latestRequestRef.current) return;
        setSubRows((prev) => ({
          ...prev,
          [id]: {
            loading: false,
            rows: appendNew(previous, data.rows || []),
            total: data.total,
            level: data.level,
            fetched: fetched + (data.rows || []).length,
          },
        }));
      } catch (err) {
        if (generation !== latestRequestRef.current) return;
        // A TP refusal also turns "Costos TP" off (its message in the bar); the row still leaves "loading" for its
        // error note, so it never sticks there if the board reload is slow or fails.
        rejectTp(filterParams, err);
        setSubRows((prev) => ({ ...prev, [id]: { loading: false, rows: previous, level, fetched, error: true } }));
      }
    },
    [expanded, subRows, filterParams, groupBy, sortKey, sort.desc, rejectTp],
  );

  const handleSort = useCallback((key) => {
    setSort((prev) => ({ key, desc: prev.key === key ? !prev.desc : key !== 'title' }));
    setOffset(0);
  }, []);

  // The CSV follows the board's "Publicidad" position and "Costos TP" (filterParams carries each only when on).
  const exportParams = { ...filterParams, sort: sortKey, sort_dir: sort.desc ? 'desc' : 'asc' };

  const handleExport = async () => {
    setExporting(true);
    setExportError(null);
    setSheetsNotice(null);
    try {
      await exportMetricasCsv(exportParams);
    } catch (err) {
      setExportError(err.message);
    } finally {
      setExporting(false);
    }
  };

  // The same file, as a new Google Sheet. Called straight from the click: the Google popup needs it.
  const handleSheetsExport = async () => {
    setExportingSheets(true);
    setExportError(null);
    setSheetsNotice(null);
    try {
      const { url } = await exportMetricasSheets(exportParams);
      setSheetsNotice({ url });
    } catch (err) {
      if (err.cancelled) setSheetsNotice({ text: err.message });
      else setExportError(err.message);
    } finally {
      setExportingSheets(false);
    }
  };

  const clearFilters = () => {
    setRange({ ...defaultRange(), filtro: DEFAULT_PRESET });
    setSearchQuery('');
    setProductFilters(EMPTY_PRODUCT_FILTERS);
    setStoreFilter('');
    setPubStatus([]);
    setPubType([]);
    setPubStatusExclude([]);
    setPubTypeExclude([]);
    setAlerts([]);
    setStock([]);
    setStockExclude([]);
    setAgeing([]);
    setAgeingExclude([]);
    setSoloConVentas(true);
    setOffset(0);
  };

  const canSeeMargin = Boolean(board?.can_see_margin);
  // `kpis.ads` exists only while the board subtracts ads.
  const ads = board?.kpis?.ads ?? null;
  const adsOn = canSeeMargin && ads !== null;
  // `kpis.total_tp` exists only while the board shows the TP costs.
  const tpOn = canSeeMargin && Boolean(board?.kpis?.total_tp);
  const periodLabel = PERIOD_LABELS[range.filtro] || 'período';
  const shownDimension = tpSolo ? TP_SOLO_DIMENSION : dimension;
  const columnDefs = useMemo(
    () => buildBoardColumns({ canSeeMargin, periodLabel, groupBy, dimension: shownDimension, adsOn, tpOn, tpSolo }),
    [canSeeMargin, periodLabel, groupBy, shownDimension, adsOn, tpOn, tpSolo],
  );
  const table = useReactTable({
    data: [],
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
    state: { columnVisibility },
    onColumnVisibilityChange: setColumnVisibility,
  });
  const byId = Object.fromEntries(columnDefs.map((col) => [col.id, col]));
  const visibleColumns = table
    .getVisibleLeafColumns()
    .map((col) => byId[col.id])
    .filter(Boolean);

  const facets = board?.facets;
  const hasActiveFilters = Boolean(
    range.filtro !== DEFAULT_PRESET ||
      searchQuery ||
      storeFilter ||
      productFilters.marcas.length ||
      productFilters.categorias.length ||
      productFilters.subcategorias.length ||
      productFilters.pms.length ||
      pubStatus.length ||
      pubType.length ||
      pubStatusExclude.length ||
      pubTypeExclude.length ||
      alerts.length ||
      stock.length ||
      stockExclude.length ||
      ageing.length ||
      ageingExclude.length ||
      !soloConVentas,
  );
  const noun = { publication: 'publicaciones', group: 'grupos' }[groupBy] ?? 'productos';
  // Asking FOR stale rows (an included 31-60 or > 60 d chip) while the
  // toggle hides rows with no sale in the period mostly comes back empty:
  // say so -- never flip the toggle behind the operator's back. Excluding
  // chips or "Hasta 30 d" ask for no stale rows: no warning.
  const storeChips = buildStoreChips({ tiendas, getLabel, counts: facets?.stores, selected: storeFilter, facetExtras: false });
  const hidesStale = soloConVentas && ageing.some((bucket) => STALE_AGEING_BUCKETS.has(bucket));
  const rows = board?.rows || [];
  const total = board?.total ?? 0;
  const freshness = timeAgo(board?.refreshed_at);

  if (!puedeVer) {
    return (
      <div className={styles.container}>
        <div className={styles.errorBar}>
          <ShieldAlert size={16} /> No tenés permiso para ver Métricas ML.
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <h1>Métricas ML</h1>
          <p className={styles.description}>
            Rendimiento y rentabilidad por producto y publicación en Mercado Libre Argentina
          </p>
        </div>
        <div className={styles.headerActions}>
          {freshness && (
            <span className={styles.freshness}>
              <span className={styles.freshnessDot} aria-hidden="true" />
              actualizado {freshness}
            </span>
          )}
          <ColumnPicker table={table} />
          <button type="button" className="btn-tesla outline sm" onClick={handleExport} disabled={exporting}>
            <Download size={14} />
            {exporting ? 'Exportando…' : 'Exportar CSV'}
          </button>
          {sheetsEnabled && (
            <button type="button" className="btn-tesla outline sm" onClick={handleSheetsExport} disabled={exportingSheets}>
              <FileSpreadsheet size={14} />
              {exportingSheets ? 'Exportando a Sheets…' : 'Exportar a Sheets'}
            </button>
          )}
        </div>
      </header>

      {errorKind === 'forbidden' && (
        <div className={styles.errorBar}>
          <ShieldAlert size={16} /> No tenés permiso para ver Métricas ML.
        </div>
      )}
      {errorKind === 'rejected' && (
        <div className={styles.errorBar} role="alert">
          <ShieldAlert size={16} /> {typeof rejectedMessage === 'string' ? rejectedMessage : PERIOD_LIMIT_MESSAGE}
        </div>
      )}
      {errorKind === 'generic' && (
        <div className={styles.errorBar}>
          <ShieldAlert size={16} /> Error al cargar las métricas.
        </div>
      )}
      {tpError && (
        <div className={styles.errorBar} role="alert">
          <ShieldAlert size={16} /> {tpError}
        </div>
      )}
      {exportError && (
        <div className={styles.errorBar} role="alert">
          <ShieldAlert size={16} /> {exportError}
        </div>
      )}
      {sheetsNotice && (
        <p className={styles.description} role="status">
          {sheetsNotice.url ? (
            <>
              Hoja creada.{' '}
              <a href={sheetsNotice.url} target="_blank" rel="noopener noreferrer">
                Abrir la hoja en Google Sheets
              </a>
            </>
          ) : (
            sheetsNotice.text
          )}
        </p>
      )}

      <section className={styles.filterCard} aria-label="Filtros">
        <div className={styles.filterBand}>
          <DateRangeFilter
            fechaDesde={range.desde}
            fechaHasta={range.hasta}
            filtroActivo={range.filtro}
            maxDays={MAX_PERIOD_DAYS}
            maxDaysMessage={PERIOD_LIMIT_MESSAGE}
            onChange={({ desde, hasta, filtro }) => withReset(setRange)({ desde, hasta, filtro })}
          />
          <div className={styles.searchSlot}>
            <SearchInput
              value={searchQuery}
              onChange={withReset(setSearchQuery)}
              debounce={400}
              placeholder="Buscar por producto, SKU, MLA o marca…"
            />
          </div>
          <div className={styles.segments}>
            <div className={styles.filterGroup}>
              <span className={styles.filterLabel}>Agrupar por:</span>
              <SegmentedControl label="Agrupar por" options={GROUP_OPTIONS} value={groupBy} onChange={withReset(setGroupBy)} />
            </div>
            {groupBy === 'group' && (
              <div className={styles.filterGroup}>
                <span className={styles.filterLabel}>Dimensión:</span>
                <SegmentedControl
                  label="Dimensión"
                  options={dimensionOptions}
                  value={shownDimension}
                  onChange={withReset(setDimension)}
                />
              </div>
            )}
            {puedeVerGanancia && <AdsModeControl value={publicidad} onChange={withReset(setPublicidad)} tpSolo={tpSolo} />}
            {puedeVerGanancia && !tpSolo && (
              <SwitchChip
                label="Costos TP"
                checked={costosTp}
                onChange={withReset((next) => {
                  setCostosTp(next);
                  if (next) setTpError(null);
                  else setSort(withoutTpSort);
                })}
                title="Muestra el Total TP junto al Total Gauss; el markup usa el costo TP en las operaciones de la tienda TP-Link"
              />
            )}
            <div className={styles.filterGroup}>
              <span className={styles.filterLabel}>Comparar con:</span>
              <SegmentedControl label="Comparar con" options={COMPARE_OPTIONS} value={compararCon} onChange={withReset(setCompararCon)} />
            </div>
          </div>
        </div>

        <div className={styles.filterBand}>
          <div className={styles.filterGroup}>
            <span
              className={styles.filterLabel}
              title="Operaciones del período en cada tienda (la tienda oficial ACTUAL de la publicación), como en Ventas ML"
            >
              Tienda:
            </span>
            <FacetChips
              label="Filtrar por tienda oficial"
              {...storeChips}
              hints={storeChipHints(storeChips, facets)}
              total={facets?.stores_total}
              onChange={withReset(setStoreFilter)}
            />
          </div>
        </div>

        <div className={styles.filterBand}>
          <div className={styles.filterGroup}>
            <SwitchChip
              label="Solo con ventas en el período"
              checked={soloConVentas}
              onChange={withReset(setSoloConVentas)}
              title="Muestra sólo las filas con ventas en el período elegido; sus ventanas 24h a 30D no cambian"
            />
            {hidesStale && (
              <span className={styles.toggleHint} role="status">
                Ocultando {noun} sin ventas en el período
              </span>
            )}
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel} title="Stock del ERP (depósito 1), el mismo que muestra Productos">
              Stock:
            </span>
            <ToggleChips
              label="Filtrar por stock"
              options={STOCK_OPTIONS}
              labels={STOCK_LABELS}
              counts={facets?.stock}
              selected={stock}
              excluded={stockExclude}
              onChange={withReset((nextSelected, nextExcluded) => {
                setStock(nextSelected);
                setStockExclude(nextExcluded);
              })}
            />
          </div>
          <div className={styles.filterGroup}>
            <span
              className={styles.filterLabel}
              title="Días desde la última venta (o desde que empezó la publicación, si nunca vendió)"
            >
              Ageing:
            </span>
            <ToggleChips
              label="Filtrar por ageing"
              options={AGEING_OPTIONS}
              labels={AGEING_LABELS}
              counts={facets?.ageing}
              selected={ageing}
              excluded={ageingExclude}
              onChange={withReset((nextSelected, nextExcluded) => {
                setAgeing(nextSelected);
                setAgeingExclude(nextExcluded);
              })}
              dotFor={(value) => AGEING_BUCKET_TONES[value]}
            />
          </div>
        </div>

        <div className={styles.filterBand}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Producto:</span>
            <ProductFiltersPanel
              value={productFilters}
              onChange={withReset(setProductFilters)}
              options={facets?.product}
              hidePm={tpSolo}
            />
          </div>
          <span className={styles.divider} aria-hidden="true" />
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel} title="Último estado informado por el ERP">
              Publicación:
            </span>
            <ToggleChips
              label="Filtrar por estado de publicación"
              options={PUB_STATUS_OPTIONS}
              labels={PUB_STATUS_LABELS}
              counts={facets?.pub_status}
              selected={pubStatus}
              excluded={pubStatusExclude}
              onChange={withReset((nextSelected, nextExcluded) => {
                setPubStatus(nextSelected);
                setPubStatusExclude(nextExcluded);
              })}
              dotFor={(value) => (value === 'active' ? 'good' : null)}
            />
            <span className={styles.subLabel}>Tipo:</span>
            <ToggleChips
              label="Filtrar por tipo de publicación"
              options={PUB_TYPE_OPTIONS}
              labels={PUB_TYPE_LABELS}
              counts={facets?.pub_type}
              selected={pubType}
              excluded={pubTypeExclude}
              onChange={withReset((nextSelected, nextExcluded) => {
                setPubType(nextSelected);
                setPubTypeExclude(nextExcluded);
              })}
            />
          </div>
        </div>

        <div className={styles.filterBand}>
          <div className={styles.filterGroup} role="group" aria-label="Alertas">
            <span className={styles.filterLabel}>Alertas:</span>
            {ALERTS.filter((alert) => !alert.margin || canSeeMargin).map(({ value, label, icon, tone }) => {
              const Icon = icon;
              const active = alerts.includes(value);
              const count = facets?.alerts?.[value];
              return (
                <button
                  key={value}
                  type="button"
                  className={`${styles.alertChip} ${active ? styles.alertActive : ''}`}
                  data-tone={tone}
                  aria-pressed={active}
                  onClick={() =>
                    withReset(setAlerts)(active ? alerts.filter((a) => a !== value) : [...alerts, value])
                  }
                >
                  <Icon size={12} aria-hidden="true" />
                  {label}
                  {count !== undefined && count !== null && ` (${formatUnits(count)})`}
                </button>
              );
            })}
          </div>
          <div className={styles.spacer} />
          {hasActiveFilters && (
            <button type="button" className={styles.clearFilters} onClick={clearFilters}>
              <FilterX size={14} /> Limpiar filtros
            </button>
          )}
        </div>
      </section>

      <AdsAppliedBanner ads={ads} />

      <MetricasKpiStrip kpis={board?.kpis} canSeeMargin={canSeeMargin} groupBy={groupBy} loading={loading} tpSolo={tpSolo} />

      {adsOn && <AdsKpiBlock ads={ads} />}

      <section className={styles.tableCard} aria-label={`Tablero de ${noun}`} aria-busy={loading}>
        <div className={styles.tableScroll} data-table-scroll>
          <BoardTable
            rows={rows}
            columns={visibleColumns}
            groupBy={groupBy}
            canSeeMargin={canSeeMargin}
            expanded={expanded}
            subRows={subRows}
            onToggleExpand={toggleExpand}
            sort={sortKey}
            sortDesc={sort.desc}
            onSort={handleSort}
          />
        </div>
        {!loading && rows.length === 0 && !errorKind && (
          <p className={styles.empty}>No hay {noun} que coincidan con los filtros.</p>
        )}
        <div className={styles.footer}>
          <Pagination
            total={total}
            offset={offset}
            pageSize={pageSize}
            onOffsetChange={setOffset}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setOffset(0);
            }}
            summary={
              <span className={styles.summary}>
                Mostrando{' '}
                <strong>
                  {total === 0 ? 0 : offset + 1}–{Math.min(offset + pageSize, total)}
                </strong>{' '}
                de <strong>{formatUnits(total)}</strong> {noun} (
                <span className={styles.rotating}>{formatUnits(board?.with_sales_count ?? 0)}</span> con rotación en el
                período)
              </span>
            }
          />
        </div>
      </section>

      {adsOn && <AdsUnattributedPanel unattributed={ads.unattributed} />}
    </div>
  );
}
