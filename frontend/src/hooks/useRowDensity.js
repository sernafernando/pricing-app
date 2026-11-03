import { useCallback, useState } from 'react';

// Reads the stored density; anything but a stored `true` means the current (normal) density.
function readDense(storageKey) {
  try {
    return JSON.parse(localStorage.getItem(storageKey)) === true;
  } catch {
    return false;
  }
}

/**
 * The "Filas finas" (Sheets-like) row density of a screen's table, kept per screen and per browser under
 * `storageKey`. Off by default: the table keeps its current density until the viewer turns it on.
 */
export default function useRowDensity(storageKey) {
  const [dense, setDense] = useState(() => readDense(storageKey));

  const toggleDense = useCallback(() => {
    setDense((current) => {
      const next = !current;
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        // Storage unavailable (private mode, quota): the choice lasts until the reload.
      }
      return next;
    });
  }, [storageKey]);

  return { dense, toggleDense };
}
