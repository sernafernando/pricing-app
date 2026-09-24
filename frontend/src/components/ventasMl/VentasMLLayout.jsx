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
 * Escape clears the selection (R20), but only when nothing else already
 * claimed the key. This app's real modal, `ModalTesla`, closes on Escape
 * via its OWN `document.addEventListener('keydown', ...)` and never calls
 * `preventDefault()`, and none of its instances render `role="dialog"`
 * (M1 fix — the previous guard relied on both and never actually covered
 * `ModalTesla`). What `ModalTesla` DOES always render, regardless of which
 * consumer or props are in play, is its portal-rendered overlay element —
 * `.modal-overlay-tesla` — a class the component hardcodes on the outer
 * `<div>` its portal mounts to `document.body`, not something a caller's
 * `className` prop can rename or omit. Checking for it is therefore a
 * structural fact about ANY currently-open `ModalTesla`, not a convention
 * a future consumer could forget to opt into — unlike `defaultPrevented`
 * or `role="dialog"`, which depended on `ModalTesla` (or a future modal)
 * cooperating. `defaultPrevented` and `role="dialog"` stay as an extra
 * layer for callers/dialogs outside `ModalTesla`.
 *
 * There is no focus trap: unlike the deleted `DesgloseDrawer`, this
 * component never moves focus on open and never wraps Tab at the panel's
 * edges — reaching the panel or leaving it follows the page's normal tab
 * order, exactly like reaching any other sticky sidebar would. What IS
 * restored (L1) is focus on CLOSE: the element that had focus at the
 * moment the panel opened (the row's keyboard route — the "Ver desglose de
 * costos" button — or whatever else had focus) gets it back once the
 * panel unmounts, so a keyboard user is not thrown back to the top of the
 * page — but ONLY when focus was still inside the panel (or had already
 * fallen back to `document.body`) at the moment it closed (M2): if the
 * operator moved on to another row or a filter WHILE the panel was still
 * open, restoring focus to the original opener would yank it away from
 * whatever they are doing now.
 */

import { useEffect, useRef } from 'react';
import styles from './VentasMLLayout.module.css';

function isEditableElement(el) {
  if (!el) return false;
  const tag = el.tagName;
  // M3: a `<select>` is as editable as an `<input>`/`<textarea>` for this
  // purpose — Escape while one is open/focused belongs to it, not to this
  // layout's selection-clearing shortcut.
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

export default function VentasMLLayout({ selectedOrderId, onClear, panel, children }) {
  const hasSelection = selectedOrderId !== null && selectedOrderId !== undefined;
  const openerRef = useRef(null);
  const panelRef = useRef(null);
  // M2: whether focus is currently somewhere inside the panel (or has
  // fallen back to `document.body`, e.g. the operator closed via a button
  // that then got removed). Kept live via `focusin`/`focusout` WHILE the
  // panel is mounted, because by the time the closing effect below runs
  // the panel has already unmounted and `document.activeElement` has
  // already moved to `<body>` regardless of where it "was" — this ref is
  // the only way to know what it was right before that happened.
  const focusInsidePanelRef = useRef(true);

  useEffect(() => {
    if (!hasSelection) return undefined;
    const updateFocusInsidePanel = () => {
      const active = document.activeElement;
      focusInsidePanelRef.current =
        !active || active === document.body || Boolean(panelRef.current && panelRef.current.contains(active));
    };
    updateFocusInsidePanel();
    document.addEventListener('focusin', updateFocusInsidePanel);
    document.addEventListener('focusout', updateFocusInsidePanel);
    return () => {
      document.removeEventListener('focusin', updateFocusInsidePanel);
      document.removeEventListener('focusout', updateFocusInsidePanel);
    };
  }, [hasSelection]);

  // Captured once per open, not on every render: the moment `hasSelection`
  // flips to `true` is the only moment `document.activeElement` still
  // points at whatever triggered the open (L1).
  useEffect(() => {
    if (hasSelection) {
      openerRef.current = document.activeElement;
    } else if (
      openerRef.current &&
      document.body.contains(openerRef.current) &&
      focusInsidePanelRef.current
    ) {
      // M2: only steal focus back if the operator had not already moved
      // it elsewhere (another row, a filter, a different control) — doing
      // it unconditionally is disorienting when they moved on before
      // closing the panel.
      openerRef.current.focus();
      openerRef.current = null;
    }
  }, [hasSelection]);

  // Global listener, not a per-panel keydown handler bound to a focused
  // dialog: there is no focus trap moving focus into the panel on open, so
  // the operator's focus can be anywhere on the page (the table, a filter
  // chip) when they press Escape, same as `DesgloseDrawer`'s Escape
  // handling used a window listener for the same reason.
  useEffect(() => {
    if (!hasSelection) return undefined;
    const handleKeyDown = (e) => {
      if (e.key !== 'Escape') return;
      // L2: a modal above this layout already handled its own Escape and
      // called preventDefault — closing this panel too would be a second,
      // unrelated effect from one keypress.
      if (e.defaultPrevented) return;
      // M1: ANY currently-open `ModalTesla` renders this hardcoded overlay
      // element via its portal to `document.body`, regardless of which
      // consumer opened it or whether that consumer calls preventDefault —
      // see the module docstring. This is the structural check that
      // actually covers this app's real modal.
      if (document.querySelector('.modal-overlay-tesla')) return;
      const active = document.activeElement;
      // L2: Escape while typing, or while focus sits inside a dialog,
      // belongs to that input/dialog, not to this layout.
      if (isEditableElement(active)) return;
      if (active && active.closest && active.closest('[role="dialog"]')) return;
      onClear();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [hasSelection, onClear]);

  return (
    <div className={`${styles.grid} ${hasSelection ? styles.gridWithPanel : ''}`}>
      <div className={styles.main}>{children}</div>
      {/* PANEL R19/R20: mounted UNCONDITIONALLY, outside the conditional
          `<aside>`, and only its TEXT changes (L3) — a live region that is
          inserted already containing its announcement is generally not
          read by screen readers, only later changes to an already-mounted
          region are, so the very first selection (the one that matters
          most) would otherwise be silent. */}
      <div aria-live="polite" className={styles.srOnly}>
        {hasSelection ? `Mostrando el detalle de la venta ${selectedOrderId}` : ''}
      </div>
      {hasSelection && (
        <aside ref={panelRef} className={styles.panel} aria-label="Detalle de venta">
          {panel}
        </aside>
      )}
    </div>
  );
}
