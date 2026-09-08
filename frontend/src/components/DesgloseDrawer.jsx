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
 * them, in order — no client-side reordering, renaming, or filtering. The
 * backend is the single source of truth for the breakdown (see
 * `breakdown_service.py`); duplicating that judgment here would let the
 * two disagree.
 *
 * `incompleto` never renders a total that looks closed: the amount stays
 * visible (it can be a real partial number, not a placeholder) but
 * visually marked, with the reason spelled out for the operator instead of
 * ML's raw incomplete_reasons code.
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
  billing_not_swept:
    'Falta el barrido de facturación: los cargos que ML factura aparte, como el envío, todavía no se descontaron. El neto real es MENOR que el que ves acá.',
  shipment_costs_missing: 'Faltan los costos de envío de esta venta.',
};

function formatAmount(value) {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

export default function DesgloseDrawer({ orderId, open, onClose }) {
  const [breakdown, setBreakdown] = useState(null);
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
    } catch {
      if (requestId !== latestRequestRef.current) return;
      setErrorKind('generic');
      setBreakdown(null);
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
  const lines = breakdown?.lines || [];

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
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
