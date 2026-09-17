/**
 * DesgloseDrawer — a MODAL anchored to the right with a sale's cost
 * breakdown (ml-ventas-desglose-costos, corte 6, frontend).
 *
 * This is a modal, not a panel: `.overlay` covers and blocks the whole
 * screen (see `DesgloseDrawer.module.css`), so the table behind it is NOT
 * operable — not by mouse, not by keyboard, not by a screen reader — while
 * this is open. `aria-modal="true"`, the focus trap, and the restored
 * focus on close all say the same thing the CSS already does. The real
 * flow is open, read, close; the operator never needs the table while the
 * breakdown is up, so a true non-blocking panel would be a bigger design
 * change for no clear benefit.
 *
 * Picking a different row while the modal is open updates `orderId` and
 * re-fetches WITHOUT closing it — see `VentasML.jsx`'s `openDrawer`, which
 * only ever changes `drawerOrderId`.
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
import { X, TriangleAlert } from 'lucide-react';
import api from '../services/api';
import styles from './DesgloseDrawer.module.css';

const FOCUSABLE_SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

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

export default function DesgloseDrawer({ orderId, open, onClose }) {
  const [breakdown, setBreakdown] = useState(null);
  // ml-ventas-modo-logistico PR6: the IVA split and the Total Gauss chain,
  // both from the SAME detail response. Kept separate from `breakdown`
  // (the older `origen: api/propio` lines) since they are two different
  // views of the sale, not one replacing the other.
  const [ivaDecomposicion, setIvaDecomposicion] = useState(null);
  const [cadenaTotalGauss, setCadenaTotalGauss] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorKind, setErrorKind] = useState(null); // 'generic' | null

  const dialogRef = useRef(null);

  // The backdrop blocks clicks but not the wheel: without this the table
  // scrolls behind an open modal, and the docblock's claim that the
  // background is not operable stops being true.
  useEffect(() => {
    if (!open) return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);
  const closeButtonRef = useRef(null);
  // The element that had focus before this modal opened -- e.g. the
  // "Neto" button the operator tabbed to. Closing returns focus there
  // instead of dropping it at the top of the document.
  const previouslyFocusedRef = useRef(null);

  // Same sequence guard `VentasML.jsx` uses for its list fetch: clicking
  // row A then row B fast can land A's response last. Without this, the
  // drawer would show A's money while its header still says B — worse
  // than showing nothing, since the operator reads it as B's number.
  const latestRequestRef = useRef(0);

  const loadBreakdown = useCallback(async () => {
    if (!open || orderId === null || orderId === undefined) return;
    const requestId = ++latestRequestRef.current;
    setLoading(true);
    setErrorKind(null);
    try {
      const { data } = await api.get(`/ml-ventas-ops/orders/${orderId}`);
      if (requestId !== latestRequestRef.current) return;
      setBreakdown(data.breakdown || null);
      setIvaDecomposicion(data.iva_decomposicion || null);
      setCadenaTotalGauss(data.cadena_total_gauss || null);
    } catch {
      if (requestId !== latestRequestRef.current) return;
      setErrorKind('generic');
      setBreakdown(null);
      setIvaDecomposicion(null);
      setCadenaTotalGauss(null);
    } finally {
      if (requestId === latestRequestRef.current) setLoading(false);
    }
  }, [open, orderId]);

  useEffect(() => {
    loadBreakdown();
  }, [loadBreakdown]);

  // Focus management for a real modal: remember what had focus, move focus
  // into the dialog on open, and give it back on close -- same shape as
  // `CalcularWebModal`'s trap, adapted to refs instead of querySelector.
  useEffect(() => {
    if (!open) return undefined;
    previouslyFocusedRef.current = document.activeElement;
    const focusTarget = closeButtonRef.current || dialogRef.current;
    focusTarget?.focus();
    return () => {
      // `isConnected` matters: on unmount (navigating away with the
      // modal open) the opener can already be gone, and focusing a
      // detached node silently drops focus on <body> instead.
      const toRestore = previouslyFocusedRef.current;
      if (toRestore && toRestore.isConnected && typeof toRestore.focus === 'function') {
        toRestore.focus();
      }
    };
  }, [open]);

  // Escape closes the modal; Tab/Shift+Tab cycle inside it ONCE FOCUS IS
  // THERE, which it is on open. This wraps at the first and last focusable
  // element rather than policing where focus came from -- what keeps it
  // from wandering back to the table is the overlay blocking clicks on the
  // background, not this handler.
  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key !== 'Tab' || !dialogRef.current) return;
      const focusable = dialogRef.current.querySelectorAll(FOCUSABLE_SELECTOR);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  // Defensive on purpose, same as the listing does with `group.orders`:
  // a malformed payload must not white-screen the drawer. `incompleto`
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
  const lines = (breakdown?.lines || []).filter((line) => line.origen !== 'propio');

  // Same defensive discipline: an absent/`null` `iva_decomposicion` (a
  // stale client, or an old-shaped test fixture) must not white-screen the
  // drawer — the new sections simply do not render.
  const componentesIva = ivaDecomposicion?.componentes || [];
  const razonesIva = ivaDecomposicion?.razones || [];
  const lineasGauss = cadenaTotalGauss?.lineas || [];
  const itemLines = breakdown?.item_lines || [];
  const costoItems = cadenaTotalGauss?.costo_mercaderia_items || [];

  if (!open) return null;

  return (
    <div className={styles.overlay} data-testid="drawer-overlay" onClick={onClose}>
      <aside
        ref={dialogRef}
        className={styles.drawer}
        role="dialog"
        aria-modal="true"
        aria-label="Desglose de costos de la venta"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          <h2 className={styles.title}>Desglose de costos</h2>
          <button
            ref={closeButtonRef}
            type="button"
            className={styles.closeButton}
            onClick={onClose}
            aria-label="Cerrar"
          >
            <X size={18} />
          </button>
        </div>

        <div className={styles.body}>
          {loading && <p className={styles.stateText}>Cargando desglose…</p>}

          {!loading && errorKind === 'generic' && (
            <p className={styles.stateText}>Error al cargar el desglose.</p>
          )}

          {/* A response that carries no `breakdown` is neither an error nor
              a zero, and without this the panel rendered blank: no loader,
              no error, no lines. Blank reads as "this sale left nothing",
              which is a number we never received. Say what happened. */}
          {!loading && !errorKind && !breakdown && (
            <p className={styles.stateText}>Esta venta todavía no tiene desglose disponible.</p>
          )}

          {!loading && !errorKind && breakdown && (
            <>
              {/* The starting figure every line below is taken off. `null`
                  (never `0`, see `formatAmount`) when some member order's
                  `paid_amount` has not synced -- reads as "unknown", not
                  as a sale worth nothing. */}
              <div className={styles.total}>
                <span className={styles.totalLabel}>Monto de la operación</span>
                <span className={styles.totalMonto}>{formatAmount(breakdown.monto_operacion)}</span>
              </div>

              {/* Per-item breakdown of the figure above -- product-owner
                  request: "debería ser la suma de los productos y no están
                  desglosados". Compact/muted on purpose: this is supporting
                  context for the total above it, not a primary figure of
                  its own -- see `.itemLineList` in the CSS module. Rendered
                  only when the backend sent at least one line; a reconcile
                  failure keeps the lines visible (a real partial list) but
                  swaps the reassurance for the named reason instead of
                  hiding the list outright. */}
              {itemLines.length > 0 && (
                <ul className={styles.itemLineList} aria-label="Detalle de productos">
                  {itemLines.map((item, index) => (
                    <li
                      key={`${index}-${item.item_id}-${item.variation_id ?? ''}`}
                      className={styles.itemLine}
                    >
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
                  {/* The fallback names the CONSEQUENCE without guessing
                      the cause: a reason the backend adds tomorrow must
                      still render as money the reader can act on, and
                      "puede no sumar el monto" describes something that
                      cannot happen any more -- the heading IS the lines'
                      own sum. */}
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
                      reasons.map((reason) => (
                        <p key={reason}>{INCOMPLETE_REASON_LABELS[reason] || reason}</p>
                      ))
                    )}
                  </div>
                </div>
              )}

              <ul className={styles.lineList}>
                {lines.map((line, index) => (
                  // Index, not `concepto`: the backend sends lines as-is,
                  // unfiltered and unreordered, so two lines CAN share a
                  // concepto and a key on it would collide.
                  <li key={`${index}-${line.concepto}`} className={styles.line}>
                    <span className={styles.lineConcepto}>{line.concepto}</span>
                    <span className={styles.lineMonto}>{formatAmount(line.monto)}</span>
                  </li>
                ))}
              </ul>

              <div className={`${styles.total} ${breakdown.incompleto ? styles.totalIncomplete : ''}`}>
                <span className={styles.totalLabel}>Neto</span>
                <span className={styles.totalMonto}>{formatAmount(breakdown.neto)}</span>
              </div>

              {/* ml-ventas-modo-logistico PR6 — IVA por alícuota. Absent
                  entirely when the backend did not send it (defensive: an
                  older cached response, a malformed payload). */}
              {ivaDecomposicion && (
                <section className={styles.section} aria-label="IVA por alícuota">
                  <h3 className={styles.sectionTitle}>IVA por alícuota</h3>
                  {ivaDecomposicion.reconcilia ? (
                    <ul className={styles.lineList}>
                      {componentesIva.map((componente, index) => (
                        // Same index-keyed reasoning as `lines` above: the
                        // backend can legitimately repeat a `concepto`.
                        <li key={`${index}-${componente.concepto}`} className={styles.line}>
                          <span className={styles.lineConcepto}>
                            {componente.concepto}
                            <span className={styles.ivaAlicuota}>
                              {' '}
                              ({formatAlicuota(componente.alicuota)})
                            </span>
                          </span>
                          <span className={styles.lineMonto}>
                            base {formatAmount(componente.base)} · IVA {formatAmount(componente.iva)}
                          </span>
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

              {/* ml-ventas-modo-logistico PR6 — the Total Gauss chain:
                  neto sin IVA -> costo de mercadería -> envío Flex ->
                  % de varios -> Total Gauss. A `null` link renders "—" and
                  is named below the chain; Total Gauss itself is only
                  ever shown once every link resolved -- never a zero. */}
              {cadenaTotalGauss && (
                <section className={styles.section} aria-label="Total Gauss">
                  <h3 className={styles.sectionTitle}>Total Gauss</h3>
                  <ul className={styles.lineList}>
                    <li className={styles.line}>
                      <span className={styles.lineConcepto}>Neto sin IVA</span>
                      <span className={styles.lineMonto}>{formatAmount(ivaDecomposicion?.neto_sin_iva)}</span>
                    </li>
                    {lineasGauss.map((linea) => (
                      <li key={linea.code} className={styles.line}>
                        {/* `concepto` carries the per-order label (today:
                            the logistics company name on `envio_flex`) when
                            the backend has one -- falls back to the static
                            map only when it does not. */}
                        <span className={styles.lineConcepto}>
                          {linea.concepto || DEDUCCION_LABELS[linea.code] || linea.code}
                        </span>
                        <span className={styles.lineMonto}>
                          {linea.monto === null ? '—' : formatAmount(linea.monto)}
                        </span>
                      </li>
                    ))}
                  </ul>

                  {/* Per-item arithmetic behind "Costo de mercadería" --
                      product-owner request: "debería decir después de costo
                      (precio USD + TC) de cada operación para saber cómo
                      replicar ese valor". Always shown when the backend sent
                      items, regardless of whether the aggregate line above
                      resolved -- an operator can still see which items DO
                      have a known cost. Compact/muted, same discipline as
                      the product list above: this explains the line above
                      it, it is not a total of its own. */}
                  {costoItems.length > 0 && (
                    <ul className={styles.itemLineList} aria-label="Detalle de costo de mercadería">
                      {costoItems.map((item, index) => (
                        <li
                          key={`${index}-${item.item_id}-${item.variation_id ?? ''}`}
                          className={styles.itemLine}
                        >
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
                            {/* `costo_unitario_ars` is the UNIT cost, and
                                the products list above shows the LINE
                                total. Without the quantity spelled out
                                here, a reader comparing "$200 (2 u.)"
                                against "$50" cannot tell whether $50 is
                                per unit or for the line -- and the
                                deduction that uses this figure multiplies
                                by the quantity. The arithmetic is shown
                                whole so it can be replicated, which is why
                                this panel exists. */}
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
                                  ? ` c/u × ${item.quantity} = ${formatMoney(
                                      Number(item.costo_unitario_ars) * item.quantity,
                                    )}`
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
                          "unknown" -- the operator needs to know whether to
                          wait for a sync or accept there is no frozen cost. */}
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
                        <span className={styles.totalLabel}>
                          Total Gauss
                          {/* total-gauss-provisorio: a REAL computed number,
                              just flagged -- never rendered as if it were
                              unknown (the `—` branch above). */}
                          {cadenaTotalGauss.provisional && (
                            <span className={`badge badge-warning ${styles.provisionalBadge}`}>Provisorio</span>
                          )}
                        </span>
                        <span className={styles.totalMonto}>{formatAmount(cadenaTotalGauss.total_gauss)}</span>
                      </div>
                      {cadenaTotalGauss.provisional && (
                        <p className={styles.stateText}>
                          Calculado sin {(cadenaTotalGauss.provisional_falta || 'Envío Flex').toLowerCase()}: todavía
                          no se cargó la etiqueta de envío. Se va a actualizar solo cuando se cargue.
                        </p>
                      )}
                    </div>
                  )}

                  {/* The sale's REAL markup -- total_gauss / costo de
                      mercadería, not the theoretical (neto sin IVA / costo)
                      one -- because total_gauss already has Flex freight and
                      % de varios subtracted too. `null` (never "0%": the
                      same "unknown" dash `formatAmount` uses everywhere
                      else) whenever total_gauss, the cost, or the division
                      itself is undefined -- see `TotalGaussResultado.markup`
                      in `deducciones.py`. */}
                  <div className={styles.total}>
                    <span className={styles.totalLabel}>Markup</span>
                    <span className={styles.totalMonto}>
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
      </aside>
    </div>
  );
}
