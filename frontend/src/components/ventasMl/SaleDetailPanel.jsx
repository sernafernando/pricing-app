/**
 * SaleDetailPanel — a sale's cost breakdown, rendered inside
 * `VentasMLLayout`'s NON-modal `<aside>` (ventas-ml-rediseno PR13).
 *
 * This is the content that used to be `DesgloseDrawer.jsx`'s modal: same
 * sections (Producto/Comprador — actually Monto de la operación/items,
 * the line list, IVA por alícuota, Total Gauss chain), same data source
 * (`GET /ml-ventas-ops/orders/{order_id}`), same rendering rules —
 * verbatim, per design D14 and PANEL R16. What changed is the shell: no
 * `.overlay`, no `role="dialog"`/`aria-modal`, no focus trap, no
 * `document.body.style.overflow` lock. `VentasMLLayout` decides WHETHER
 * this renders at all (only while a row is selected — PANEL R18); this
 * component only reacts to `orderId` and fetches/renders its detail.
 *
 * Picking a different row updates `orderId` and re-fetches WITHOUT
 * unmounting this component — same "never closes on its own" contract
 * `DesgloseDrawer` had, now driven by `VentasML.jsx`'s `useVentasMLFilters`
 * selection instead of local state.
 *
 * The lines render exactly as `GET /ml-ventas-ops/orders/{order_id}` sends
 * them, in order, with one exception: `origen="propio"` lines are dropped
 * from this list. Those are costs WE pay that ML never saw and do NOT sit
 * inside `neto` (see `OperationBreakdown`'s docstring in
 * `breakdown_service.py`) — showing them above "Neto" would read as
 * subtracted from it, and the Flex one already appears, genuinely
 * subtracted, in the Total Gauss chain below. No other reordering,
 * renaming, or filtering happens here. The backend is the single source of
 * truth for the breakdown; duplicating its judgment here would let the
 * two disagree.
 *
 * `incompleto` never renders a total that looks closed: the amount stays
 * visible (it can be a real partial number, not a placeholder) but
 * visually marked, with the reason spelled out for the operator instead of
 * ML's raw incomplete_reasons code.
 *
 * ml-ventas-modo-logistico PR6 adds two more sections, both from the SAME
 * `GET /ml-ventas-ops/orders/{order_id}` response, never recomputed here:
 *  - `iva_decomposicion` (PR4): the neto split by IVA rate. `reconcilia:
 *    false` renders the NAMED reason instead of a componentes table — a
 *    partial split would look like an arithmetic bug in this panel.
 *  - `cadena_total_gauss` (PR5): neto sin IVA minus each applicable
 *    deduction, in chain order. A `null` link is shown as "—" and named —
 *    UNKNOWN is never a zero, and Total Gauss itself is only ever shown
 *    when every link in the chain resolved.
 */

import { useEffect, useCallback, useState, useRef } from 'react';
import { X, TriangleAlert, ExternalLink, RefreshCw, ReceiptText } from 'lucide-react';
import api from '../../services/api';
import CopyButton from './CopyButton';
import StatusPill from './StatusPill';
import SaleContextSections, { ProductSection } from './SaleContextSections';
import {
  mlSaleUrl,
  timeAgo,
  formatDateTime,
  OPERATION_STATUS_LABELS,
  GOODS_STATUS_LABELS,
} from '../../utils/ventasMlFormat';
import {
  formatDeduction,
  formatSignedMoney,
  markupTone,
  moneyTone,
  OPERATION_STATUS_TONE,
  GOODS_STATUS_TONE,
} from '../../utils/ventasMlTone';
import styles from './SaleDetailPanel.module.css';

const INCOMPLETE_REASON_LABELS = {
  // Each label says which WAY the total is wrong, not just that it is.
  // "Incomplete" alone leaves the operator guessing whether the number
  // in front of them is too high or too low, which is the one thing they
  // need in order to decide anything with it.
  payments_not_synced: 'Faltan los pagos de esta venta: el sincronizador todavía no los trajo.',
  payments_not_countable:
    'Los pagos de esta venta llegaron, pero ninguno se puede computar: revisá su estado en MercadoLibre.',
  billing_not_swept:
    'Falta el barrido de facturación: los cargos que ML factura aparte, como el envío, todavía no se descontaron. El neto real es MENOR que el que ves acá.',
};

