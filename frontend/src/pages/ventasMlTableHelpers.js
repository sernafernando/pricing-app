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
// throw. A locked-visible column (Producto, Total Gauss) is never allowed
// to load as hidden even if a stale/corrupted/foreign payload says so --
// `LOCKED_VISIBLE_COLUMN_IDS` is TanStack's own `enableHiding: false`
// escape hatch's source of truth, so this stays in lockstep with it rather
// than re-deciding which columns are locked.
export function loadColumnVisibility(columns, lockedVisibleIds) {
  try {
    const parsed = JSON.parse(localStorage.getItem(COLUMN_VISIBILITY_STORAGE_KEY) || '{}');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const knownIds = new Set(columns.map((c) => c.id));
    const locked = new Set(lockedVisibleIds || []);
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
