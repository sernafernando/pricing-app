/**
 * RowActionsCell — the reconcile table's `Acciones` column (PR-A of the
 * table redesign). Consolidates what used to be three separate inline
 * ternaries scattered across the `Coincidencias TN (IDs)` and `Despublicar`
 * columns (see `tiendaNubeReconcileHelpers.js` for the pure "what applies to
 * this row" decisions this component renders).
 *
 * Primary action is always a real, clickable `<button>` (never a disabled
 * placeholder). Banear renders as its own visible button right next to the
 * primary action (tn-categorias-descubribles fix, defect 2) — on a
 * FALTA_PUBLICAR/FALTA_VINCULAR row it IS the other half of the operator's
 * triage decision, not a secondary one, so it must not be hidden behind the
 * overflow menu. Genuinely secondary actions (Despublicar / Editar en TN)
 * live behind a 30px overflow trigger so the row stays compact — this is a
 * real WAI-ARIA menu (Enter/Space open, Escape closes and returns focus to
 * the trigger, arrow keys roam between items), not a mouse-only affordance.
 *
 * Despublicar keeps its exact pre-existing two-step behavior: choosing it
 * from the menu does NOT call the endpoint — it hands off to the SAME
 * `confirmingProductId`/`Confirmar`/`Cancelar` pair the row used to render
 * inline, still enforcing "only one row can be mid-confirm at a time" (that
 * invariant is owned by the caller, which passes a single shared
 * `confirmingProductId`).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ExternalLink, MoreVertical } from 'lucide-react';
import {
  resolvePrimaryAction,
  resolveSecondaryActions,
  resolveBanAction,
  resolveEditorAction,
} from '../../pages/tiendaNubeReconcileHelpers';
import styles from './RowActionsCell.module.css';

export default function RowActionsCell({
  row,
  canBanlist,
  canPublish,
  despublicarTargetProductId,
  onPublicar,
  onBanear,
  confirmingProductId,
  despublicando,
  onStartDespublicarConfirm,
  onCancelDespublicarConfirm,
  onConfirmDespublicar,
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const itemRefs = useRef([]);

  const primary = resolvePrimaryAction(row, canPublish);
  const banAction = resolveBanAction(row, canBanlist);
  const editorAction = resolveEditorAction(row);
  const secondaryActions = resolveSecondaryActions(row, {
    canPublish,
    despublicarTargetProductId,
  });

  const closeMenu = useCallback((returnFocus) => {
    setMenuOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!menuOpen) return undefined;
    itemRefs.current[0]?.focus();

    function handleOutsideClick(event) {
      if (menuRef.current && !menuRef.current.contains(event.target) && event.target !== triggerRef.current) {
        closeMenu(false);
      }
    }
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [menuOpen, closeMenu]);

  // Row went out of confirm state (e.g. cancelled/confirmed elsewhere) —
  // nothing else to do here; confirm UI is derived directly from props.
  const despublicarAction = secondaryActions.find((a) => a.id === 'despublicar');
  const isConfirmingThisRow =
    despublicarAction != null && confirmingProductId === despublicarAction.productId;

  function handleMenuItemClick(action) {
    closeMenu(true);
    if (action.id === 'despublicar') onStartDespublicarConfirm(action.productId);
  }

  function handleMenuKeyDown(event) {
    const items = itemRefs.current.filter(Boolean);
    const currentIndex = items.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      closeMenu(true);
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      const next = items[(currentIndex + 1) % items.length];
      next?.focus();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      const prev = items[(currentIndex - 1 + items.length) % items.length];
      prev?.focus();
    } else if (event.key === 'Home') {
      event.preventDefault();
      items[0]?.focus();
    } else if (event.key === 'End') {
      event.preventDefault();
      items[items.length - 1]?.focus();
    }
  }

  return (
    <div className={styles.actionsCell}>
      {isConfirmingThisRow ? (
        <span className={styles.confirmGroup}>
          <button
            type="button"
            className="btn-tesla outline-subtle-danger sm"
            disabled={despublicando}
            onClick={() => onConfirmDespublicar(despublicarAction.productId)}
          >
            Confirmar
          </button>
          <button
            type="button"
            className={`btn-tesla ghost sm ${styles.spaced}`}
            disabled={despublicando}
            onClick={onCancelDespublicarConfirm}
          >
            Cancelar
          </button>
        </span>
      ) : (
        <>
          {primary && (
            <button
              type="button"
              className={`btn-tesla outline sm ${styles.primaryBtn}`}
              onClick={() => onPublicar(row)}
            >
              {primary.label}
            </button>
          )}
          {banAction && (
            <button
              type="button"
              className={`btn-tesla outline-subtle-danger sm ${styles.banBtn}`}
              onClick={() => onBanear(row.ean)}
            >
              {banAction.label}
            </button>
          )}
          {/*
            Promoted out of the overflow menu: opening the product in
            Tienda Nube is the first move on any mis-published row, and it
            was hidden behind a three-dot trigger. Same target, same lack
            of permission gating — only reachable in one click now.
          */}
          {editorAction && (
            <a
              href={editorAction.href}
              target="_blank"
              rel="noopener noreferrer"
              className={`btn-tesla ghost sm ${styles.editorBtn}`}
              aria-label={`Editar en TN el producto ${editorAction.productId}`}
            >
              {editorAction.label} <ExternalLink size={12} aria-hidden="true" />
            </a>
          )}
          {secondaryActions.length > 0 && (
            <div className={styles.overflowWrap}>
              <button
                type="button"
                ref={triggerRef}
                className={`btn-tesla ghost sm ${styles.overflowTrigger}`}
                aria-label={`Más acciones para ${row.ean}`}
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((v) => !v)}
              >
                <MoreVertical size={16} aria-hidden="true" />
              </button>
              {menuOpen && (
                <div
                  className={styles.menu}
                  role="menu"
                  aria-label={`Acciones para ${row.ean}`}
                  ref={menuRef}
                  onKeyDown={handleMenuKeyDown}
                >
                  {/* Every secondary action is a button now — the
                      link-shaped `editar_tn` branch that used to live here
                      moved out to a visible action. */}
                  {secondaryActions.map((action, idx) => (
                      <button
                        key={action.id}
                        type="button"
                        role="menuitem"
                        tabIndex={-1}
                        ref={(el) => (itemRefs.current[idx] = el)}
                        className={styles.menuItem}
                        onClick={() => handleMenuItemClick(action)}
                      >
                        {action.label}
                      </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {/* `editorAction` counts here too: rendering the link AND a "—"
              that means "nothing to do" states two contradictory things in
              the same cell. */}
          {!primary && !banAction && !editorAction && secondaryActions.length === 0 && (
            <span className={styles.noActions}>—</span>
          )}
        </>
      )}
    </div>
  );
}
