/**
 * VentasML — the Mercado Libre sales list page (ml-ventas-listado-ui).
 *
 * Consumes GET /ml-ventas-ops/sales (merged backend, ml-ventas-listado-api).
 * Read access needs `ml_ops.ver`. No invoices, no costs, no metrics on this
 * page — those were explicitly deferred; see `MLQuestions.jsx`/
 * `DivergenciasML.jsx` for the sibling ML dashboards this page mirrors.
 *
 * Two axes are the whole point of this page, and they stay independent on
 * purpose:
 *  - `operation_status` is about the MONEY (paid, cancelled, in dispute...).
 *  - `goods_status` is about the PRODUCT (in warehouse, in transit...).
 * A cancellation with the goods still in the warehouse, one that came back
 * (`returned_undelivered`), and one the buyer kept are three different
 * situations behind the same word "cancelled" — the UI must let the
 * operator see both axes at a glance and filter each independently.
 *
 * `cancelled_ml_covered` is mechanically a cancellation but commercially
 * not one — Mercado Libre's Buyer Protection Programme paid the buyer out
 * of its own pocket, so the money still arrived. Never render it as a
 * plain "Cancelada".
 *
 * `unknown` (either axis) means nobody has classified it yet. It fails
 * safe on purpose and must stay visible — never hidden, never folded into
 * another value.
 *
 * ONE ROW IS ONE PACK. Mercado Libre splits a purchase into one order per
 * item, tied together by `pack_id`. Listed one-per-row they read as
 * unrelated sales: on 2026-09-02 the operator hit three rows with the same
 * buyer and the same timestamp where two were a single parcel and the
 * third was another — indistinguishable. The row is the parcel; the
 * spoiler holds the orders inside it.
 *
 * `mixed` is not a status either axis defines. It is the row saying its
 * orders disagree and the operator has to open it.
 *
 * ML's own `shipping_status` is deliberately NOT rendered. `goods_status`
 * is derived from it and answers the question the operator acts on — is
 * the parcel still mine, or has it left? — so the raw value restates that
 * badge in untranslated English beside it. It bought no distinction and
 * cost a column: a 20-shipment sample of live orders came back
 * `ready_to_ship` 17 times.
 *
 * The argument is about the two columns saying the same thing, not about
 * which status maps where — `GOODS_STATUS_BY_SHIPPING_STATUS` owns that,
 * and this comment stays true when it changes. The raw value is still in
 * the API per order for whoever needs the finer reading.
 */

import { Fragment, useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useReactTable, getCoreRowModel } from '@tanstack/react-table';
import { ShieldAlert, AlertTriangle, Download, RefreshCw } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import VentasMLLayout from '../components/ventasMl/VentasMLLayout';
import SaleDetailPanel from '../components/ventasMl/SaleDetailPanel';
import PackDetailPanel from '../components/ventasMl/PackDetailPanel';
import Pagination from '../components/ventasMl/Pagination';
import SalesToolbar from '../components/ventasMl/SalesToolbar';
import FacetChips from '../components/ventasMl/FacetChips';
import AlertsFilterChip from '../components/ventasMl/AlertsFilterChip';
import ProductFiltersPanel from '../components/shared/ProductFiltersPanel';
import KpiStrip from '../components/ventasMl/KpiStrip';
import IncludeToggles from '../components/ventasMl/IncludeToggles';
import ColumnPicker from '../components/ventasMl/ColumnPicker';
import { COLUMNS } from '../components/ventasMl/ventasMlColumns';
import { useColumnSizing } from '../components/ml-bot/useColumnSizing';
import { useColumnResize } from '../components/ventasMl/useColumnResize';
import {
  loadColumnVisibility,
  saveColumnVisibility,
  loadPageSize,
  savePageSize,
  COLUMN_SIZING_STORAGE_KEY,
} from './ventasMlTableHelpers';
import { useVentasMLFilters } from '../hooks/useVentasMLFilters';
import VariosVentaPctModal from '../components/VariosVentaPctModal';
import DateRangeFilter from '../components/DateRangeFilter';
import { buildVentasMLFilterParams } from '../utils/ventasMlParams';
import { exportVentasCsv } from '../utils/ventasMlExport';
import {
  formatDate,
  timeAgo,
  OPERATION_STATUS_LABELS,
  OPERATION_STATUS_OPTIONS,
  GOODS_STATUS_LABELS,
  GOODS_STATUS_OPTIONS,
  groupAlertLevel,
  groupMetricsState,
} from '../utils/ventasMlFormat';
import styles from './VentasML.module.css';

