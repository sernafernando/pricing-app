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
 *  - With `resizeKey` the operator can drag the divider (or focus it and use
 *    the arrows) to trade table width for panel width. Both sides keep a
 *    minimum, the width is remembered in this browser under that key, and
 *    until someone resizes, the panel keeps its usual token width. Without
 *    the prop nothing changes: no handle, same columns.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import styles from './SplitPanelLayout.module.css';

const WIDTHS = ['md', 'lg'];

export const PANEL_MIN_WIDTH = 360;
export const TABLE_MIN_WIDTH = 480;
export const RESIZE_STEP = 16;

const storageKey = (key) => `split-panel-width:${key}`;

// Disabled or private-mode storage must never break the layout: resizing
// still works, it just isn't remembered.
function loadWidth(key) {
  if (!key) return null;
  try {
    const width = Number(localStorage.getItem(storageKey(key)));
    return Number.isFinite(width) && width >= PANEL_MIN_WIDTH ? width : null;
  } catch {
    return null;
  }
}

function saveWidth(key, width) {
  try {
    localStorage.setItem(storageKey(key), String(width));
  } catch {
    // Not remembered; the current width still applies.
  }
}

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
 * @param {string} [props.resizeKey] Turns on resizing; the width is remembered per browser under this key.
 * @param {import('react').ReactNode} props.children The list.
 */
export default function SplitPanelLayout({ open, panel, onClose, width = 'md', ariaLabel, resizeKey, children }) {
  const size = WIDTHS.includes(width) ? width : 'md';
  const resizable = Boolean(resizeKey);
  const gridRef = useRef(null);
  const handleRef = useRef(null);
  // `null` until the operator resizes: the panel keeps its token width.
  const [panelWidth, setPanelWidth] = useState(() => loadWidth(resizeKey));
  const [measured, setMeasured] = useState({ width: 0, max: PANEL_MIN_WIDTH });
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
        !active ||
        active === document.body ||
        Boolean(panelRef.current?.contains(active)) ||
        // The resize handle belongs to the panel: Escape from it returns focus too.
        active === handleRef.current;
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

  const measure = () => {
    const grid = gridRef.current?.getBoundingClientRect().width ?? 0;
    const handle = handleRef.current?.getBoundingClientRect().width ?? 0;
    return {
      width: panelRef.current?.getBoundingClientRect().width ?? 0,
      max: Math.max(PANEL_MIN_WIDTH, Math.floor(grid - handle - TABLE_MIN_WIDTH)),
    };
  };

  useLayoutEffect(() => {
    if (!open || !resizable) return undefined;
    const update = () => setMeasured(measure());
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, [open, resizable]);

  // The bounds a gesture moves within. They stretch to include where it
  // starts: on a narrow window the default width can sit outside them, and a
  // step must never jump the divider the opposite way.
  const boundsFrom = (start, max) => ({ min: Math.min(PANEL_MIN_WIDTH, start), max: Math.max(max, start) });
  const clampWidth = (value, bounds) => Math.min(Math.max(Math.round(value), bounds.min), bounds.max);

  // Steps and drags start from the width on screen, which the CSS clamp may
  // have narrowed below a width saved on a wider window.
  const handleSeparatorKeyDown = (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const box = measure();
    const step = e.key === 'ArrowLeft' ? RESIZE_STEP : -RESIZE_STEP;
    const next = clampWidth(box.width + step, boundsFrom(box.width, box.max));
    setMeasured(box);
    if (next === Math.round(box.width)) return;
    setPanelWidth(next);
    saveWidth(resizeKey, next);
  };

  const handlePointerDown = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const box = measure();
    const startX = e.clientX;
    const startWidth = box.width;
    const bounds = boundsFrom(startWidth, box.max);
    let latest = null;
    setMeasured(box);
    // On the window, not the handle: a fast drag leaves the thin handle behind.
    const move = (event) => {
      latest = clampWidth(startWidth + startX - event.clientX, bounds);
      setPanelWidth(latest);
    };
    const end = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
      // A click without a drag is not a resize: the default width stays.
      if (latest !== null) saveWidth(resizeKey, latest);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
  };

  const resized = resizable && panelWidth !== null;
  const valueNow = panelWidth === null ? measured.width : Math.min(panelWidth, measured.max);
  const valueBounds = boundsFrom(valueNow, measured.max);
  const gridStyle = resized
    ? {
        '--split-panel-drag-width': `${panelWidth}px`,
        '--split-panel-min-width': `${PANEL_MIN_WIDTH}px`,
        '--split-table-min-width': `${TABLE_MIN_WIDTH}px`,
      }
    : undefined;

  return (
    <div
      ref={gridRef}
      className={`${styles.grid} ${open ? styles.open : ''}`}
      data-width={size}
      data-split-open={open || undefined}
      data-split-grid
      data-resizable={resizable || undefined}
      data-resized={resized || undefined}
      style={gridStyle}
    >
      <div className={styles.main}>{children}</div>
      {open && resizable && (
        <div
          ref={handleRef}
          className={styles.handle}
          role="separator"
          aria-orientation="vertical"
          aria-label="Ancho del panel"
          aria-valuenow={valueNow}
          aria-valuemin={valueBounds.min}
          aria-valuemax={valueBounds.max}
          tabIndex={0}
          onKeyDown={handleSeparatorKeyDown}
          onPointerDown={handlePointerDown}
        />
      )}
      {open && (
        <aside ref={panelRef} className={styles.panel} aria-label={ariaLabel} data-split-panel>
          {panel}
        </aside>
      )}
    </div>
  );
}
