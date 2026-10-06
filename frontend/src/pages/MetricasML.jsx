import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useReactTable, getCoreRowModel } from '@tanstack/react-table';
import { AlertTriangle, Clock, Download, FilterX, ShieldAlert, TrendingDown } from 'lucide-react';
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
import MetricasKpiStrip from '../components/metricasMl/MetricasKpiStrip';
import BoardTable from '../components/metricasMl/BoardTable';
import { DIMENSION_OPTIONS, buildBoardColumns } from '../components/metricasMl/metricasMlColumns';
import { buildStoreChips } from '../constants/tiendasOficiales';
import { useTiendasOficiales } from '../hooks/useTiendasOficiales';
import { calcularRangoPreset } from '../utils/dateRangePresets';
import { buildMetricasMLParams } from '../utils/metricasMlParams';
import { nodeId } from '../utils/metricasMlLevels';
import { exportMetricasCsv } from '../utils/ventasMlExport';
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

const DEFAULT_PRESET = '30d';
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

/** `next` after `previous`, without any row `previous` already has: a metric
 * that moved between two pages shifts the order, and a repeated row would
 * duplicate its React key. */
function appendNew(previous, next) {
  const seen = new Set(previous.map((row) => row.key));
  return [...previous, ...next.filter((row) => !seen.has(row.key))];
}

function defaultRange() {
  const { desde, hasta } = calcularRangoPreset(DEFAULT_PRESET);
  return { desde, hasta };
}

export default function MetricasML() {
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('ml_metricas.ver');
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

  const filterParams = useMemo(
    () =>
      buildMetricasMLParams({
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
    ],
  );

  // Changing WHAT is filtered resets WHERE you are: page 1, nothing open.
  const withReset = (setter) => (...args) => {
    setter(...args);
    setOffset(0);
  };

  const cargar = useCallback(async () => {
    if (!puedeVer) return;
    const requestId = ++latestRequestRef.current;
    setLoading(true);
    setErrorKind(null);
    try {
      const params = { ...filterParams, sort: sort.key, sort_dir: sort.desc ? 'desc' : 'asc', limit: pageSize, offset };
      const { data } = await api.get('/ml-metricas/board', { params });
      if (requestId !== latestRequestRef.current) return;
      setBoard(data);
      setExpanded(new Set());
      setSubRows({});
    } catch (err) {
      if (requestId !== latestRequestRef.current) return;
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
  }, [puedeVer, filterParams, sort, pageSize, offset]);

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
                sort: sort.key,
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
      } catch {
        if (generation !== latestRequestRef.current) return;
        setSubRows((prev) => ({ ...prev, [id]: { loading: false, rows: previous, level, fetched, error: true } }));
      }
    },
    [expanded, subRows, filterParams, groupBy, sort],
  );

  const handleSort = useCallback((key) => {
    setSort((prev) => ({ key, desc: prev.key === key ? !prev.desc : key !== 'title' }));
    setOffset(0);
  }, []);

  const handleExport = useCallback(async () => {
    setExporting(true);
    setExportError(null);
    try {
      await exportMetricasCsv({ ...filterParams, sort: sort.key, sort_dir: sort.desc ? 'desc' : 'asc' });
    } catch (err) {
      setExportError(err.message);
    } finally {
      setExporting(false);
    }
  }, [filterParams, sort]);

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
  const periodLabel = PERIOD_LABELS[range.filtro] || 'período';
  const columnDefs = useMemo(
    () => buildBoardColumns({ canSeeMargin, periodLabel, groupBy, dimension }),
    [canSeeMargin, periodLabel, groupBy, dimension],
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
      {exportError && (
        <div className={styles.errorBar} role="alert">
          <ShieldAlert size={16} /> {exportError}
        </div>
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
                  options={DIMENSION_OPTIONS}
                  value={dimension}
                  onChange={withReset(setDimension)}
                />
              </div>
            )}
            <div className={styles.filterGroup}>
              <span className={styles.filterLabel}>Comparar con:</span>
              <SegmentedControl label="Comparar con" options={COMPARE_OPTIONS} value={compararCon} onChange={withReset(setCompararCon)} />
            </div>
          </div>
        </div>

        <div className={styles.filterBand}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel} title="La tienda oficial ACTUAL de la publicación">
              Tienda:
            </span>
            <FacetChips
              label="Filtrar por tienda oficial"
              {...buildStoreChips({ tiendas, getLabel, counts: facets?.stores, selected: storeFilter, facetExtras: false })}
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

      <MetricasKpiStrip kpis={board?.kpis} canSeeMargin={canSeeMargin} groupBy={groupBy} loading={loading} />

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
            sort={sort.key}
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
    </div>
  );
}
