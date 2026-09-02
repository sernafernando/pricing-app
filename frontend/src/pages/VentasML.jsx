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
 */

import { Fragment, useState, useEffect, useCallback, useRef } from 'react';
import { ShoppingBag, ShieldAlert, ChevronRight } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
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

  const [operationStatusFilter, setOperationStatusFilter] = useState('');
  const [goodsStatusFilter, setGoodsStatusFilter] = useState('');
  const [soldMonthFilter, setSoldMonthFilter] = useState('');

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

  const handleOperationStatusChange = useCallback((value) => {
    setOperationStatusFilter(value);
    setOffset(0);
  }, []);

  const handleGoodsStatusChange = useCallback((value) => {
    setGoodsStatusFilter(value);
    setOffset(0);
  }, []);

  const handleSoldMonthChange = useCallback((value) => {
    setSoldMonthFilter(value);
    setOffset(0);
  }, []);

  const toggleOperationStatus = useCallback(
    (value) => {
      handleOperationStatusChange(operationStatusFilter === value ? '' : value);
    },
    [operationStatusFilter, handleOperationStatusChange]
  );

  const toggleGoodsStatus = useCallback(
    (value) => {
      handleGoodsStatusChange(goodsStatusFilter === value ? '' : value);
    },
    [goodsStatusFilter, handleGoodsStatusChange]
  );

  const clearFilters = useCallback(() => {
    setOperationStatusFilter('');
    setGoodsStatusFilter('');
    setSoldMonthFilter('');
    setOffset(0);
  }, []);

  const hasActiveFilters = Boolean(operationStatusFilter || goodsStatusFilter || soldMonthFilter);

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
      if (soldMonthFilter) params.sold_month = soldMonthFilter;
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
  }, [puedeVer, operationStatusFilter, goodsStatusFilter, soldMonthFilter, offset]);

  useEffect(() => {
    cargarVentas();
  }, [cargarVentas]);

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

      <div className={styles.filters}>
        <div className={styles.filterRow} role="group" aria-label="Filtrar por estado de operación">
          <span className={styles.fieldLabel}>
            Operación
            <span className={styles.fieldLabelSub}>el dinero</span>
          </span>
          {/* "Todas" is a chip like the rest, not a hidden empty state:
              clearing one axis has to be as reachable as setting it. */}
          <button
            type="button"
            className={`${styles.filter} ${operationStatusFilter === '' ? styles.filterActive : ''}`}
            aria-pressed={operationStatusFilter === ''}
            onClick={() => handleOperationStatusChange('')}
          >
            Todas · {facets.operation_status_total ?? 0}
          </button>
          {OPERATION_STATUS_OPTIONS.map((value) => (
            <button
              key={value}
              type="button"
              className={`${styles.filter} ${operationStatusFilter === value ? styles.filterActive : ''}`}
              aria-pressed={operationStatusFilter === value}
              onClick={() => toggleOperationStatus(value)}
            >
              {OPERATION_STATUS_LABELS[value]} · {facets.operation_status?.[value] ?? 0}
            </button>
          ))}
        </div>

        <div className={styles.divider} />

        <div className={styles.filterRow} role="group" aria-label="Filtrar por estado de la mercadería">
          <span className={styles.fieldLabel}>
            Mercadería
            <span className={styles.fieldLabelSub}>el producto</span>
          </span>
          <button
            type="button"
            className={`${styles.filter} ${goodsStatusFilter === '' ? styles.filterActive : ''}`}
            aria-pressed={goodsStatusFilter === ''}
            onClick={() => handleGoodsStatusChange('')}
          >
            Todas · {facets.goods_status_total ?? 0}
          </button>
          {GOODS_STATUS_OPTIONS.map((value) => (
            <button
              key={value}
              type="button"
              className={`${styles.filter} ${goodsStatusFilter === value ? styles.filterActive : ''}`}
              aria-pressed={goodsStatusFilter === value}
              onClick={() => toggleGoodsStatus(value)}
            >
              {GOODS_STATUS_LABELS[value]} · {facets.goods_status?.[value] ?? 0}
            </button>
          ))}
        </div>

        <div className={styles.divider} />

        <div className={styles.filterRow}>
          <span className={styles.fieldLabel}>Y además</span>
          <input
            id="ventas-ml-sold-month"
            type="month"
            className={styles.monthInput}
            aria-label="Mes de la venta"
            value={soldMonthFilter}
            onChange={(e) => handleSoldMonthChange(e.target.value)}
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

      <div className={styles.tableCard}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.colOrden}>Orden</th>
              <th>Fecha</th>
              <th>Comprador</th>
              <th>Operación</th>
              <th>Mercadería</th>
              <th className={styles.numeric}>Importe</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className={styles.stateCell} colSpan={6}>
                  Cargando ventas…
                </td>
              </tr>
            ) : sales.length === 0 ? (
              <tr>
                <td className={styles.stateCell} colSpan={6}>
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
                return (
                  <Fragment key={group.group_key}>
                    <tr className={isPack ? styles.packRow : undefined}>
                      <td className={styles.colOrden}>
                        {isPack ? (
                          <button
                            type="button"
                            className={styles.packToggle}
                            aria-expanded={isOpen}
                            onClick={() => toggleExpanded(group.group_key)}
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
                      <td className={styles.numeric}>
                        {formatMoney(group.total_amount, group.currency_id)}
                      </td>
                    </tr>
                    {/* The orders inside the parcel. Rendered only when
                        opened, and never for a lone order — there is
                        nothing to unfold. */}
                    {isPack &&
                      isOpen &&
                      orders.map((order) => (
                        <tr key={order.order_id} className={styles.memberRow}>
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
                          <td className={styles.numeric}>
                            {formatMoney(order.total_amount, order.currency_id)}
                            {/* ML's own shipping status, per order. The
                                header row cannot carry it — a pack's
                                orders can ship separately — and
                                `goods_status` is the coarse reading of
                                it, not a replacement. */}
                            {order.shipping_status && (
                              <span className={styles.subline}>{order.shipping_status}</span>
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

    </div>
  );
}
