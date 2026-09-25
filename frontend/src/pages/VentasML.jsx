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

import { Fragment, useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ShoppingBag, ShieldAlert, ChevronRight, AlertTriangle } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import VentasMLLayout from '../components/ventasMl/VentasMLLayout';
import SaleDetailPanel from '../components/ventasMl/SaleDetailPanel';
import SalesToolbar from '../components/ventasMl/SalesToolbar';
import FacetChips from '../components/ventasMl/FacetChips';
import AlertIcon from '../components/ventasMl/AlertIcon';
import RecalculatingBadge from '../components/ventasMl/RecalculatingBadge';
import ProductCell from '../components/ventasMl/ProductCell';
import { useVentasMLFilters } from '../hooks/useVentasMLFilters';
import VariosVentaPctModal from '../components/VariosVentaPctModal';
import DateRangeFilter from '../components/DateRangeFilter';
import styles from './VentasML.module.css';

const PAGE_SIZE = 50;

const EMPTY_FACETS = {
  operation_status: {},
  goods_status: {},
  operation_status_total: 0,
  goods_status_total: 0,
};

const OPERATION_STATUS_LABELS = {
  paid: 'Pagada',
  cancelled: 'Cancelada',
  // A cancellation Mercado Libre covered through its Buyer Protection
  // Programme — the money still arrived, so this must not read as a plain
  // cancellation.
  cancelled_ml_covered: 'Cubierta por ML',
  in_dispute: 'En disputa',
  delivered: 'Entregada',
  unknown: 'A revisar',
  // Not a status the backend derives per order — the pack's orders
  // disagree. Never render a winner.
  mixed: 'Mixta',
};

const OPERATION_STATUS_BADGE_CLASS = {
  paid: 'badge-primary',
  cancelled: 'badge-danger',
  cancelled_ml_covered: 'badge-success',
  in_dispute: 'badge-warning',
  delivered: 'badge-success',
  unknown: 'badge-neutral',
  mixed: 'badge-warning',
};

// `mixed` is deliberately NOT a filter chip: it is a property of a row,
// not a value any order carries, so there is nothing to filter on.
const OPERATION_STATUS_OPTIONS = Object.keys(OPERATION_STATUS_LABELS).filter((v) => v !== 'mixed');

const GOODS_STATUS_LABELS = {
  unknown: 'A revisar',
  in_warehouse: 'En depósito',
  in_transit: 'En tránsito',
  delivered: 'Entregado',
  returned_undelivered: 'Devuelto sin entregar',
  mixed: 'Mixta',
};

const GOODS_STATUS_BADGE_CLASS = {
  unknown: 'badge-neutral',
  in_warehouse: 'badge-primary',
  in_transit: 'badge-warning',
  delivered: 'badge-success',
  returned_undelivered: 'badge-danger',
  mixed: 'badge-warning',
};

const GOODS_STATUS_OPTIONS = Object.keys(GOODS_STATUS_LABELS).filter((v) => v !== 'mixed');

// ml-ventas-modo-logistico PR6: `modo_logistico` badge. Known values come
// straight from `MlShipmentOps.logistic_type` (`resolve_modo_logistico`,
// backend): `self_service` is Flex, `fulfillment` is Full, `cross_docking`
// is Colecta. `retiro` is the tag-only fallback when there is no shipment
// at all. An UNRECOGNISED value is rendered VERBATIM — never folded into
// "desconocido" — because the backend passes a future ML logistic type
// through on purpose so it cannot silently vanish here.
const MODO_LOGISTICO_LABELS = {
  self_service: 'Flex',
  fulfillment: 'Full',
  cross_docking: 'Colecta',
  retiro: 'Retiro',
  desconocido: 'Desconocido',
  // The group's modo_logistico when its orders disagree — same "mixed"
  // discipline as the two status axes above.
  mixed: 'Mixto',
};

const MODO_LOGISTICO_BADGE_CLASS = {
  self_service: 'badge-primary',
  fulfillment: 'badge-success',
  cross_docking: 'badge-warning',
  retiro: 'badge-neutral',
  desconocido: 'badge-neutral',
  mixed: 'badge-warning',
};

