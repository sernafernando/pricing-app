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
 *    minimum, except that the panel's default width always stays reachable,
 *    and the panel's minimum wins over the table's when both don't fit. The
 *    width is remembered in this browser under that key, and
 *    until someone resizes, the panel keeps its usual token width. Without
 *    the prop nothing changes: no handle, same columns.
 *  - `expanded` (Ver competencia) is a wider view with a width of its own:
 *    it starts at its token and the operator's drag there is remembered
 *    apart (`<resizeKey>:expanded`), so neither view moves the other.
 *  - On a phone (`useIsPhone`, <= 768px) there is no room beside the list:
 *    the panel takes the whole screen over it, with no divider, and the list
 *    keeps its scroll underneath for when the panel closes
 *    (mobile-metricas-pubml S2). Everything else above still holds.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import useIsPhone from '../../hooks/useIsPhone';
import styles from './SplitPanelLayout.module.css';

const WIDTHS = ['md', 'lg', 'xl'];

// Pixels. The minimums keep both sides readable: a panel narrower than 360
// no longer fits its tab strip and key/value rows, and a table narrower than
// 480 shows little more than its pinned first column. One arrow press moves
// the divider 16.
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
    // Any positive width: the CSS track bounds what is drawn, and the lower
    // bound can sit under PANEL_MIN_WIDTH where the default does.
    return Number.isFinite(width) && width > 0 ? width : null;
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
 * @param {'md'|'lg'|'xl'} [props.width='md'] 460px / 560px / 920px (capped at 42vw unless `expanded`).
 * @param {boolean} [props.expanded] Lifts the 42vw cap so `xl` (Ver competencia) can actually grow; its dragged width
 *   is remembered apart from the usual one.
 * @param {string} [props.ariaLabel] Accessible name of the panel.
 * @param {string} [props.resizeKey] Turns on resizing; the width is remembered per browser under this key.
 *   Read once on mount, so keep it constant for the life of the layout.
 * @param {import('react').ReactNode} props.children The list.
 */
