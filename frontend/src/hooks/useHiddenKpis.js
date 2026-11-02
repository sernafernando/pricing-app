import { useCallback, useMemo, useState } from 'react';

// Reads the stored list of hidden KPI ids; anything that is not an array of strings means "nothing hidden".
function readHidden(storageKey) {
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey));
    return Array.isArray(stored) && stored.every((id) => typeof id === 'string') ? stored : [];
  } catch {
    return [];
  }
}

/**
 * Which KPI cards a page shows, kept per page and per browser under `storageKey` (every card visible by
 * default). `options` (`[{ id, label }]`) are the KPIs the viewer can see right now; `pickerTable` is the
 * TanStack-shaped object the kit's `ColumnPicker` lists them from. A hidden id the page does not offer
 * right now stays hidden for when it comes back.
 */
export default function useHiddenKpis(storageKey, options) {
  const [hidden, setHidden] = useState(() => readHidden(storageKey));

  const toggle = useCallback(
    (id) => {
      const next = hidden.includes(id) ? hidden.filter((hiddenId) => hiddenId !== id) : [...hidden, id];
      setHidden(next);
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        // Storage unavailable (private mode, quota): the choice lasts until the reload.
      }
    },
    [hidden, storageKey],
  );

  const isVisible = useCallback((id) => !hidden.includes(id), [hidden]);

  const pickerTable = useMemo(
    () => ({
      getAllLeafColumns: () =>
        options.map(({ id, label }) => ({
          id,
          columnDef: { header: label },
          getCanHide: () => true,
          getIsVisible: () => !hidden.includes(id),
          getToggleVisibilityHandler: () => () => toggle(id),
        })),
    }),
    [options, hidden, toggle],
  );

  return { isVisible, pickerTable };
}
