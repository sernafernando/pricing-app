/**
 * Shared TanStack column-sizing engine for the ml-bot panel's four resizable
 * tables (Preguntas / Historial / Mensajes / Pendientes) — extracted in PR4
 * (ml-bot-panel-operador, design ADR-3) from four near-identical ~30-line
 * state blocks that used to live directly in `MLQuestions.jsx`.
 *
 * `columnSizing` initializes from localStorage; changes are debounced
 * (~200ms, since `onChange` resize mode fires per mouse-move during a drag)
 * before persisting. Behaviour-neutral extraction: these are the exact same
 * semantics as the four original blocks (#956, PR1-PR3), just parameterized
 * by `storageKey`.
 */
import { useCallback, useRef, useState } from 'react';

// The four localStorage keys are FROZEN, verbatim. Renaming any of these
// silently resets every operator's saved column widths on next load with no
// error — see the literal-key test in useColumnSizing.test.js.
export const COLUMN_SIZING_STORAGE_KEYS = {
  preguntas: 'mlq:colsizing:preguntas',
  historial: 'mlq:colsizing:historial',
  mensajes: 'mlq:colsizing:mensajes',
  pendientes: 'mlq:colsizing:pendientes',
};

// Fail-safe persistence: absent/corrupt/disabled localStorage MUST never
// throw, and MUST fall back to `{}` so TanStack uses each column's default
// `size`. Unknown/stale column ids in the stored object are inert — TanStack
// only reads sizes for columns that currently exist.
export function loadColumnSizing(key = COLUMN_SIZING_STORAGE_KEYS.preguntas) {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export function saveColumnSizing(state, key = COLUMN_SIZING_STORAGE_KEYS.preguntas) {
  try {
    localStorage.setItem(key, JSON.stringify(state));
  } catch {
    // Disabled/private-mode localStorage: resizing still works in-memory,
    // it just won't persist across reload.
  }
}

/**
 * @param {string} storageKey one of COLUMN_SIZING_STORAGE_KEYS
 * @returns {{ columnSizing: object, onColumnSizingChange: Function, reset: Function, hasCustom: boolean }}
 */
export function useColumnSizing(storageKey) {
  const [columnSizing, setColumnSizingState] = useState(() => loadColumnSizing(storageKey));
  const saveTimerRef = useRef(null);

  const onColumnSizingChange = useCallback((updater) => {
    setColumnSizingState((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => saveColumnSizing(next, storageKey), 200);
      return next;
    });
  }, [storageKey]);

  const reset = useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    setColumnSizingState({});
    try {
      localStorage.removeItem(storageKey);
    } catch {
      // no-op — disabled/private-mode localStorage
    }
  }, [storageKey]);

  const hasCustom = Object.keys(columnSizing).length > 0;

  return { columnSizing, onColumnSizingChange, reset, hasCustom };
}