export default function SplitPanelLayout({ open, panel, onClose, width = 'md', expanded = false, ariaLabel, resizeKey, children }) {
  const size = WIDTHS.includes(width) ? width : 'md';
  const phone = useIsPhone();
  const resizable = Boolean(resizeKey) && !phone;
  const gridRef = useRef(null);
  const handleRef = useRef(null);
  // `null` until the operator resizes: the panel keeps its token width. The
  // expanded view keeps its own, so dragging one never moves the other.
  const [usualWidth, setUsualWidth] = useState(() => loadWidth(resizeKey));
  const [expandedWidth, setExpandedWidth] = useState(() => loadWidth(resizeKey && `${resizeKey}:expanded`));
  const panelWidth = expanded ? expandedWidth : usualWidth;
  const setPanelWidth = expanded ? setExpandedWidth : setUsualWidth;
  const widthKey = expanded ? `${resizeKey}:expanded` : resizeKey;
  const [measured, setMeasured] = useState({ width: 0, min: PANEL_MIN_WIDTH, max: PANEL_MIN_WIDTH });
  // Cancels the drag in progress, if any: back to the width before it, nothing saved.
  const cancelDragRef = useRef(null);
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

  // The default width (token, capped at `--split-panel-cap`) always stays
  // reachable, even where it crowds the table under its minimum or is itself
  // under the panel's minimum: otherwise resizing would be one-way. The CSS
  // track has the same bounds, and both values are read from the stylesheet,
  // which owns them: the width token must be in px and the cap in vw, or the
  // bounds fall back to the two minimums alone.
  const defaultWidth = () => {
    if (!gridRef.current) return null;
    const style = getComputedStyle(gridRef.current);
    const token = style.getPropertyValue('--split-panel-width').trim();
    const cap = style.getPropertyValue('--split-panel-cap').trim();
    if (!/^[\d.]+px$/.test(token) || !/^[\d.]+vw$/.test(cap)) return null;
    // Not rounded: a floored default would let a step "move" a divider the CSS keeps still.
    return Math.min(Number.parseFloat(token), (window.innerWidth * Number.parseFloat(cap)) / 100);
  };

  const measure = () => {
    const grid = gridRef.current?.getBoundingClientRect().width ?? 0;
    const handle = handleRef.current?.getBoundingClientRect().width ?? 0;
    // `null` when the stylesheet values can't be trusted: the two minimums alone bound it.
    const defaultPanel = defaultWidth();
    return {
      width: panelRef.current?.getBoundingClientRect().width ?? 0,
      min: defaultPanel === null ? PANEL_MIN_WIDTH : Math.min(PANEL_MIN_WIDTH, defaultPanel),
      // Never wider than the grid itself, whatever the minimums say.
      max: Math.min(
        Math.max(PANEL_MIN_WIDTH, Math.floor(grid - handle - TABLE_MIN_WIDTH), defaultPanel ?? 0),
        Math.floor(grid - handle),
      ),
    };
  };

  useLayoutEffect(() => {
    if (!open || !resizable) return undefined;
    const update = () => setMeasured(measure());
    update();
    // The grid can change width without the window doing so (sidebar, scrollbar).
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
    observer?.observe(gridRef.current);
    window.addEventListener('resize', update);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', update);
      // Closing mid-drag cancels the drag: the release afterwards saves nothing.
      cancelDragRef.current?.();
    };
    // `measure` only reads refs: re-subscribing whenever it changes identity would add nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, resizable]);

  // Where a step or drag from `start` towards `target` lands: within the same
  // bounds the CSS clamp applies, so the saved width is the one on screen.
  // `null` when it would not move the divider the asked way, which happens
  // when the start sits outside the bounds: a grid narrower than the default
  // panel plus the handle, or bounds of the minimums alone because the
  // stylesheet values couldn't be read.
  const moveTo = (start, target, bounds) => {
    if (target === start) return null;
    const next = Math.min(Math.max(Math.round(target), bounds.min), bounds.max);
    // Under half a pixel is the browser snapping the measured width, not a move.
    if (Math.abs(next - start) < 0.5) return null;
    return (target > start ? next > start : next < start) ? next : null;
  };

  // Steps and drags start from the width on screen, which the CSS clamp may
  // have narrowed below a width saved on a wider window.
  const handleSeparatorKeyDown = (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    // Alt+arrow and the like belong to the browser (history, text navigation).
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    // During a drag the pointer decides; a cancelled drag must leave nothing saved.
    if (cancelDragRef.current) return;
    const box = measure();
    const next = moveTo(box.width, box.width + (e.key === 'ArrowLeft' ? RESIZE_STEP : -RESIZE_STEP), box);
    setMeasured(box);
    if (next === null) return;
    setPanelWidth(next);
    saveWidth(widthKey, next);
  };

  const handlePointerDown = (e) => {
    // One drag at a time: a second touch or pen while dragging starts nothing.
    if (e.button !== 0 || cancelDragRef.current) return;
    e.preventDefault();
    // preventDefault also blocks the focus a press gives, and the arrows need it.
    handleRef.current?.focus();
    const box = measure();
    const { pointerId } = e;
    const startX = e.clientX;
    const startWidth = box.width;
    const widthBefore = panelWidth;
    let latest = null;
    setMeasured(box);
    // On the window, not the handle: a fast drag leaves the thin handle behind.
    const move = (event) => {
      if (event.pointerId !== pointerId) return;
      // The button is already up: the release got lost (a context menu ate it). End the drag here.
      if (event.buttons === 0) {
        end(event);
        return;
      }
      latest = moveTo(startWidth, startWidth + startX - event.clientX, box);
      // Back where it started (or pushed the way it cannot go): as before the drag.
      setPanelWidth(latest ?? widthBefore);
    };
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', cancel);
      window.removeEventListener('blur', finish);
      cancelDragRef.current = null;
    };
    function finish() {
      stop();
      // A click without a drag is not a resize: the default width stays.
      if (latest !== null) saveWidth(widthKey, latest);
    }
    function end(event) {
      if (event.pointerId === pointerId) finish();
    }
    function cancel(event) {
      if (event && event.pointerId !== pointerId) return;
      stop();
      setPanelWidth(widthBefore);
    }
    cancelDragRef.current = cancel;
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', cancel);
    // Leaving the window can swallow the release: end the drag where it is.
    window.addEventListener('blur', finish);
  };

  const resized = resizable && panelWidth !== null;
  // A saved width is reported as the CSS draws it, clamped to both bounds.
  const valueNow =
    panelWidth === null ? measured.width : Math.min(Math.max(panelWidth, measured.min), measured.max);
  // The unresized width can sit outside the bounds (a grid narrower than the
  // default panel, or unread stylesheet values); the reported range still contains it.
  const valueMin = Math.min(measured.min, valueNow);
  const valueMax = Math.max(measured.max, valueNow);
  const gridStyle = resized
    ? {
        '--split-panel-chosen-width': `${panelWidth}px`,
        '--split-panel-min-width': `${PANEL_MIN_WIDTH}px`,
        '--split-table-min-width': `${TABLE_MIN_WIDTH}px`,
      }
    : undefined;

  return (
    <div
      ref={gridRef}
      className={`${styles.grid} ${open ? styles.open : ''}`}
      data-width={size}
      data-expanded={expanded || undefined}
      data-split-open={open || undefined}
      data-split-grid
      data-resizable={resizable || undefined}
      data-resized={resized || undefined}
      data-phone={phone || undefined}
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
          aria-valuemin={valueMin}
          aria-valuemax={valueMax}
          tabIndex={0}
          onKeyDown={handleSeparatorKeyDown}
          onPointerDown={handlePointerDown}
        />
      )}
      {open && (
        <aside ref={panelRef} className={styles.panel} aria-label={ariaLabel} data-split-panel data-phone={phone || undefined}>
          {panel}
        </aside>
      )}
    </div>
  );
}
