/**
 * Pure table-state helpers for the Ventas ML table (ventas-ml-columnas) --
 * column-visibility persistence, calqued on
 * `tiendaNubeReconcileTableHelpers.js`'s `loadColumnSizing`/
 * `saveColumnSizing` fail-safe discipline. Kept out of `VentasML.jsx` for
 * the same "pure export beside a default component export trips
 * react-refresh/only-export-components" reasoning that file documents.
 */

export const COLUMN_VISIBILITY_STORAGE_KEY = 'ventasml:colvisibility';

// Fail-safe persistence — absent/corrupt/disabled localStorage MUST never
// throw. A locked-visible column is never allowed
// to load as hidden even if a stale/corrupted/foreign payload says so --
// `LOCKED_VISIBLE_COLUMN_IDS` is TanStack's own `enableHiding: false`
// escape hatch's source of truth, so this stays in lockstep with it rather
// than re-deciding which columns are locked.
// The locked ids are DERIVED from `columns`, not received as a second
// argument. They used to be an exported `LOCKED_VISIBLE_COLUMN_IDS` constant
// computed inside `ventasMlColumns.jsx`, which tripped
// `react-refresh/only-export-components`: that rule tolerates a plain
// constant export beside the column list, but not a COMPUTED one. Deriving it
// here removes the export instead of relocating it — one less thing that can
// fall out of sync with `enableHiding`.
export function loadColumnVisibility(columns) {
  try {
    const parsed = JSON.parse(localStorage.getItem(COLUMN_VISIBILITY_STORAGE_KEY) || '{}');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const knownIds = new Set(columns.map((c) => c.id));
    const locked = new Set(columns.filter((c) => c.enableHiding === false).map((c) => c.id));
    return Object.fromEntries(
      Object.entries(parsed).filter(([id, value]) => knownIds.has(id) && typeof value === 'boolean' && !locked.has(id))
    );
  } catch {
    return {};
  }
}

export function saveColumnVisibility(state) {
  try {
    localStorage.setItem(COLUMN_VISIBILITY_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Disabled/private-mode localStorage: hiding a column still works
    // in-memory for the rest of the session.
  }
}

// Column WIDTHS are user-resizable and persisted with the same shared hook
// the ml-bot tables use (`components/ml-bot/useColumnSizing.js`); only the
// storage key is ours. Frozen: renaming it silently resets every operator.
export const COLUMN_SIZING_STORAGE_KEY = 'ventasml:colsizing';

/**
 * Moves the border on the right of `columnId` by `delta` pixels: that column
 * grows, its right neighbour shrinks by the same amount, so the total never
 * changes and no other column moves. Both are clamped to their minimum, which
 * is what keeps one column from being dragged over the next (the old overlap
 * bug). The last visible column has no right neighbour, so it is a no-op.
 *
 * @param {Record<string, number>} widths current width of every visible column
 * @param {string[]} order visible column ids, left to right
 * @param {string} columnId
 * @param {number} delta pixels, positive = widen
 * @param {Record<string, number>} mins minimum width per column id
 */
export function resizeColumns(widths, order, columnId, delta, mins) {
  const index = order.indexOf(columnId);
  const neighborId = index === -1 ? undefined : order[index + 1];
  if (neighborId === undefined) return widths;
  const lower = (mins[columnId] ?? 0) - widths[columnId];
  const upper = widths[neighborId] - (mins[neighborId] ?? 0);
  if (lower > upper) return widths;
  const applied = Math.min(Math.max(delta, lower), upper);
  return {
    ...widths,
    [columnId]: widths[columnId] + applied,
    [neighborId]: widths[neighborId] - applied,
  };
}

// Rows per page. The endpoint caps `limit` at 200 (`ml_ventas_ops.py`), so
// nothing above that is offered. Persisted like the column choices.
export const PAGE_SIZE_OPTIONS = [25, 50, 100, 200];
export const DEFAULT_PAGE_SIZE = 50;
export const PAGE_SIZE_STORAGE_KEY = 'ventasml:pagesize';

export function loadPageSize() {
  try {
    const value = Number(localStorage.getItem(PAGE_SIZE_STORAGE_KEY));
    return PAGE_SIZE_OPTIONS.includes(value) ? value : DEFAULT_PAGE_SIZE;
  } catch {
    return DEFAULT_PAGE_SIZE;
  }
}

export function savePageSize(size) {
  try {
    localStorage.setItem(PAGE_SIZE_STORAGE_KEY, String(size));
  } catch {
    // Disabled/private-mode localStorage: the choice lasts for the session.
  }
}

/**
 * Page numbers to render: first, last, the current page and its neighbours,
 * with a `gap-*` marker where pages are skipped (never for a single page —
 * a gap hiding one number is longer than the number).
 */
export function pageWindow(current, totalPages) {
  if (totalPages <= 1) return [1];
  const keep = new Set([1, totalPages, current - 1, current, current + 1]);
  const pages = [...keep].filter((p) => p >= 1 && p <= totalPages).sort((a, b) => a - b);
  const out = [];
  pages.forEach((page, i) => {
    const prev = pages[i - 1];
    if (prev !== undefined && page - prev === 2) out.push(prev + 1);
    else if (prev !== undefined && page - prev > 2) out.push(prev === 1 ? 'gap-start' : 'gap-end');
    out.push(page);
  });
  return out;
}
