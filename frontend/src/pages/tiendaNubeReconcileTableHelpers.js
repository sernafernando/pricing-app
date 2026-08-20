/**
 * Pure table-state helpers extracted from `TiendaNubeReconcile.jsx` (column
 * sizing persistence + client-side stock sort) — kept out of the page file
 * for the same "pure export beside a default component export trips
 * react-refresh/only-export-components" reasoning as
 * `tiendaNubeReconcileHelpers.js`.
 */

export const COLUMN_SIZING_STORAGE_KEY = 'tnreconcile:colsizing:reporte';

// Fail-safe persistence — absent/corrupt/disabled localStorage MUST never
// throw (mirrors MLQuestions.jsx's loadColumnSizing/saveColumnSizing).
// Adding/removing a COLUMNS entry (like this PR's new `acciones` column)
// changes the stored-size shape: a stale saved entry may carry sizes for
// columns that no longer exist, or simply lack one for a brand-new column.
// TanStack tolerates extra unknown keys harmlessly and a missing key just
// falls back to that column's own default `size` — but we filter to KNOWN
// ids here anyway so a corrupted/foreign localStorage payload can never
// grow unbounded or leak an unrelated column's stale width into this table.
export function loadColumnSizing(columns) {
  try {
    const parsed = JSON.parse(localStorage.getItem(COLUMN_SIZING_STORAGE_KEY) || '{}');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const knownIds = new Set(columns.map((c) => c.id));
    return Object.fromEntries(Object.entries(parsed).filter(([id]) => knownIds.has(id)));
  } catch {
    return {};
  }
}

export function saveColumnSizing(state) {
  try {
    localStorage.setItem(COLUMN_SIZING_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Disabled/private-mode localStorage: resizing still works in-memory.
  }
}

// Slice 4: client-side sort over `currentTabItems`, BEFORE pagination —
// deliberately NOT wired onto TanStack's `getSortedRowModel` (the table
// instance is used only for column sizing/resize; the body renders manually
// from `COLUMNS`/`filasVisibles`, see the page module docstring's One-shot-
// fetch note and design.md Decision 3).
//
// Null/unknown-stock ordering is explicit and intentional, not an accident
// of the comparator: `stock === null` ALWAYS sorts last, in BOTH ascending
// and descending order. This is deliberately asymmetric — an operator
// sorting descending wants the highest stock first, and one sorting
// ascending wants the genuine lowest/zero-stock rows first; in both cases
// "unknown" is the least actionable row and belongs at the bottom, never
// mixed in as if it were a real value.
//
// Ties (equal stock, including two nulls) are broken by EAN for a stable,
// deterministic order across renders — never left to array-insertion order.
function compareByStock(a, b, direction) {
  const aNull = a.stock === null || a.stock === undefined;
  const bNull = b.stock === null || b.stock === undefined;
  if (aNull && bNull) return a.ean.localeCompare(b.ean);
  if (aNull) return 1; // nulls always last, regardless of direction
  if (bNull) return -1;
  if (a.stock !== b.stock) return direction === 'asc' ? a.stock - b.stock : b.stock - a.stock;
  return a.ean.localeCompare(b.ean);
}

export function sortItems(items, sortState) {
  if (!sortState || sortState.column !== 'stock') return items;
  // `.slice()` first — sorting must never mutate the source array in place
  // (it's the same `reporte` state array the rest of the component reads).
  return items.slice().sort((a, b) => compareByStock(a, b, sortState.direction));
}
