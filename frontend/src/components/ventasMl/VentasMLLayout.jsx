/**
 * VentasMLLayout — the FE layout shell replacing `DesgloseDrawer`'s modal
 * (ventas-ml-rediseno PR13, design D14, PANEL R16/R17/R18/R19/R20).
 *
 * The panel this hosts is a FIXED side panel next to the listing, never a
 * modal or a focus-trapped overlay (R16): the decision this whole PR13
 * exists to serve is that operators on wide monitors need to keep reading
 * and COPYING a table row's data while the detail panel is open, which a
 * blocking overlay made impossible. There is no `.overlay` element here —
 * see `VentasMLLayout.module.css` — and the `<aside>` never carries
 * `aria-modal` or `role="dialog"`.
 *
 * Selection state itself is NOT owned here — `useVentasMLFilters` (the
 * `orden` URL param) is the source of truth, same URL-state convention the
 * rest of this screen already uses. This component only reacts to
 * `selectedOrderId`: rendering the sticky/fixed `panel` when it is set,
 * and nothing when it is not (R18 — deselecting closes the panel with no
 * extra "no order" empty state to build or maintain).
 *
 * Escape clears the selection (R20). There is no focus trap: unlike the
 * deleted `DesgloseDrawer`, this component never moves focus on open and
 * never wraps Tab at the panel's edges — reaching the panel or leaving it
 * follows the page's normal tab order, exactly like reaching any other
 * sticky sidebar would.
 */

import { useEffect } from 'react';
import styles from './VentasMLLayout.module.css';

export default function VentasMLLayout({ selectedOrderId, onClear, panel, children }) {
  const hasSelection = selectedOrderId !== null && selectedOrderId !== undefined;

  // Global listener, not a per-panel keydown handler bound to a focused
  // dialog: there is no focus trap moving focus into the panel on open, so
  // the operator's focus can be anywhere on the page (the table, a filter
  // chip) when they press Escape, same as `DesgloseDrawer`'s Escape
  // handling used a window listener for the same reason.
  useEffect(() => {
    if (!hasSelection) return undefined;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClear();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [hasSelection, onClear]);

  return (
    <div className={`${styles.grid} ${hasSelection ? styles.gridWithPanel : ''}`}>
      <div className={styles.main}>{children}</div>
      {hasSelection && (
        <aside className={styles.panel} aria-label="Detalle de venta">
          {/* PANEL R19/R20: screen readers are informed of panel content
              changes without a modal role — an `aria-live` region, not a
              focus move, announces which order the panel now shows. */}
          <div aria-live="polite" className={styles.srOnly}>
            {`Mostrando el detalle de la venta ${selectedOrderId}`}
          </div>
          {panel}
        </aside>
      )}
    </div>
  );
}
