/**
 * SplitPanelLayout — a list on the left and a NON-modal detail panel on the
 * right that ALWAYS shrinks the list (publicaciones-ml-vista P10b, design 8.2).
 *
 * Why this is not `VentasMLLayout`: that one turns the panel into a fixed
 * sheet over the table below 1600px, which on a 1366px laptop hides the very
 * row the operator is reading. Here the panel is a grid column at EVERY
 * width -- there is no media query -- so opening it narrows the table and
 * never covers it. The table is expected to cope (see `TableShell`, which
 * scrolls horizontally inside its own bounded scroller).
 *
 * Contract:
 *  - `open` decides whether the `<aside>` exists; nothing is animated or
 *    portalled, and there is no overlay/backdrop element.
 *  - Never `aria-modal`, never `role="dialog"`, never a focus trap and never
 *    moves focus on open.
 *  - Escape calls `onClose`, unless something else already owns the key: a
 *    handler that called `preventDefault`, an open `ModalTesla` (its portal
 *    always renders `.modal-overlay-tesla`), an editable control, or focus
 *    inside a `role="dialog"`.
 *  - On close the opener gets focus back, but only when focus was still inside
 *    the panel (or had fallen to `<body>`): if the operator moved on to
 *    another row meanwhile, yanking focus back would be hostile.
 */
import { useEffect, useRef } from 'react';
import styles from './SplitPanelLayout.module.css';

const WIDTHS = ['md', 'lg'];

function isEditableElement(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

/**
 * @param {object} props
 * @param {boolean} props.open Whether the panel is shown.
 * @param {import('react').ReactNode} props.panel Panel content.
 * @param {() => void} props.onClose Called on Escape.
 * @param {'md'|'lg'} [props.width='md'] 460px / 560px (capped at 42vw).
 * @param {string} [props.ariaLabel] Accessible name of the panel.
 * @param {import('react').ReactNode} props.children The list.
 */
export default function SplitPanelLayout({ open, panel, onClose, width = 'md', ariaLabel, children }) {
  const size = WIDTHS.includes(width) ? width : 'md';
  const openerRef = useRef(null);
  const panelRef = useRef(null);
  // Whether focus is in the panel or on <body>. Tracked live because by the
  // time the closing effect runs the panel is already unmounted and
  // `document.activeElement` is `<body>` no matter where focus was.
  const focusInsidePanelRef = useRef(true);

  useEffect(() => {
    if (!open) return undefined;
    const update = () => {
      const active = document.activeElement;
      focusInsidePanelRef.current =
        !active || active === document.body || Boolean(panelRef.current?.contains(active));
    };
    update();
    document.addEventListener('focusin', update);
    document.addEventListener('focusout', update);
    return () => {
      document.removeEventListener('focusin', update);
      document.removeEventListener('focusout', update);
    };
  }, [open]);

  useEffect(() => {
    if (open) {
      openerRef.current = document.activeElement;
    } else if (openerRef.current && document.body.contains(openerRef.current) && focusInsidePanelRef.current) {
      openerRef.current.focus();
      openerRef.current = null;
    }
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (e) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      if (document.querySelector('.modal-overlay-tesla')) return;
      const active = document.activeElement;
      if (isEditableElement(active)) return;
      if (active?.closest?.('[role="dialog"]')) return;
      onClose?.();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  return (
    <div className={`${styles.grid} ${open ? styles.open : ''}`} data-width={size} data-split-open={open || undefined}>
      <div className={styles.main}>{children}</div>
      {open && (
        <aside ref={panelRef} className={styles.panel} aria-label={ariaLabel} data-split-panel>
          {panel}
        </aside>
      )}
    </div>
  );
}