// Locale pinned, like every other page in the app (`Prearmado.jsx`,
// `DashboardMetricasML.jsx`). Left to the browser, a client in en-US
// renders MM/DD and AM/PM in the middle of a DD/MM table.
const DATE_FORMAT = new Intl.DateTimeFormat('es-AR', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

function formatDate(value) {
  if (!value) return '—';
  return DATE_FORMAT.format(new Date(value));
}

// With thousands separators. `1234567.50 ARS` in a column of amounts
// forces the operator to count digits to tell 1,2M from 123k.
function formatMoney(value, currencyId) {
  if (value === null || value === undefined) return '—';
  const amount = new Intl.NumberFormat('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
  return currencyId ? `${amount} ${currencyId}` : amount;
}

// ml-ventas-neto-iibb-varios PR1.T12: the listing's own explanation for
// why Neto reads higher than what ML deposited -- same text and fields as
// the drawer's sub-line (decision c), rendered as a `title` tooltip on
// the Neto button rather than a permanent row, since the listing has no
// room for a second line per row.
// ventas-ml-rediseno PR14.T5/T9 (LISTING R28/R29, SM R3/R9): the row-level
// summaries below are the ONLY client-side aggregation this table does over
// per-order fields, and deliberately never touch money -- `group_neto`/
// `group_total_gauss` already come pre-aggregated from the backend
// (`SaleGroup`), null whenever any member is unresolved. These three only
// decide which ICON/BADGE the pack-level row shows.

// Worst-first, same discipline as the existing status "mixed" precedent:
// a pack with any order in `error` reads as `error`, not an average.
function groupAlertLevel(orders) {
  if (orders.some((o) => o.alert_level === 'error')) return 'error';
  if (orders.some((o) => o.alert_level === 'warning')) return 'warning';
  return 'ok';
}

// Same precedence as `RecalculatingBadge` expects: `recalculating` beats
// `failed` beats `pending` beats `ok`, so the pack row never claims a
// stale/finished state while one of its orders is still catching up.
function groupMetricsState(orders) {
  if (orders.some((o) => o.metrics_state === 'recalculating')) return 'recalculating';
  if (orders.some((o) => o.metrics_state === 'failed')) return 'failed';
  if (orders.some((o) => o.metrics_state === 'pending')) return 'pending';
  return 'ok';
}

// A pack's icon is only shown when every order agrees on `item_category` --
// showing one item's category for a multi-item parcel would misrepresent
// the other items, so this renders nothing (falls back to no icon) instead
// of picking an arbitrary member.
function groupCategory(orders) {
  const categories = new Set(orders.map((o) => o.item_category).filter(Boolean));
  return categories.size === 1 ? [...categories][0] : null;
}

// ventas-ml-producto-listado-pr10b (PR14.T5/T6 blocker): a pack's row is
// one PARCEL but can carry several orders, each with its own item(s) — the
// collapsed row must represent EVERY item across the whole pack, never
// just the first order's. `ProductCell` itself only ever silently keeps
// the count of what it does not show inline (the "+N productos" badge);
// this flattens the source so that count is correct at the pack level too.
function groupItems(orders) {
  return orders.flatMap((o) => o.items || []);
}

// PR14 review fix P3: mirrors `_alert_level`'s own precedence
// (`ml_ventas_ops.py`) using only the fields the listing endpoint actually
// exposes per order (`metrics_state`, `neto`, `operation_status`,
// `goods_status`) -- `iva_reconcilia` is never sent to the FE, so a warning
// caused solely by that check falls back to the generic label rather than
// inventing a reason the data cannot back up.
function orderAlertReason(order) {
  if (!order) return undefined;
  if (order.metrics_state === 'failed') return 'El recálculo de esta venta falló.';
  if (order.metrics_state === 'pending') return 'Todavía no se calculó esta venta.';
  if (order.neto == null) return 'El neto de esta venta es desconocido.';
  if (order.metrics_state === 'recalculating') return 'Esta venta se está recalculando.';
  if (order.operation_status === 'unknown') return 'El estado de la operación todavía no se clasificó.';
  if (order.goods_status === 'unknown') return 'El estado de la mercadería todavía no se clasificó.';
  return 'Esta venta requiere revisión.';
}

// The group row's own alert_level is the worst among its orders
// (`groupAlertLevel`). The reason shown must come from an order that
// actually carries that level -- never a guess picked from an unrelated
// member.
function groupAlertReason(orders, level) {
  const culprit = orders.find((o) => o.alert_level === level);
  return orderAlertReason(culprit);
}

const TABLE_COLUMN_COUNT = 11;

function netoTooltip(netoDepositado, retencionesRecuperables) {
  if (!(retencionesRecuperables > 0)) return undefined;
  return `MP $ ${new Intl.NumberFormat('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(netoDepositado))} · SIRTAC $ ${new Intl.NumberFormat('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(retencionesRecuperables))}`;
}

export default function VentasML() {
  const latestRequestRef = useRef(0);
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('ml_ops.ver');

  const [sales, setSales] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [lastLoadedAt, setLastLoadedAt] = useState(null);
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

  // Panel selection lives in the `orden` URL param, consistent with this
  // screen's other URL-driven filters (PANEL R19 — see design D14). The
  // panel opens for a GROUP (pack or lone order) and stays open while the
  // operator picks another row -- it only carries the order_id the
  // per-order endpoint needs, since the backend resolves the whole pack's
  // breakdown from any order inside it.
  const { selectedOrderId, selectOrder, clearSelection, searchQuery, setSearchQuery } =
    useVentasMLFilters();

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

  const handleOperationStatusChange = useCallback((value) => {
    setOperationStatusFilter(value);
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
    setOffset(0);
  }, [setSearchQuery]);

  const hasActiveFilters = Boolean(
    operationStatusFilter || goodsStatusFilter || fechaDesde || fechaHasta || searchQuery
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
      const params = { limit: PAGE_SIZE, offset };
      if (operationStatusFilter) params.operation_status = operationStatusFilter;
      if (goodsStatusFilter) params.goods_status = goodsStatusFilter;
      if (fechaDesde) params.date_from = fechaDesde;
      if (fechaHasta) params.date_to = fechaHasta;
      // SEARCH R26: the search term combines with every other active
      // filter as an INTERSECTION — sent alongside them in the same
      // request, never as a separate call that replaces the filtered set.
      if (searchQuery) params.q = searchQuery;
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
  }, [puedeVer, operationStatusFilter, goodsStatusFilter, fechaDesde, fechaHasta, searchQuery, offset]);

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

  const isFirstPage = offset === 0;
  const isLastPage = offset + PAGE_SIZE >= total;
  const rangeFrom = total === 0 ? 0 : offset + 1;
  const rangeTo = Math.min(offset + PAGE_SIZE, total);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <ShoppingBag size={20} />
          <h1>Ventas ML</h1>
        </div>
        <div className={styles.headerActions}>
          <button
            type="button"
            className="btn-tesla outline sm"
            onClick={() => setVariosPctModalOpen(true)}
          >
            % de varios
          </button>
          <button type="button" className="btn-tesla outline sm" onClick={cargarVentas} disabled={loading}>
            {loading ? 'Actualizando...' : 'Actualizar'}
          </button>
        </div>
      </div>

      <p className={styles.description}>
        Listado de ventas de Mercado Libre. El estado de la operación describe el dinero; el estado de la
        mercadería describe el producto — son ejes independientes a propósito.
      </p>

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

      <SalesToolbar
        value={searchQuery}
        onSearchChange={handleSearchChange}
        noResults={!loading && Boolean(searchQuery) && sales.length === 0}
      />

      <div className={styles.filters}>
        <div className={styles.filterRow}>
          <span className={styles.fieldLabel}>
            Operación
            <span className={styles.fieldLabelSub}>el dinero</span>
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

        <div className={styles.divider} />

        <div className={styles.filterRow}>
          <span className={styles.fieldLabel}>
            Mercadería
            <span className={styles.fieldLabelSub}>el producto</span>
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

        <div className={styles.divider} />

        <div className={styles.filterRow}>
          <span className={styles.fieldLabel}>Y además</span>
          <DateRangeFilter
            fechaDesde={fechaDesde}
            fechaHasta={fechaHasta}
            filtroActivo={dateRangeFiltro}
            onChange={handleDateRangeChange}
          />
          {hasActiveFilters && (
            <button type="button" className={styles.clearFilters} onClick={clearFilters}>
              Limpiar filtros
            </button>
          )}
          <div className={styles.spacer} />
          {lastLoadedAt && (
            <span className={styles.stale}>actualizado {formatDate(lastLoadedAt)}</span>
          )}
        </div>
      </div>

      <VentasMLLayout
        selectedOrderId={selectedOrderId}
        onClear={clearSelection}
        panel={<SaleDetailPanel orderId={selectedOrderId} onClose={clearSelection} />}
      >
      <div className={styles.tableCard}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.colAlerta} aria-label="Alerta" />
              <th className={styles.colProducto}>Producto</th>
              <th className={styles.colOrden}>Orden</th>
              <th>Fecha</th>
              <th>Comprador</th>
              <th>Operación</th>
              <th>Mercadería</th>
              <th>Envío</th>
              <th className={styles.numeric}>Importe</th>
              <th className={styles.numeric}>Neto</th>
              <th className={styles.numeric}>Total Gauss</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className={styles.stateCell} colSpan={TABLE_COLUMN_COUNT}>
                  Cargando ventas…
                </td>
              </tr>
            ) : sales.length === 0 ? (
              <tr>
                <td className={styles.stateCell} colSpan={TABLE_COLUMN_COUNT}>
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
                return (
                  <Fragment key={group.group_key}>
                    {/* The row click is a MOUSE SHORTCUT, deliberately not a
                        widget: the keyboard route is the real <button> in
                        the Neto cell below. Making a <tr> focusable would
                        announce a control that screen readers cannot
                        describe, and the button already carries the
                        accessible name. */}
                    <tr
                      className={`${isPack ? styles.packRow : ''} ${
                        representativeOrderId != null ? styles.clickableRow : ''
                      }`.trim()}
                      onClick={
                        representativeOrderId != null
                          ? () => openDrawer(representativeOrderId)
                          : undefined
                      }
                    >
                      <td className={styles.colAlerta}>
                        <AlertIcon level={groupLevel} reason={groupAlertReason(orders, groupLevel)} />
                      </td>
                      <td className={styles.colProducto}>
                        <ProductCell items={groupItems(orders)} category={groupCategory(orders)} />
                      </td>
                      <td className={styles.colOrden}>
                        {isPack ? (
                          <button
                            type="button"
                            className={styles.packToggle}
                            aria-expanded={isOpen}
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleExpanded(group.group_key);
                            }}
                          >
                            <ChevronRight
                              size={14}
                              className={`${styles.chevron} ${isOpen ? styles.chevronOpen : ''}`}
                              aria-hidden="true"
                            />
                            <span>
                              <span className={styles.orden}>Pack {group.pack_id}</span>
                              <span className={styles.subline}>
                                {orders.length} órdenes
                              </span>
                            </span>
                          </button>
                        ) : (
                          <span className={styles.orden}>{orders[0]?.order_id ?? group.group_key}</span>
                        )}
                      </td>
                      <td className={styles.fecha}>{formatDate(group.date_created)}</td>
                      <td>{group.buyer_nickname || '—'}</td>
                      <td>
                        <span
                          className={`badge ${OPERATION_STATUS_BADGE_CLASS[group.operation_status] || 'badge-neutral'}`}
                        >
                          {OPERATION_STATUS_LABELS[group.operation_status] || group.operation_status}
                        </span>
                      </td>
                      <td>
                        <span
                          className={`badge ${GOODS_STATUS_BADGE_CLASS[group.goods_status] || 'badge-neutral'}`}
                        >
                          {GOODS_STATUS_LABELS[group.goods_status] || group.goods_status}
                        </span>
                      </td>
                      <td>
                        <span
                          className={`badge ${MODO_LOGISTICO_BADGE_CLASS[group.modo_logistico] || 'badge-neutral'}`}
                        >
                          {MODO_LOGISTICO_LABELS[group.modo_logistico] || group.modo_logistico}
                        </span>
                        {/* PR14 review fix P1: a lone sale has no
                            pack-member block to render this in -- it must
                            carry its own subline. */}
                        {loneOrder &&
                          (loneOrder.city || loneOrder.province || loneOrder.shipping_substatus) && (
                            <span className={styles.subline}>
                              {[loneOrder.city, loneOrder.province].filter(Boolean).join(', ') || '—'}
                              {loneOrder.shipping_substatus ? ` · ${loneOrder.shipping_substatus}` : ''}
                            </span>
                          )}
                      </td>
                      <td className={styles.numeric}>
                        {formatMoney(group.total_amount, group.currency_id)}
                      </td>
                      <td className={styles.numeric}>
                        {(() => {
                          const metricsState = groupMetricsState(orders);
                          // SM R3/R9: a pack with any unresolved member
                          // never shows the (possibly stale) sum as the
                          // current amount -- the badge replaces it.
                          const content =
                            metricsState !== 'ok' ? (
                              <RecalculatingBadge state={metricsState} />
                            ) : (
                              formatMoney(group.neto, group.currency_id)
                            );
                          if (representativeOrderId != null) {
                            return (
                              // PR14 review fix P2: this button IS the
                              // keyboard route to the detail panel (see the
                              // <tr> comment above) -- it must survive
                              // every metrics_state, carrying the badge as
                              // its content instead of being replaced by it.
                              <button
                                type="button"
                                className={styles.netoButton}
                                // The visible text is the amount, so without
                                // this a screen reader announces "button,
                                // 82,50 ARS" and never says what it does.
                                aria-label="Ver desglose de costos"
                                title={
                                  metricsState === 'ok'
                                    ? netoTooltip(group.neto_depositado, group.retenciones_recuperables)
                                    : undefined
                                }
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openDrawer(representativeOrderId);
                                }}
                              >
                                {content}
                              </button>
                            );
                          }
                          return content;
                        })()}
                      </td>
                      <td className={styles.numeric}>
                        {groupMetricsState(orders) !== 'ok' ? (
                          <RecalculatingBadge state={groupMetricsState(orders)} />
                        ) : (
                          <>
                            {formatMoney(group.total_gauss, group.currency_id)}
                            {/* total-gauss-provisorio: the pack sum already
                                includes a member's provisional figure -- the
                                badge says so at THIS level too, not only in
                                the drawer (product owner's explicit
                                decision). */}
                            {group.total_gauss_provisional && (
                              <span
                                className={`badge badge-warning ${styles.provisionalBadge}`}
                                title={`Calculado sin ${(group.total_gauss_provisional_falta || 'Envío Flex').toLowerCase()}: todavía no se cargó la etiqueta de envío.`}
                              >
                                Provisorio
                              </span>
                            )}
                            {/* PR14 review fix P1: markup was only ever
                                rendered inside the pack-member block -- a
                                lone sale must carry its own. */}
                            {loneOrder && loneOrder.markup !== null && loneOrder.markup !== undefined && (
                              <span className={styles.markup}>
                                {' '}
                                · {new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(loneOrder.markup)}%
                              </span>
                            )}
                          </>
                        )}
                      </td>
                    </tr>
                    {/* The orders inside the parcel. Rendered only when
                        opened, and never for a lone order — there is
                        nothing to unfold. */}
                    {isPack &&
                      isOpen &&
                      orders.map((order) => (
                        <tr
                          key={order.order_id}
                          className={`${styles.memberRow} ${styles.clickableRow}`}
                          onClick={() => openDrawer(order.order_id)}
                        >
                          <td className={styles.colAlerta}>
                            <AlertIcon level={order.alert_level} reason={orderAlertReason(order)} />
                          </td>
                          <td className={styles.colProducto}>
                            <ProductCell items={order.items} category={order.item_category} />
                          </td>
                          <td className={styles.colOrden}>
                            <span className={styles.memberOrden}>{order.order_id}</span>
                          </td>
                          <td className={styles.fecha}>{formatDate(order.date_created)}</td>
                          <td />
                          <td>
                            <span
                              className={`badge ${OPERATION_STATUS_BADGE_CLASS[order.operation_status] || 'badge-neutral'}`}
                            >
                              {OPERATION_STATUS_LABELS[order.operation_status] || order.operation_status}
                            </span>
                          </td>
                          <td>
                            <span
                              className={`badge ${GOODS_STATUS_BADGE_CLASS[order.goods_status] || 'badge-neutral'}`}
                            >
                              {GOODS_STATUS_LABELS[order.goods_status] || order.goods_status}
                            </span>
                          </td>
                          <td>
                            <span
                              className={`badge ${MODO_LOGISTICO_BADGE_CLASS[order.modo_logistico] || 'badge-neutral'}`}
                            >
                              {MODO_LOGISTICO_LABELS[order.modo_logistico] || order.modo_logistico}
                            </span>
                            {(order.city || order.province || order.shipping_substatus) && (
                              <span className={styles.subline}>
                                {[order.city, order.province].filter(Boolean).join(', ') || '—'}
                                {order.shipping_substatus ? ` · ${order.shipping_substatus}` : ''}
                              </span>
                            )}
                          </td>
                          <td className={styles.numeric}>
                            {formatMoney(order.total_amount, order.currency_id)}
                          </td>
                          <td className={styles.numeric}>
                            {(() => {
                              const isRecalc = order.metrics_state && order.metrics_state !== 'ok';
                              // PR14 review fix P2: same discipline as the
                              // group row -- the button is the keyboard
                              // affordance and must survive every
                              // metrics_state, carrying the badge as its
                              // content.
                              return (
                                <button
                                  type="button"
                                  className={styles.netoButton}
                                  aria-label="Ver desglose de costos"
                                  title={
                                    isRecalc
                                      ? undefined
                                      : netoTooltip(order.neto_depositado, order.retenciones_recuperables)
                                  }
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    openDrawer(order.order_id);
                                  }}
                                >
                                  {isRecalc ? (
                                    <RecalculatingBadge state={order.metrics_state} />
                                  ) : (
                                    formatMoney(order.neto, order.currency_id)
                                  )}
                                </button>
                              );
                            })()}
                          </td>
                          <td className={styles.numeric}>
                            {order.metrics_state && order.metrics_state !== 'ok' ? (
                              <RecalculatingBadge state={order.metrics_state} />
                            ) : (
                              <>
                                {formatMoney(order.total_gauss, order.currency_id)}
                                {order.total_gauss_provisional && (
                                  <span
                                    className={`badge badge-warning ${styles.provisionalBadge}`}
                                    title={`Calculado sin ${(order.total_gauss_provisional_falta || 'Envío Flex').toLowerCase()}: todavía no se cargó la etiqueta de envío.`}
                                  >
                                    Provisorio
                                  </span>
                                )}
                                {order.markup !== null && order.markup !== undefined && (
                                  <span className={styles.markup}>
                                    {' '}
                                    · {new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(order.markup)}%
                                  </span>
                                )}
                              </>
                            )}
                          </td>
                        </tr>
                      ))}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className={styles.paginationBar}>
        <button
          type="button"
          className="btn-tesla ghost sm"
          onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
          disabled={isFirstPage}
        >
          Anterior
        </button>
        <span>
          mostrando {rangeFrom}-{rangeTo} de {total} ventas
        </span>
        <button
          type="button"
          className="btn-tesla ghost sm"
          onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
          disabled={isLastPage}
        >
          Siguiente
        </button>
      </div>
      </VentasMLLayout>

      <VariosVentaPctModal isOpen={variosPctModalOpen} onClose={() => setVariosPctModalOpen(false)} />
    </div>
  );
}