// ml-ventas-modo-logistico PR6, mirrors `iva.py`'s named RAZON_* constants
// verbatim — the backend names WHY the split failed, never a bare "no
// reconcilia" that reads like an arithmetic bug in this panel.
const RAZON_LABELS = {
  venta_con_devolucion:
    'Esta venta tuvo una devolución: no se sabe qué ítems volvieron, así que el IVA no se puede desglosar por alícuota.',
  item_sin_cantidad: 'Falta la cantidad de un ítem de esta venta.',
  // The historical case (PR3 froze costs only for new ingestions): most
  // sales made before it carry no frozen cost at all, and that must read
  // as "sin costo congelado", never as a generic error.
  item_sin_costo_congelado: 'Sin costo congelado: esta venta es anterior a la congelación de costos.',
  costo_sin_item: 'Hay un costo congelado sin ítem asociado en esta venta.',
  sin_pagos_sincronizados: 'Todavía no se sincronizaron los pagos de esta venta.',
};

// ml-ventas-modo-logistico PR5's deduction codes (`deducciones.py`), in the
// same chain order the backend already applies them.
const DEDUCCION_LABELS = {
  costo_mercaderia: 'Costo de mercadería',
  envio_flex: 'Envío Flex',
  varios: '% de varios',
  // ML pays the seller for the Flex shipping it delivers: income, shown as `(+)`.
  bonificacion_envio: 'Bonificación por envío',
};

function formatAlicuota(value) {
  if (value === null || value === undefined) return 'Sin alícuota';
  return `${formatAmount(value)}%`;
}

