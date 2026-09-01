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
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { ShoppingBag, ShieldAlert } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import styles from './VentasML.module.css';

const PAGE_SIZE = 50;

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
};

const OPERATION_STATUS_BADGE_CLASS = {
  paid: 'badge-primary',
  cancelled: 'badge-danger',
  cancelled_ml_covered: 'badge-success',
  in_dispute: 'badge-warning',
  delivered: 'badge-success',
  unknown: 'badge-neutral',
};

const OPERATION_STATUS_OPTIONS = Object.keys(OPERATION_STATUS_LABELS);

const GOODS_STATUS_LABELS = {
  unknown: 'A revisar',
  in_warehouse: 'En depósito',
  in_transit: 'En tránsito',
  delivered: 'Entregado',
  returned_undelivered: 'Devuelto sin entregar',
};

const GOODS_STATUS_BADGE_CLASS = {
  unknown: 'badge-neutral',
  in_warehouse: 'badge-primary',
  in_transit: 'badge-warning',
  delivered: 'badge-success',
  returned_undelivered: 'badge-danger',
};

const GOODS_STATUS_OPTIONS = Object.keys(GOODS_STATUS_LABELS);

function formatDate(value) {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

function formatMoney(value, currencyId) {
  if (value === null || value === undefined) return '—';
  return `${Number(value).toFixed(2)} ${currencyId || ''}`.trim();
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

  const [facets, setFacets] = useState({ operation_status: {}, goods_status: {} });

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
      setTotal(data.total ?? 0);
      setFacets(data.facets || { operation_status: {}, goods_status: {} });
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
      setFacets({ operation_status: {}, goods_status: {} });
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

      <div className={styles.filtersBar} role="group" aria-label="Filtrar por estado de operación">
        <span className={styles.filterGroupLabel}>Operación</span>
        {OPERATION_STATUS_OPTIONS.map((value) => (
          <button
            key={value}
            type="button"
            className={`${styles.chip} ${operationStatusFilter === value ? styles.chipActive : ''}`}
            aria-pressed={operationStatusFilter === value}
            onClick={() => toggleOperationStatus(value)}
          >
            {OPERATION_STATUS_LABELS[value]} · {facets.operation_status?.[value] ?? 0}
          </button>
        ))}
      </div>

      <div className={styles.filtersBar} role="group" aria-label="Filtrar por estado de la mercadería">
        <span className={styles.filterGroupLabel}>Mercadería</span>
        {GOODS_STATUS_OPTIONS.map((value) => (
          <button
            key={value}
            type="button"
            className={`${styles.chip} ${goodsStatusFilter === value ? styles.chipActive : ''}`}
            aria-pressed={goodsStatusFilter === value}
            onClick={() => toggleGoodsStatus(value)}
          >
            {GOODS_STATUS_LABELS[value]} · {facets.goods_status?.[value] ?? 0}
          </button>
        ))}
      </div>

      <div className={styles.filtersBar}>
        <label className={styles.monthLabel} htmlFor="ventas-ml-sold-month">
          Mes de la venta
        </label>
        <input
          id="ventas-ml-sold-month"
          type="month"
          className={styles.monthInput}
          aria-label="Mes de la venta"
          value={soldMonthFilter}
          onChange={(e) => handleSoldMonthChange(e.target.value)}
        />
        {hasActiveFilters && (
          <button type="button" className="btn-tesla ghost sm" onClick={clearFilters}>
            Limpiar filtros
          </button>
        )}
      </div>

      <div className="table-container-tesla">
        <table className="table-tesla">
          <thead>
            <tr>
              <th>Orden</th>
              <th>Fecha</th>
              <th>Comprador</th>
              <th>Importe</th>
              <th>Operación</th>
              <th>Mercadería</th>
              <th>Envío</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className={styles.loadingCell} colSpan={7}>
                  Cargando ventas...
                </td>
              </tr>
            ) : sales.length === 0 ? (
              <tr>
                <td className={styles.emptyCell} colSpan={7}>
                  No hay ventas que coincidan con los filtros
                </td>
              </tr>
            ) : (
              sales.map((sale) => (
                <tr key={sale.order_id}>
                  <td>{sale.order_id}</td>
                  <td>{formatDate(sale.date_created)}</td>
                  <td>{sale.buyer_nickname || '—'}</td>
                  <td>{formatMoney(sale.total_amount, sale.currency_id)}</td>
                  <td>
                    <span className={`badge ${OPERATION_STATUS_BADGE_CLASS[sale.operation_status] || 'badge-neutral'}`}>
                      {OPERATION_STATUS_LABELS[sale.operation_status] || sale.operation_status}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${GOODS_STATUS_BADGE_CLASS[sale.goods_status] || 'badge-neutral'}`}>
                      {GOODS_STATUS_LABELS[sale.goods_status] || sale.goods_status}
                    </span>
                  </td>
                  <td>{sale.shipping_status || '—'}</td>
                </tr>
              ))
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

      {lastLoadedAt && (
        <p className={styles.stale}>Actualizado: {lastLoadedAt.toLocaleString()}</p>
      )}
    </div>
  );
}