const EMPTY_FACETS = {
  operation_status: {},
  goods_status: {},
  operation_status_total: 0,
  goods_status_total: 0,
  alerts_total: 0,
};

// Status labels/badge classes, money/date formatting, and the group-level
// alert/metrics-state/category/items helpers all live in
// `utils/ventasMlFormat.js` now (ventas-ml-columnas) -- moved out so
// `components/ventasMl/ventasMlColumns.jsx` can render both the group row
// and the pack-member rows from the SAME formatting rules without an
// import cycle back into this page module. Behaviour unchanged.

export default function VentasML() {
  const latestRequestRef = useRef(0);
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('ml_ops.ver');
  const puedeResincronizar = tienePermiso('ml_ops.resincronizar');

  const [sales, setSales] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSizeState] = useState(loadPageSize);
  const [loading, setLoading] = useState(true);
  const [lastLoadedAt, setLastLoadedAt] = useState(null);
  // When ML data last reached the list (sweep / activity drain), not when
  // this screen last fetched it.
  const [lastSyncedAt, setLastSyncedAt] = useState(null);
  // 403 (no permission) and 503 (feature switched off) are distinct
  // failures the operator needs to tell apart — never collapsed into one
  // generic error message.
  const [errorKind, setErrorKind] = useState(null); // 'forbidden' | 'disabled' | 'generic' | null

  // Ingestion failures (`ingest_failed` divergences) are surfaced here on
  // purpose: an order that never got written stays invisible in this list
  // by definition, so a silent failure looks identical to a quiet day. This
  // count is best-effort — a failure here must never break the sales list
  // itself, only skip the warning banner (see the catch block below).
  const [failedIngestCount, setFailedIngestCount] = useState(0);

  // ventas-ml-kpi-strip T5: the four `include_*` toggles. Defaulted to
  // `true` (show everything) to match the LIST endpoint's own legacy
  // backward-compatible default (`GET /sales`'s docstring) -- before this
  // feature the frontend never sent them at all, so the list already
  // behaved as if all four were on. Both the list and the KPI request read
  // from this SAME state (T5 parity), regardless of each endpoint's own
  // individual default.
  const [includeUnknown, setIncludeUnknown] = useState(true);
  const [includeInDispute, setIncludeInDispute] = useState(true);
  const [includeMixed, setIncludeMixed] = useState(true);
  const [includeProvisional, setIncludeProvisional] = useState(true);
  const [includeCancelled, setIncludeCancelled] = useState(true);
  const [onlyAlerts, setOnlyAlerts] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(null);

  const [kpi, setKpi] = useState(null);
  const [kpiLoading, setKpiLoading] = useState(true);
  const [kpiError, setKpiError] = useState(null);

  const [operationStatusFilter, setOperationStatusFilter] = useState('');
  const [goodsStatusFilter, setGoodsStatusFilter] = useState('');
  // No default range: unlike the métricas dashboard this list starts
  // unfiltered by date, so `dateRangeFiltro` stays `null` until the
  // operator picks a preset or a custom range.
  const [fechaDesde, setFechaDesde] = useState('');
  const [fechaHasta, setFechaHasta] = useState('');
  const [dateRangeFiltro, setDateRangeFiltro] = useState(null);

  const [facets, setFacets] = useState({
    operation_status: {},
    goods_status: {},
    operation_status_total: 0,
    goods_status_total: 0,
  });
  // Keyed by `group_key`, so an open pack stays open across a re-render.
  // Reset on every load: the keys of the previous page mean nothing here.
  const [expanded, setExpanded] = useState(() => new Set());

  const toggleExpanded = useCallback((key) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // ventas-ml-columnas: the table instance is used ONLY as a column-
  // geometry engine (sizing + visibility) -- the same discipline
  // `tiendaNubeReconcileTableHelpers.js` documents for its own table. Rows
  // still render manually below, for BOTH the group row and the expanded
  // pack-member rows, from `table.getVisibleLeafColumns()` -- that is what
  // keeps a hidden column out of every row kind at once (T4).
  const [columnVisibility, setColumnVisibilityState] = useState(() =>
    loadColumnVisibility(COLUMNS),
  );

  const handleColumnVisibilityChange = useCallback((updater) => {
    setColumnVisibilityState((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      saveColumnVisibility(next);
      return next;
    });
  }, []);

  // User-resizable widths: same shared hook the ml-bot tables use (state in
  // localStorage, debounced save, reset), our own key.
  const {
    columnSizing,
    onColumnSizingChange,
    reset: resetColumnSizing,
    hasCustom: hasCustomSizing,
  } = useColumnSizing(COLUMN_SIZING_STORAGE_KEY);

  const table = useReactTable({
    columns: COLUMNS,
    data: useMemo(() => [], []),
    getCoreRowModel: getCoreRowModel(),
    state: { columnVisibility, columnSizing },
    onColumnVisibilityChange: handleColumnVisibilityChange,
    onColumnSizingChange,
  });

  const visibleColumns = table.getVisibleLeafColumns();
  // Sum of the VISIBLE columns only, so the `<colgroup>` ratios below always
  // add up to 100% no matter how many the operator hid. `getTotalSize()`
  // would serve here too, but naming it makes the division read as what it
  // is: a share of what is actually on screen.
  const theadRef = useRef(null);
  const { startDrag, keyResize } = useColumnResize({
    visibleColumns,
    theadRef,
    onSizingChange: onColumnSizingChange,
  });
  const lastVisibleColumnId = visibleColumns[visibleColumns.length - 1]?.id;
  const visibleColumnsTotalSize = visibleColumns.reduce((acc, col) => acc + col.getSize(), 0) || 1;

  // Panel selection lives in the `orden` URL param, consistent with this
  // screen's other URL-driven filters (PANEL R19 — see design D14). The
  // panel opens for a GROUP (pack or lone order) and stays open while the
  // operator picks another row -- it only carries the order_id the
  // per-order endpoint needs, since the backend resolves the whole pack's
  // breakdown from any order inside it.
  const {
    selectedOrderId,
    selectOrder,
    selectedPackId,
    selectPack,
    clearSelection,
    searchQuery,
    setSearchQuery,
    productFilters,
    setProductFilters,
    clearProductFilters,
  } = useVentasMLFilters();

  // Visible to everyone who can see this page — the modal itself decides
  // read-only vs. read+write once open, per product decision (see
  // VariosVentaPctModal for the actual `ml_ops.varios_editar` gating).
  const [variosPctModalOpen, setVariosPctModalOpen] = useState(false);

  const openDrawer = useCallback(
    (orderId) => {
      selectOrder(orderId);
    },
    [selectOrder],
  );

  // PR19 (PANEL R22): a pack row opens the PACK-scoped panel, keyed by
  // `pack_id` — never `openDrawer(orders[0].order_id)`, which opened the
  // order-scoped panel of an arbitrary member (the bug this PR fixes).
  const openPackDrawer = useCallback(
    (packId) => {
      selectPack(packId);
    },
    [selectPack],
  );

  // A new page size invalidates `offset` (page 3 of 25 is not page 3 of
  // 100), so it always goes back to the first page.
  const handlePageSizeChange = useCallback((size) => {
    setPageSizeState(size);
    savePageSize(size);
    setOffset(0);
  }, []);

  const handleOperationStatusChange = useCallback((value) => {
    setOperationStatusFilter(value);
    setOffset(0);
  }, []);

  // The file is the filtered set the table shows: same shared params builder,
  // no paging (the backend walks the pages itself).
  const handleExport = useCallback(async () => {
    setExporting(true);
    setExportError(null);
    try {
      await exportVentasCsv(
        buildVentasMLFilterParams({
          operationStatusFilter,
          goodsStatusFilter,
          fechaDesde,
          fechaHasta,
          searchQuery,
          productFilters,
          includeUnknown,
          includeInDispute,
          includeMixed,
          includeProvisional,
          includeCancelled,
          onlyAlerts,
        }),
      );
    } catch (err) {
      setExportError(err.message);
    } finally {
      setExporting(false);
    }
  }, [
    operationStatusFilter,
    goodsStatusFilter,
    fechaDesde,
    fechaHasta,
    searchQuery,
    productFilters,
    includeUnknown,
    includeInDispute,
    includeMixed,
    includeProvisional,
    includeCancelled,
    onlyAlerts,
  ]);

  const handleOnlyAlertsChange = useCallback((value) => {
    setOnlyAlerts(value);
    setOffset(0);
  }, []);

  const handleGoodsStatusChange = useCallback((value) => {
    setGoodsStatusFilter(value);
    setOffset(0);
  }, []);

  // The month picker this page used to carry is GONE: the shared date
  // filter replaces it. Two controls for one axis meant the endpoint
  // silently preferred one of them (`_parse_date_range`/`sold_range` in
  // `ml_ventas_ops.py` only consults the month when no range parsed), so
  // the field could read "Septiembre" over a list filtered to 7 days.
  // Making them exclusive papered over that; removing one settles it.
  // `sold_month` stays supported by the endpoint for other callers.
  const handleSearchChange = useCallback(
    (value) => {
      setSearchQuery(value);
      setOffset(0);
    },
    [setSearchQuery],
  );

  // Same discipline every other filter on this screen follows: changing WHAT
  // is filtered resets WHERE you are in the result set. Without it, picking a
  // brand while on page 3 shows "no hay ventas que coincidan" for a brand that
  // does have sales -- they are simply on page 1.
  const handleProductFiltersChange = useCallback(
    (next) => {
      setProductFilters(next);
      setOffset(0);
    },
    [setProductFilters],
  );

  const handleDateRangeChange = useCallback(({ desde, hasta, filtro }) => {
    setFechaDesde(desde);
    setFechaHasta(hasta);
    setDateRangeFiltro(filtro);
    setOffset(0);
  }, []);

  const clearFilters = useCallback(() => {
    setOperationStatusFilter('');
    setGoodsStatusFilter('');
    setFechaDesde('');
    setFechaHasta('');
    setDateRangeFiltro(null);
    setSearchQuery('');
    clearProductFilters();
    setIncludeUnknown(true);
    setIncludeInDispute(true);
    setIncludeMixed(true);
    setIncludeProvisional(true);
    setIncludeCancelled(true);
    setOnlyAlerts(false);
    setOffset(0);
  }, [setSearchQuery, clearProductFilters]);

  // T4/T5: a single fan-out so a toggle change always reaches both the
  // list and the KPI request (they read the same state) and never drifts
  // out of sync with each other.
  const handleToggleChange = useCallback((key, value) => {
    if (key === 'includeUnknown') setIncludeUnknown(value);
    else if (key === 'includeInDispute') setIncludeInDispute(value);
    else if (key === 'includeMixed') setIncludeMixed(value);
    else if (key === 'includeProvisional') setIncludeProvisional(value);
    else if (key === 'includeCancelled') setIncludeCancelled(value);
    setOffset(0);
  }, []);

  const hasActiveFilters = Boolean(
    operationStatusFilter ||
      goodsStatusFilter ||
      fechaDesde ||
      fechaHasta ||
      searchQuery ||
      productFilters.marcas.length > 0 ||
      productFilters.subcategorias.length > 0 ||
      productFilters.pms.length > 0 ||
      !includeUnknown ||
      !includeInDispute ||
      !includeMixed ||
      !includeProvisional ||
      !includeCancelled ||
      onlyAlerts
  );

  // "Todas" is neither `total` (scoped by BOTH axes, so it under-counts
  // once the other axis is filtered) nor the sum of the buckets (a pack
  // whose orders disagree counts in two of them, so the sum double-counts
  // it and contradicts the table below). The backend sends the exact row
  // count for each axis's scope; read it, never re-derive it here.

  const cargarVentas = useCallback(async () => {
    if (!puedeVer) return;
    // Changing a filter twice quickly can land the older response last and
    // overwrite the list with the previous filter's rows. Only the newest
    // request is allowed to write.
    const requestId = ++latestRequestRef.current;
    setLoading(true);
    setErrorKind(null);
    try {
      // T5: the list uses the SAME filter params the KPI strip does
      // (`buildVentasMLFilterParams`) plus its own pagination on top — the
      // one shared builder is what keeps the two requests from drifting.
      const params = {
        limit: pageSize,
        offset,
        ...buildVentasMLFilterParams({
          operationStatusFilter,
          goodsStatusFilter,
          fechaDesde,
          fechaHasta,
          searchQuery,
          productFilters,
          includeUnknown,
          includeInDispute,
          includeMixed,
          includeProvisional,
          includeCancelled,
          onlyAlerts,
        }),
      };
      const { data } = await api.get('/ml-ventas-ops/sales', { params });
      if (requestId !== latestRequestRef.current) return;
      setSales(data.sales || []);
      setExpanded(new Set());
      setTotal(data.total ?? 0);
      setFacets(data.facets || EMPTY_FACETS);
      setLastLoadedAt(new Date());
    } catch (err) {
      if (requestId !== latestRequestRef.current) return;
      const httpStatus = err?.response?.status;
      if (httpStatus === 403) {
        setErrorKind('forbidden');
      } else if (httpStatus === 503) {
        setErrorKind('disabled');
      } else {
        setErrorKind('generic');
      }
      setSales([]);
      setTotal(0);
      setFacets(EMPTY_FACETS);
    } finally {
      if (requestId === latestRequestRef.current) setLoading(false);
    }
  }, [
    puedeVer,
    operationStatusFilter,
    goodsStatusFilter,
    fechaDesde,
    fechaHasta,
    searchQuery,
    productFilters,
    includeUnknown,
    includeInDispute,
    includeMixed,
    includeProvisional,
    includeCancelled,
    onlyAlerts,
    offset,
    pageSize,
  ]);

  // T5/T6: the KPI strip's own load — same filter params as the list
  // (never its `limit`/`offset`, the endpoint aggregates the whole
  // filtered set), a separate request so a paging click doesn't re-fetch
  // totals that have not changed, and its own sequence guard for the same
  // reason `cargarVentas` needs one.
  const latestKpiRequestRef = useRef(0);
  const cargarKpis = useCallback(async () => {
    if (!puedeVer) return;
    const requestId = ++latestKpiRequestRef.current;
    setKpiLoading(true);
    setKpiError(null);
    try {
      const params = buildVentasMLFilterParams({
        operationStatusFilter,
        goodsStatusFilter,
        fechaDesde,
        fechaHasta,
        searchQuery,
        productFilters,
        includeUnknown,
        includeInDispute,
        includeMixed,
        includeProvisional,
        includeCancelled,
        onlyAlerts,
      });
      const { data } = await api.get('/ml-ventas-ops/sales/kpis', { params });
      if (requestId !== latestKpiRequestRef.current) return;
      setKpi(data);
    } catch (err) {
      if (requestId !== latestKpiRequestRef.current) return;
      setKpi(null);
      // Same three kinds the list already distinguishes (see `errorKind`):
      // 403 is "you lack the permission", 503 is "the feature is switched
      // off". Collapsing them into one generic message sends an operator
      // hunting for an outage that is really a flag, or for a flag that is
      // really their own permissions.
      const kpiStatus = err?.response?.status;
      setKpiError(kpiStatus === 403 ? 'forbidden' : kpiStatus === 503 ? 'disabled' : 'generic');
    } finally {
      if (requestId === latestKpiRequestRef.current) setKpiLoading(false);
    }
  }, [
    puedeVer,
    operationStatusFilter,
    goodsStatusFilter,
    fechaDesde,
    fechaHasta,
    searchQuery,
    productFilters,
    includeUnknown,
    includeInDispute,
    includeMixed,
    includeProvisional,
    includeCancelled,
    onlyAlerts,
  ]);

  useEffect(() => {
    cargarKpis();
  }, [cargarKpis]);

  // Best-effort and independent of the list (same stance as the ingest-failed
  // banner below): losing this indicator must never cost the operator the list.
  const cargarSyncStatus = useCallback(async () => {
    if (!puedeVer) return;
    try {
      const { data } = await api.get('/ml-ventas-ops/sales/sync-status');
      setLastSyncedAt(data?.last_synced_at ?? null);
    } catch {
      setLastSyncedAt(null);
    }
  }, [puedeVer]);

  useEffect(() => {
    cargarSyncStatus();
  }, [cargarSyncStatus]);

  // A resynced sale can change its row, the totals and the freshness stamp.
  const handleResynced = useCallback(() => {
    cargarVentas();
    cargarKpis();
    cargarSyncStatus();
  }, [cargarVentas, cargarKpis, cargarSyncStatus]);

  useEffect(() => {
    cargarVentas();
  }, [cargarVentas]);

  // Independent of `cargarVentas` on purpose: this banner is additional
  // information, never a reason for the sales list itself to fail. Only
  // `limit: 1` is requested — `total` is all this banner needs, not the
  // rows themselves.
  useEffect(() => {
    if (!puedeVer) return;
    let cancelled = false;
    api
      .get('/ml-ventas-ops/divergences', {
        params: { kind: 'ingest_failed', state: 'open', limit: 1 },
      })
      .then(({ data }) => {
        if (!cancelled) setFailedIngestCount(data.total ?? 0);
      })
      .catch(() => {
        // Best-effort: an operator who cannot see the banner must still see
        // the sales list. Silently keep the banner hidden.
        if (!cancelled) setFailedIngestCount(0);
      });
    return () => {
      cancelled = true;
    };
  }, [puedeVer]);

  if (!puedeVer) {
    return null;
  }

  // The selected order's own listing row, when it is on this page: the
  // detail endpoint carries no status axes or sale date, the row does. The
  // panel shows those pills only when it has them -- a deep link to an
  // order on another page simply goes without.
  const selectedListOrder =
    selectedOrderId === null || selectedOrderId === undefined
      ? null
      : sales.flatMap((group) => group.orders || []).find((o) => o.order_id === selectedOrderId) || null;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <h1>Ventas ML</h1>
          <p className={styles.description}>
            Ventas de Mercado Libre. La operación describe el dinero; la mercadería, el producto — son ejes
            independientes a propósito.
          </p>
        </div>
        <div className={styles.headerActions}>
          {(timeAgo(lastSyncedAt) || lastLoadedAt) && (
            <span className={styles.freshness}>
              {timeAgo(lastSyncedAt) && <span className={styles.freshnessDot} aria-hidden="true" />}
              {timeAgo(lastSyncedAt) && <span>sincronizado {timeAgo(lastSyncedAt)}</span>}
              {timeAgo(lastSyncedAt) && lastLoadedAt && <span aria-hidden="true">·</span>}
              {lastLoadedAt && <span>actualizado {formatDate(lastLoadedAt)}</span>}
            </span>
          )}
          <ColumnPicker table={table} />
          {hasCustomSizing && (
            <button type="button" className="btn-tesla outline sm" onClick={resetColumnSizing}>
              Restablecer columnas
            </button>
          )}
          <button
            type="button"
            className="btn-tesla outline sm"
            onClick={() => setVariosPctModalOpen(true)}
          >
            % de varios
          </button>
          <button
            type="button"
            className="btn-tesla outline sm"
            onClick={handleExport}
            disabled={exporting}
          >
            <Download size={14} aria-hidden="true" />
            {exporting ? 'Exportando...' : 'Exportar CSV'}
          </button>
          {/* Refreshes BOTH: reloading only the list would leave the six
              cards showing the previous totals beside fresh rows, which is
              exactly the "what I see is what it sums" promise broken by the
              one button whose whole job is to make them agree. */}
          <button
            type="button"
            className="btn-tesla outline sm"
            onClick={() => {
              cargarVentas();
              cargarKpis();
              cargarSyncStatus();
            }}
            disabled={loading}
          >
            <RefreshCw size={14} aria-hidden="true" />
            {loading ? 'Actualizando...' : 'Actualizar'}
          </button>
        </div>
      </div>

      {exportError && (
        <div className={styles.errorBar} role="alert">
          <ShieldAlert size={16} /> {exportError}
        </div>
      )}

      {errorKind === 'forbidden' && (
        <div className={styles.errorBar}>
          <ShieldAlert size={16} /> No tenés permiso para ver las ventas (ml_ops.ver).
        </div>
      )}
      {errorKind === 'disabled' && (
        <div className={styles.errorBar}>
          <ShieldAlert size={16} /> La fuente de verdad de ventas ML está deshabilitada actualmente.
        </div>
      )}
      {errorKind === 'generic' && (
        <div className={styles.errorBar}>
          <ShieldAlert size={16} /> Error al cargar las ventas.
        </div>
      )}

      {failedIngestCount > 0 && (
        <Link to="/ml-ventas-divergencias" className={styles.ingestFailedBanner}>
          <AlertTriangle size={16} />
          {failedIngestCount === 1
            ? '1 venta no pudo ingresar — el total de esta lista está incompleto.'
            : `${failedIngestCount} ventas no pudieron ingresar — el total de esta lista está incompleto.`}
          {' '}Ver divergencias
        </Link>
      )}

      {/* ONE filter card, three bands (Stitch `listado`): search, statuses,
          products. Same controls, same state and params as before
          (`buildVentasMLFilterParams`) -- only the arrangement changed. */}
      <section className={styles.filterCard} aria-label="Filtros">
        <div className={styles.filterBand}>
          <DateRangeFilter
            fechaDesde={fechaDesde}
            fechaHasta={fechaHasta}
            filtroActivo={dateRangeFiltro}
            onChange={handleDateRangeChange}
          />
          <div className={styles.searchSlot}>
            <SalesToolbar
              value={searchQuery}
              onSearchChange={handleSearchChange}
              noResults={!loading && Boolean(searchQuery) && sales.length === 0}
            />
          </div>
          <div className={styles.alertsSlot}>
            <AlertsFilterChip
              active={onlyAlerts}
              count={facets.alerts_total}
              onChange={handleOnlyAlertsChange}
            />
          </div>
        </div>

        <div className={styles.filterBand}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel} title="El dinero">
              Operación:
            </span>
            <FacetChips
              label="Filtrar por estado de operación"
              options={OPERATION_STATUS_OPTIONS}
              labels={OPERATION_STATUS_LABELS}
              counts={facets.operation_status}
              total={facets.operation_status_total}
              activeValue={operationStatusFilter}
              onChange={handleOperationStatusChange}
            />
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel} title="El producto">
              Mercadería:
            </span>
            <FacetChips
              label="Filtrar por estado de la mercadería"
              options={GOODS_STATUS_OPTIONS}
              labels={GOODS_STATUS_LABELS}
              counts={facets.goods_status}
              total={facets.goods_status_total}
              activeValue={goodsStatusFilter}
              onChange={handleGoodsStatusChange}
            />
          </div>
        </div>

        <div className={styles.filterBand}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Producto:</span>
            <ProductFiltersPanel value={productFilters} onChange={handleProductFiltersChange} />
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Incluir:</span>
            <IncludeToggles
              values={{
                includeUnknown,
                includeInDispute,
                includeMixed,
                includeProvisional,
                includeCancelled,
              }}
              excludedByToggle={kpi?.excluded_by_toggle}
              onChange={handleToggleChange}
            />
          </div>
          <div className={styles.spacer} />
          {hasActiveFilters && (
            <button type="button" className={styles.clearFilters} onClick={clearFilters}>
              Limpiar filtros
            </button>
          )}
        </div>
      </section>

      <KpiStrip kpi={kpi} loading={kpiLoading} error={kpiError} />

      <VentasMLLayout
        selectedOrderId={selectedOrderId}
        selectedPackId={selectedPackId}
        onClear={clearSelection}
        panel={
          selectedPackId !== null && selectedPackId !== undefined ? (
            <PackDetailPanel
              packId={selectedPackId}
              onClose={clearSelection}
              onSelectOrder={openDrawer}
            />
          ) : (
            <SaleDetailPanel
              orderId={selectedOrderId}
              onClose={clearSelection}
              canResync={puedeResincronizar}
              lastSyncedAt={lastSyncedAt}
              onResynced={handleResynced}
              listOrder={selectedListOrder}
            />
          )
        }
      >
      <div className={styles.tableCard}>
        {/* NO inline `width: table.getTotalSize()`. The `size` values add
            up to ~1320px, and `.tableCard` deliberately has no
            `overflow-x` above 1280px (it would become a scroll container on
            BOTH axes and break the sticky header). A fixed 1427px table in
            the ~1080px a 1366px laptop leaves after the sidebar does not
            scroll -- the right-hand columns simply fall off the edge, Total
            Gauss included, with no way to reach them. Worse than the
            squeeze it replaced.

            So the table stays `width: 100%` and each `size` is used as a
            RATIO of the visible total below: one source of truth for the
            proportions, compression instead of clipping, and hiding a
            column still hands its share to the rest. */}
        <table className={styles.table}>
          <colgroup>
            {visibleColumns.map((col) => (
              <col
                key={col.id}
                style={{ width: `${((col.getSize() / visibleColumnsTotalSize) * 100).toFixed(4)}%` }}
              />
            ))}
          </colgroup>
          <thead ref={theadRef}>
            <tr>
              {table.getFlatHeaders().map((h) => {
                const def = h.column.columnDef;
                // No grip on the last visible column: its right edge is the
                // table's edge, nothing to trade width with.
                const resizable = h.column.getCanResize() && h.column.id !== lastVisibleColumnId;
                return (
                  <th
                    key={h.id}
                    data-col-id={h.column.id}
                    className={def.numeric ? styles.numeric : def.align === 'center' ? styles.colAlerta : undefined}
                    aria-label={def.header ? undefined : def.headerAriaLabel}
                  >
                    {def.header}
                    {resizable && (
                      <span
                        className={styles.resizeGrip}
                        role="separator"
                        aria-orientation="vertical"
                        aria-label={`Redimensionar columna ${def.header || def.headerAriaLabel}`}
                        tabIndex={0}
                        onMouseDown={(e) => startDrag(h.column.id, e)}
                        onTouchStart={(e) => startDrag(h.column.id, e)}
                        onKeyDown={(e) => keyResize(h.column.id, e)}
                      />
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className={styles.stateCell} colSpan={visibleColumns.length}>
                  Cargando ventas…
                </td>
              </tr>
            ) : sales.length === 0 ? (
              <tr>
                <td className={styles.stateCell} colSpan={visibleColumns.length}>
                  No hay ventas que coincidan con los filtros
                </td>
              </tr>
            ) : (
              sales.map((group) => {
                // Defensive on purpose: one malformed row must not white-screen
                // the whole listing for the operator.
                const orders = group.orders || [];
                const isPack = orders.length > 1;
                const isOpen = expanded.has(group.group_key);
                // Any order in the group resolves the same pack-level
                // breakdown on the backend -- the first one is enough.
                // `!= null` on purpose below, not `!== undefined`: a null order_id
                // would pass that check, mark the row clickable, and then call
                // openDrawer(null) -- which is the very sentinel for "closed",
                // so the click would do nothing at all.
                const representativeOrderId = orders[0]?.order_id;
                // PR14 review fix P1: a lone sale (`!isPack`) has no
                // pack-member block to fall into, so it must carry its own
                // subline/markup source directly.
                const loneOrder = !isPack ? orders[0] : null;
                const groupLevel = groupAlertLevel(orders);
                // PR19 (PANEL R22): a pack row opens the PACK-scoped panel
                // keyed by `group.pack_id` -- never
                // `openDrawer(representativeOrderId)`, which opened an
                // arbitrary member's order-scoped panel instead.
                const isRowClickable = isPack ? group.pack_id != null : representativeOrderId != null;
                const openGroupPanel = isPack
                  ? () => openPackDrawer(group.pack_id)
                  : representativeOrderId != null
                    ? () => openDrawer(representativeOrderId)
                    : undefined;
                const groupCtx = {
                  kind: 'group',
                  group,
                  orders,
                  isPack,
                  isOpen,
                  toggleExpanded,
                  loneOrder,
                  groupLevel,
                  metricsState: groupMetricsState(orders),
                  isRowClickable,
                  openGroupPanel,
                };
                return (
                  <Fragment key={group.group_key}>
                    {/* The row click is a MOUSE SHORTCUT, deliberately not a
                        widget: the keyboard route is the real <button> in
                        the Neto cell below. Making a <tr> focusable would
                        announce a control that screen readers cannot
                        describe, and the button already carries the
                        accessible name. */}
                    <tr
                      className={[
                        isPack ? styles.packRow : '',
                        isRowClickable ? styles.clickableRow : '',
                        (isPack && selectedPackId != null && group.pack_id === selectedPackId) ||
                        (!isPack && selectedOrderId != null && representativeOrderId === selectedOrderId)
                          ? styles.selectedRow
                          : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      onClick={isRowClickable ? openGroupPanel : undefined}
                    >
                      {/* T4/T3: the group row renders EXACTLY the columns
                          `table.getVisibleLeafColumns()` reports -- the
                          same list the header and the pack-member rows
                          below read from, so hiding a column can never
                          desync one row kind from another. */}
                      {visibleColumns.map((col) => {
                        const def = col.columnDef;
                        const extraProps = def.cellProps ? def.cellProps(groupCtx) : {};
                        const className = [def.numeric ? styles.numeric : '', def.align === 'center' ? styles.colAlerta : '', extraProps.className || '']
                          .filter(Boolean)
                          .join(' ');
                        return (
                          <td key={col.id} data-col-id={col.id} {...extraProps} className={className || undefined}>
                            {def.cell(groupCtx)}
                          </td>
                        );
                      })}
                    </tr>
                    {/* The orders inside the parcel. Rendered only when
                        opened, and never for a lone order — there is
                        nothing to unfold. */}
                    {isPack &&
                      isOpen &&
                      orders.map((order) => {
                        const memberCtx = { kind: 'member', order, openDrawer };
                        return (
                          <tr
                            key={order.order_id}
                            className={`${styles.memberRow} ${styles.clickableRow} ${
                              selectedOrderId === order.order_id ? styles.selectedRow : ''
                            }`.trim()}
                            onClick={() => openDrawer(order.order_id)}
                          >
                            {/* T4: THE SAME `visibleColumns` list the group
                                row above just rendered -- a hidden column
                                disappears from both at once, so a value can
                                never shift under the wrong header here. */}
                            {visibleColumns.map((col) => {
                              const def = col.columnDef;
                              const extraProps = def.cellProps ? def.cellProps(memberCtx) : {};
                              const className = [def.numeric ? styles.numeric : '', def.align === 'center' ? styles.colAlerta : '', extraProps.className || '']
                                .filter(Boolean)
                                .join(' ');
                              return (
                                <td
                                  key={col.id}
                                  data-col-id={col.id}
                                  {...extraProps}
                                  className={className || undefined}
                                >
                                  {def.cell(memberCtx)}
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <Pagination
        total={total}
        offset={offset}
        pageSize={pageSize}
        onOffsetChange={setOffset}
        onPageSizeChange={handlePageSizeChange}
      />
      </VentasMLLayout>

      <VariosVentaPctModal isOpen={variosPctModalOpen} onClose={() => setVariosPctModalOpen(false)} />
    </div>
  );
}