function formatAmount(value) {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function formatMoney(value) {
  return `$ ${formatAmount(value)}`;
}

// Product-owner request: "no están desglosados, no sé de qué es cada cosa"
// -- the reason the per-item list cannot be trusted to add up, spelled out
// same discipline as `INCOMPLETE_REASON_LABELS` above: never a bare code.
// The heading IS these lines' own sum, so "la lista no suma el total" is
// no longer a thing that can happen -- these reasons all mean the TOTAL
// could not be formed, and each names what the ERP is missing so the
// reader knows where to go.
const ITEM_LINES_RAZON_LABELS = {
  item_lines_no_items: 'Esta venta no tiene ítems cargados.',
  item_lines_orden_sin_items:
    'Una de las órdenes de este pack no tiene ítems cargados, así que el monto de la operación estaría incompleto.',
  item_lines_item_sin_cantidad:
    'Uno o más ítems no tienen cantidad cargada, así que no se puede calcular el monto de la operación.',
  item_lines_item_sin_precio:
    'Uno o más ítems no tienen precio unitario cargado, así que no se puede calcular el monto de la operación.',
};

// `fuente` values are deliberately distinct (see `MlOrderItemCosto`'s
// module docstring): `erp_*` is the CURRENT ERP cost, `hist_*` a DATED
// historical cost from the backfill, `hist_combo` a combo/kit's cost
// SUMMED from its components. Flattening these into one generic "ERP"
// label would hide exactly the distinction an operator needs to trust
// (or distrust) the figure.
const FUENTE_LABELS = {
  erp_publicacion: 'ERP (por publicación)',
  erp_sku: 'ERP (por SKU)',
  hist_publicacion: 'Histórico (por publicación)',
  hist_sku: 'Histórico (por SKU)',
  hist_combo: 'Histórico (combo)',
};

function formatCostoFecha(value) {
  if (!value) return null;
  const [year, month, day] = value.split('-');
  return `${day}/${month}/${year}`;
}

// Prefers the backend's own message (the resync endpoint explains WHAT failed
// and that nothing changed) over a generic one.
function resyncErrorMessage(err) {
  const data = err?.response?.data;
  return data?.error?.message || (typeof data?.detail === 'string' ? data.detail : null) || 'No se pudo resincronizar la venta.';
}

export default function SaleDetailPanel({
  orderId,
  onClose,
  canResync = false,
  lastSyncedAt = null,
  onResynced,
  listOrder = null,
}) {
  const [breakdown, setBreakdown] = useState(null);
  // ml-ventas-modo-logistico PR6: the IVA split and the Total Gauss chain,
  // both from the SAME detail response. Kept separate from `breakdown`
  // (the older `origen: api/propio` lines) since they are two different
  // views of the sale, not one replacing the other.
  const [ivaDecomposicion, setIvaDecomposicion] = useState(null);
  const [cadenaTotalGauss, setCadenaTotalGauss] = useState(null);
  // ODD ventas-ml-ui-pendiente T4: who bought, how it was paid, how it ships
  // -- from the same response, rendered by `SaleContextSections`.
  const [orderInfo, setOrderInfo] = useState(null);
  const [shipmentInfo, setShipmentInfo] = useState(null);
  const [orderItems, setOrderItems] = useState([]);
  const [loading, setLoading] = useState(false);
  // ODD ventas-ml-ui-pendiente T7: per-sale resync (ML re-fetch + recompute).
  const [resyncing, setResyncing] = useState(false);
  const [resyncError, setResyncError] = useState(null);
  const [resyncDone, setResyncDone] = useState(false);
  const [errorKind, setErrorKind] = useState(null); // 'generic' | null

  // Same sequence guard `VentasML.jsx` uses for its list fetch: selecting
  // row A then row B fast can land A's response last. Without this, the
  // panel would show A's money while its header still describes B --
  // worse than showing nothing, since the operator reads it as B's number.
  const latestRequestRef = useRef(0);

  const loadBreakdown = useCallback(async () => {
    if (orderId === null || orderId === undefined) return;
    const requestId = ++latestRequestRef.current;
    setLoading(true);
    setErrorKind(null);
    try {
      const { data } = await api.get(`/ml-ventas-ops/orders/${orderId}`);
      if (requestId !== latestRequestRef.current) return;
      setBreakdown(data.breakdown || null);
      setIvaDecomposicion(data.iva_decomposicion || null);
      setCadenaTotalGauss(data.cadena_total_gauss || null);
      setOrderInfo(data.order || null);
      setShipmentInfo(data.shipment || null);
      setOrderItems(Array.isArray(data.items) ? data.items : []);
    } catch {
      if (requestId !== latestRequestRef.current) return;
      setErrorKind('generic');
      setBreakdown(null);
      setIvaDecomposicion(null);
      setCadenaTotalGauss(null);
      setOrderInfo(null);
      setShipmentInfo(null);
      setOrderItems([]);
    } finally {
      if (requestId === latestRequestRef.current) setLoading(false);
    }
  }, [orderId]);

  useEffect(() => {
    loadBreakdown();
  }, [loadBreakdown]);

  // Another sale was picked: a message about the previous one must not stay.
  useEffect(() => {
    setResyncError(null);
    setResyncDone(false);
  }, [orderId]);

  async function handleResync() {
    setResyncing(true);
    setResyncError(null);
    setResyncDone(false);
    try {
      await api.post(`/ml-ventas-ops/orders/${orderId}/resync`);
    } catch (err) {
      // The backend leaves the stored data untouched on failure, so there is
      // nothing to reload: just say what happened.
      setResyncError(resyncErrorMessage(err));
      setResyncing(false);
      return;
    }
    setResyncDone(true);
    await loadBreakdown();
    if (onResynced) onResynced();
    setResyncing(false);
  }

  // Defensive on purpose, same as the listing does with `group.orders`:
  // a malformed payload must not white-screen the panel. `incompleto`
  // arriving without its reasons is exactly the shape that would, and it
  // is the one the operator sees when something upstream is already
  // wrong -- the worst moment to lose the panel.
  const reasons = breakdown?.incomplete_reasons || [];
  // `origen="propio"` lines (today: the real Flex freight cost) are NOT
  // part of what ML subtracted to reach `neto` -- see
  // `OperationBreakdownSummary`'s docstring. Rendering them in this list
  // would read as "subtracted from Neto", which is false, AND double the
  // Flex line: it already appears, genuinely subtracted, in the Total
  // Gauss chain below (`cadena_total_gauss`'s `envio_flex` link).
  // ml-ventas-neto-iibb-varios D6: `origen="recuperable"` (today: a SIRTAC
  // withholding) is neither `propio` nor a real subtraction from `neto` --
  // it is shown, but separately, muted, and NOT part of the list the
  // operator reads as "this is what came off Neto".
  const lines = (breakdown?.lines || []).filter(
    (line) => line.origen !== 'propio' && line.origen !== 'recuperable',
  );
  const recuperables = (breakdown?.lines || []).filter((line) => line.origen === 'recuperable');

  // Same defensive discipline: an absent/`null` `iva_decomposicion` (a
  // stale client, or an old-shaped test fixture) must not white-screen the
  // panel — the new sections simply do not render.
  const componentesIva = ivaDecomposicion?.componentes || [];
  const razonesIva = ivaDecomposicion?.razones || [];
  const lineasGauss = cadenaTotalGauss?.lineas || [];
  const itemLines = breakdown?.item_lines || [];
  const costoItems = cadenaTotalGauss?.costo_mercaderia_items || [];
  const mlUrl = mlSaleUrl({ orderId, packId: orderInfo?.pack_id });

  const montoOperacion = breakdown?.monto_operacion;
  const gaussTone = moneyTone(cadenaTotalGauss?.total_gauss);
  const syncedAgo = timeAgo(lastSyncedAt);

  return (
    <>
      <div className={styles.header}>
        <div className={styles.headerTop}>
          <div className={styles.titleBlock}>
            {orderId !== null && orderId !== undefined ? (
              <div className={styles.identityRow}>
                <h2 className={styles.title}>
                  Orden <span className={styles.mono}>{orderId}</span>
                </h2>
                <CopyButton value={orderId} label="Copiar ID de la orden" />
                {mlUrl && orderInfo && (
                  <a className={styles.mlLink} href={mlUrl} target="_blank" rel="noopener noreferrer">
                    Ver en ML <ExternalLink size={12} aria-hidden="true" />
                  </a>
                )}
              </div>
            ) : null}
            <span className={styles.kicker}>Desglose de costos</span>
          </div>
          <button type="button" className={styles.closeButton} onClick={onClose} aria-label="Cerrar">
            <X size={18} />
          </button>
        </div>
        {/* The two status axes and the sale date come from the listing row
            (the detail endpoint carries neither): shown when the row is on
            the current page, omitted -- never guessed -- when it is not. */}
        {listOrder && (
          <div className={styles.headerMeta}>
            <StatusPill variant="soft" dot tone={OPERATION_STATUS_TONE[listOrder.operation_status]}>
              {OPERATION_STATUS_LABELS[listOrder.operation_status] || listOrder.operation_status}
            </StatusPill>
            <StatusPill variant="soft" dot tone={GOODS_STATUS_TONE[listOrder.goods_status]}>
              {GOODS_STATUS_LABELS[listOrder.goods_status] || listOrder.goods_status}
            </StatusPill>
            {listOrder.date_created && (
              <span className={styles.headerDate}>{formatDateTime(listOrder.date_created)}</span>
            )}
          </div>
        )}
      </div>

      <div className={styles.body}>
        {loading && <p className={styles.stateText}>Cargando desglose…</p>}

        {!loading && errorKind === 'generic' && <p className={styles.stateText}>Error al cargar el desglose.</p>}

        {/* A response that carries no `breakdown` is neither an error nor
            a zero, and without this the panel rendered blank: no loader,
            no error, no lines. Blank reads as "this sale left nothing",
            which is a number we never received. Say what happened. */}
        {!loading && !errorKind && !breakdown && (
          <p className={styles.stateText}>Esta venta todavía no tiene desglose disponible.</p>
        )}

        {!loading && !errorKind && breakdown && (
          <>
            <ProductSection items={orderItems} />

            <SaleContextSections order={orderInfo} shipment={shipmentInfo} />

            {/* "De dónde sale el neto" (detalle.jpg): the sale amount, every
                charge ML took off it as a red (−) line, and the Neto that is
                left. Same lines, same order the backend sent -- only signed
                and coloured now, so the subtraction reads as one. */}
            <section className={styles.card} aria-label="De dónde sale el neto">
              <div className={styles.cardTitleRow}>
                <h3 className={styles.cardTitle}>De dónde sale el neto</h3>
                <span className={styles.cardHint}>Liquidación ARS</span>
              </div>

              <ul className={styles.lineList}>
                {/* The starting figure every line below is taken off. `null`
                    (never `0`) when some member order's `paid_amount` has not
                    synced -- reads as "unknown", not as a sale worth nothing. */}
                <li className={styles.line}>
                  <span className={styles.lineSign}>(+)</span>
                  <span className={styles.lineConcepto}>Monto de la operación</span>
                  <span className={styles.lineMonto}>{formatSignedMoney(montoOperacion)}</span>
                </li>
              </ul>

              {/* Per-item breakdown of the figure above -- product-owner
                  request: "debería ser la suma de los productos y no están
                  desglosados". Compact/muted on purpose: supporting context
                  for the total above it, not a primary figure of its own. */}
              {itemLines.length > 0 && (
                <ul className={styles.itemLineList} aria-label="Detalle de productos">
                  {itemLines.map((item, index) => (
                    <li key={`${index}-${item.item_id}-${item.variation_id ?? ''}`} className={styles.itemLine}>
                      <span className={styles.itemLineTitle}>
                        {item.title || item.item_id}
                        {item.quantity && item.quantity > 1 ? ` (x${item.quantity})` : ''}
                      </span>
                      <span className={styles.itemLineMonto}>{formatAmount(item.monto)}</span>
                    </li>
                  ))}
                </ul>
              )}
              {breakdown.item_lines_reconcilia === false && (
                <p className={styles.itemLineWarning}>
                  {/* The fallback names the CONSEQUENCE without guessing the
                      cause: a reason the backend adds tomorrow must still
                      render as money the reader can act on. */}
                  {ITEM_LINES_RAZON_LABELS[breakdown.item_lines_razon] ||
                    'No se pudo calcular el monto de la operación a partir de los productos.'}
                </p>
              )}

              {breakdown.incompleto && (
                <div className={styles.incompleteBanner}>
                  <TriangleAlert size={16} aria-hidden="true" />
                  <div>
                    {reasons.length === 0 ? (
                      <p>Este desglose está incompleto.</p>
                    ) : (
                      reasons.map((reason) => <p key={reason}>{INCOMPLETE_REASON_LABELS[reason] || reason}</p>)
                    )}
                  </div>
                </div>
              )}

              <ul className={styles.lineList} aria-label="Cargos descontados">
                {lines.map((line, index) => {
                  // Index, not `concepto`: the backend sends lines as-is,
                  // unfiltered and unreordered, so two lines CAN share a
                  // concepto and a key on it would collide.
                  const deduction = formatDeduction(line.monto);
                  return (
                    <li key={`${index}-${line.concepto}`} className={styles.line}>
                      <span className={styles.lineSign}>{deduction.sign}</span>
                      <span className={styles.lineConcepto}>{line.concepto}</span>
                      <span className={`${styles.lineMonto} ${deduction.tone ? styles[`money_${deduction.tone}`] : ''}`}>
                        {deduction.text}
                      </span>
                    </li>
                  );
                })}
              </ul>

              {/* ml-ventas-neto-iibb-varios D6: recoverable lines (today:
                  SIRTAC) render AFTER the subtraction list, visibly muted,
                  never counted in it -- see the `lines`/`recuperables` split
                  above. */}
              {recuperables.length > 0 && (
                <ul className={styles.lineList} aria-label="Recuperable">
                  {recuperables.map((line, index) => (
                    <li key={`${index}-${line.concepto}`} className={`${styles.line} ${styles.recuperableLine}`}>
                      <span className={styles.lineSign} aria-hidden="true">
                        ·
                      </span>
                      <span className={styles.lineConcepto}>
                        {line.concepto}
                        <span className={styles.mutedNote}> · se recupera a fin de mes (no se descuenta)</span>
                      </span>
                      <span className={styles.lineMonto}>{formatSignedMoney(line.monto)}</span>
                    </li>
                  ))}
                </ul>
              )}

              <div className={`${styles.total} ${breakdown.incompleto ? styles.totalIncomplete : ''}`}>
                <span className={styles.totalLabel}>Neto</span>
                <span className={`${styles.totalMonto} ${styles.money_headline}`}>
                  {formatSignedMoney(breakdown.neto)}
                </span>
              </div>
              {/* ml-ventas-neto-iibb-varios R4/PR1.T10.c: explains why Neto is
                  higher than what ML actually deposited -- only when there is
                  a non-refunded SIRTAC to explain. */}
              {breakdown.retenciones_recuperables > 0 && (
                <p className={styles.netoSubLine}>
                  {`MP ${formatMoney(breakdown.neto_depositado)} · SIRTAC ${formatMoney(
                    breakdown.retenciones_recuperables,
                  )}`}
                </p>
              )}

              {/* ml-ventas-modo-logistico PR6 — IVA por alícuota, an inset
                  under Neto. Absent entirely when the backend did not send it. */}
              {ivaDecomposicion && (
                <section className={styles.inset} aria-label="IVA por alícuota">
                  <h4 className={styles.insetTitle}>
                    <ReceiptText size={14} aria-hidden="true" />
                    IVA por alícuota
                  </h4>
                  {ivaDecomposicion.reconcilia ? (
                    <ul className={styles.insetList}>
                      {componentesIva.map((componente, index) => (
                        // Same index-keyed reasoning as `lines` above.
                        <li
                          key={`${index}-${componente.concepto}`}
                          className={`${styles.insetLine} ${componente.informativo ? styles.recuperableLine : ''}`}
                        >
                          <span className={styles.lineConcepto}>
                            {componente.concepto}
                            {componente.informativo && <span className={styles.mutedNote}> (informativo)</span>}
                            {(!componente.informativo || componente.alicuota !== null) && (
                              <span className={styles.ivaAlicuota}> ({formatAlicuota(componente.alicuota)})</span>
                            )}
                          </span>
                          {/* An informativo componente WITHOUT a rate (SIRTAC)
                              shows no base/IVA split -- it carries no rate and
                              does not count in `neto_sin_iva`. One WITH a rate
                              (the Flex bonificación) does show it: the split is
                              the point, the amount just is not in the sum. */}
                          {(!componente.informativo || componente.alicuota !== null) && (
                            <span className={styles.lineMonto}>
                              base {formatAmount(componente.base)} · IVA {formatAmount(componente.iva)}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    // Never a bare number when it does not reconcile — the
                    // NAMED reason, exactly as `iva.py` produced it.
                    <div className={styles.reasonBox}>
                      {razonesIva.length === 0 ? (
                        <p>Este desglose de IVA no reconcilia.</p>
                      ) : (
                        razonesIva.map((razon) => <p key={razon}>{RAZON_LABELS[razon] || razon}</p>)
                      )}
                    </div>
                  )}
                </section>
              )}
            </section>

            {/* ml-ventas-modo-logistico PR6 — the Total Gauss chain: neto sin
                IVA -> costo de mercadería -> envío Flex -> % de varios ->
                Total Gauss. A `null` link renders "—" and is named below the
                chain; Total Gauss itself is only ever shown when every link
                resolved -- never a zero. */}
            {cadenaTotalGauss && (
              <section className={styles.card} aria-label="Total Gauss">
                <div className={styles.cardTitleRow}>
                  <h3 className={styles.cardTitle}>Total Gauss</h3>
                  {/* total-gauss-provisorio: a REAL computed number, just
                      flagged -- never rendered as if it were unknown. */}
                  {cadenaTotalGauss.total_gauss !== null && cadenaTotalGauss.provisional && (
                    <span className={styles.provisionalBadge}>Provisorio</span>
                  )}
                </div>
                <ul className={styles.lineList}>
                  <li className={styles.line}>
                    <span className={styles.lineSign}>(+)</span>
                    <span className={styles.lineConcepto}>Neto sin IVA</span>
                    <span className={styles.lineMonto}>{formatSignedMoney(ivaDecomposicion?.neto_sin_iva)}</span>
                  </li>
                  {lineasGauss.map((linea) => {
                    // A Gauss deduction is always SUBTRACTED from the chain
                    // (`deducciones.py`: `total = total - monto`).
                    const deduction = formatDeduction(linea.monto);
                    return (
                      <li key={linea.code} className={styles.line}>
                        <span className={styles.lineSign}>{deduction.sign}</span>
                        {/* `concepto` carries the per-order label (today: the
                            logistics company name on `envio_flex`) when the
                            backend has one -- falls back to the static map. */}
                        <span className={styles.lineConcepto}>
                          {linea.concepto || DEDUCCION_LABELS[linea.code] || linea.code}
                          {/* ventas-ml-rediseno PR19 (BREAKDOWN R38): a SPLIT of
                              the shared shipment, never this order's own
                              exclusive shipping cost. */}
                          {linea.code === 'envio_flex' && linea.prorateado && (
                            <span className={styles.mutedNote}> (prorrateado entre las órdenes del envío)</span>
                          )}
                          {/* ventas-ml-bonificacion-envio-flex: gross, net and
                              IVA as SEPARATE figures (the same data can feed an
                              IVA book later). Only the NET is in the amount at
                              the right; the IVA is informational. */}
                          {linea.importe && (
                            <span className={styles.mutedNote}>
                              {' '}
                              (Bruto {formatMoney(linea.importe.bruto)} · Neto {formatMoney(linea.importe.neto)} · IVA{' '}
                              {formatMoney(linea.importe.iva)} — el IVA no suma al Total Gauss)
                            </span>
                          )}
                        </span>
                        <span
                          className={`${styles.lineMonto} ${deduction.tone ? styles[`money_${deduction.tone}`] : ''}`}
                        >
                          {linea.monto === null ? '—' : deduction.text}
                        </span>
                      </li>
                    );
                  })}
                </ul>

                {/* Per-item arithmetic behind "Costo de mercadería" --
                    product-owner request: "debería decir después de costo
                    (precio USD + TC) de cada operación para saber cómo
                    replicar ese valor". Always shown when the backend sent
                    items. */}
                {costoItems.length > 0 && (
                  <ul className={styles.itemLineList} aria-label="Detalle de costo de mercadería">
                    {costoItems.map((item, index) => (
                      // STACKED, not side by side: an ML title runs to ~100
                      // characters and the arithmetic beside it cannot shrink.
                      <li key={`${index}-${item.item_id}-${item.variation_id ?? ''}`} className={styles.costoItemLine}>
                        <span className={styles.itemLineTitle}>
                          {item.title || item.item_id}
                          {item.quantity && item.quantity > 1 ? ` (x${item.quantity})` : ''}
                          {item.fuente && (
                            <span className={styles.itemLineFuente}>
                              {' '}
                              · {FUENTE_LABELS[item.fuente] || item.fuente}
                              {item.costo_fecha ? ` (${formatCostoFecha(item.costo_fecha)})` : ''}
                            </span>
                          )}
                        </span>
                        <span className={styles.itemLineMonto}>
                          {/* `costo_unitario_ars` is the UNIT cost; the
                              quantity is spelled out so the arithmetic can be
                              replicated, which is why this panel exists. */}
                          {!item.conocido ? (
                            'Costo desconocido'
                          ) : (
                            <>
                              {item.moneda === 'USD'
                                ? `USD ${formatAmount(item.costo_origen)} × ${formatAmount(item.tipo_cambio)}${
                                    item.tipo_cambio_fecha ? ` (${formatCostoFecha(item.tipo_cambio_fecha)})` : ''
                                  } = ${formatMoney(item.costo_unitario_ars)}`
                                : formatMoney(item.costo_unitario_ars)}
                              {item.quantity > 1
                                ? ` c/u × ${item.quantity} = ${formatMoney(Number(item.costo_unitario_ars) * item.quantity)}`
                                : ''}
                            </>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}

                {cadenaTotalGauss.total_gauss === null ? (
                  <div>
                    <div className={`${styles.total} ${styles.totalIncomplete}`}>
                      <span className={styles.totalLabel}>Total Gauss</span>
                      <span className={styles.totalMonto}>—</span>
                    </div>
                    {/* Names EXACTLY which link is missing, never a bare
                        "unknown". */}
                    <p className={styles.stateText}>
                      {(() => {
                        const unresolved = lineasGauss.find((linea) => linea.monto === null);
                        if (unresolved) {
                          return `Sin ${(DEDUCCION_LABELS[unresolved.code] || unresolved.code).toLowerCase()} conocido.`;
                        }
                        if (ivaDecomposicion && !ivaDecomposicion.reconcilia) {
                          return 'El neto sin IVA no reconcilia — ver la razón arriba.';
                        }
                        return 'Total Gauss desconocido.';
                      })()}
                    </p>
                  </div>
                ) : (
                  <div>
                    <div className={styles.total}>
                      <span className={styles.totalLabel}>Total Gauss</span>
                      <span
                        className={`${styles.totalMonto} ${
                          gaussTone === 'negative' ? styles.money_negative : gaussTone === 'positive' ? styles.money_positive : ''
                        }`}
                      >
                        {formatSignedMoney(cadenaTotalGauss.total_gauss)}
                      </span>
                    </div>
                    {cadenaTotalGauss.provisional && (
                      <p className={styles.provisionalNote}>
                        Calculado sin {(cadenaTotalGauss.provisional_falta || 'Envío Flex').toLowerCase()}: todavía
                        no se cargó la etiqueta de envío. Se va a actualizar solo cuando se cargue.
                      </p>
                    )}
                  </div>
                )}

                {/* The sale's REAL markup -- total_gauss / costo de
                    mercadería -- coloured by the same thresholds as the
                    listing (`markupTone`). `null` (never "0%") whenever it is
                    undefined -- see `TotalGaussResultado.markup`. */}
                <div className={styles.markupRow}>
                  <span className={styles.totalLabel}>Markup</span>
                  <span
                    className={`${styles.markupChip} ${
                      markupTone(cadenaTotalGauss.markup) ? styles[`markup_${markupTone(cadenaTotalGauss.markup)}`] : ''
                    }`}
                  >
                    {cadenaTotalGauss.markup === null || cadenaTotalGauss.markup === undefined
                      ? '—'
                      : `${formatAmount(cadenaTotalGauss.markup)}%`}
                  </span>
                </div>
              </section>
            )}
          </>
        )}
      </div>

      {(canResync || syncedAgo) && (
        <div className={styles.footer}>
          {syncedAgo && (
            <span className={styles.syncedAt}>
              <span className={styles.syncedDot} aria-hidden="true" />
              Sincronizado {syncedAgo}
            </span>
          )}
          {resyncDone && !resyncError && <span className={styles.resyncDone}>Venta resincronizada</span>}
          {resyncError && (
            <span className={styles.resyncError} role="alert">
              {resyncError}
            </span>
          )}
          {canResync && (
            <button type="button" className={styles.resyncButton} onClick={handleResync} disabled={resyncing}>
              <RefreshCw size={14} aria-hidden="true" />
              {resyncing ? 'Resincronizando...' : 'Resincronizar'}
            </button>
          )}
        </div>
      )}
    </>
  );
}
