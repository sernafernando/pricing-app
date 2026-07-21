import { useState, useCallback, useRef, useEffect } from 'react';

const STEP = 16;
const SHIFT_MULTIPLIER = 4;
const DEBOUNCE_MS = 300;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function readStoredWidths(storageKey, columnsById) {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    const result = {};
    for (const [id, value] of Object.entries(parsed)) {
      const col = columnsById[id];
      if (!col) continue;
      if (typeof value !== 'number' || !Number.isFinite(value)) continue;
      result[id] = clamp(value, col.min, col.max);
    }
    return result;
  } catch {
    return {};
  }
}

function writeStoredWidths(storageKey, widths) {
  try {
    if (Object.keys(widths).length === 0) {
      localStorage.removeItem(storageKey);
    } else {
      localStorage.setItem(storageKey, JSON.stringify(widths));
    }
  } catch {
    // swallow: quota exceeded / private mode / disabled storage
  }
}

/**
 * Manages per-table, per-column resizable widths with drag + keyboard support
 * and localStorage persistence.
 *
 * @param {{ storageKey: string, columns: Array<{id:string,label:string,resizable:boolean,min:number,max:number,defaultWidth:number}> }} params
 * @returns {{
 *   colWidth: (id: string) => number|undefined,
 *   effectiveWidth: (id: string) => number|undefined,
 *   tableWidth: number,
 *   isResized: (id: string) => boolean,
 *   getHandleProps: (id: string) => object,
 *   resetWidths: () => void,
 * }}
 */
export function useResizableColumns({ storageKey, columns }) {
  const columnsById = useRef({});
  columnsById.current = columns.reduce((acc, col) => {
    acc[col.id] = col;
    return acc;
  }, {});

  const [widths, setWidths] = useState(() => readStoredWidths(storageKey, columnsById.current));

  const dragState = useRef(null);
  const debounceTimers = useRef({});

  const colWidth = useCallback((id) => widths[id], [widths]);
  const isResized = useCallback((id) => widths[id] !== undefined, [widths]);

  // Effective px width of a column: the user-resized value if present, else the
  // column's configured defaultWidth. EVERY column (resizable or not) reports a
  // concrete px width so the table can be sized to the exact SUM of its columns.
  const effectiveWidth = useCallback(
    (id) => {
      const col = columnsById.current[id];
      if (!col) return undefined;
      return widths[id] !== undefined ? widths[id] : col.defaultWidth;
    },
    [widths]
  );

  // Total table width = sum of every column's effective width. The table MUST
  // be given this as an explicit width under `table-layout: fixed`: `width:
  // max-content` sizes the table to its CONTENT (long ML titles/answers), which
  // ignores the <col> widths and defeats resizing; an explicit sum makes fixed
  // layout honor each <col> width and truncate overflowing cell content.
  const tableWidth = columns.reduce(
    (sum, col) => sum + (widths[col.id] !== undefined ? widths[col.id] : col.defaultWidth || 0),
    0
  );

  const commitWidth = useCallback(
    (id, value, { debounce = false } = {}) => {
      const col = columnsById.current[id];
      if (!col) return;
      const clamped = clamp(value, col.min, col.max);

      setWidths((prev) => {
        const next = { ...prev, [id]: clamped };

        if (debounce) {
          if (debounceTimers.current[id]) {
            clearTimeout(debounceTimers.current[id]);
          }
          debounceTimers.current[id] = setTimeout(() => {
            writeStoredWidths(storageKey, next);
          }, DEBOUNCE_MS);
        } else {
          writeStoredWidths(storageKey, next);
        }

        return next;
      });
    },
    [storageKey]
  );

  const handleMouseMove = useCallback((event) => {
    const state = dragState.current;
    if (!state) return;
    const { id, startX, baseWidth } = state;
    const dx = event.clientX - startX;
    const col = columnsById.current[id];
    if (!col) return;
    const clamped = clamp(baseWidth + dx, col.min, col.max);
    setWidths((prev) => ({ ...prev, [id]: clamped }));
  }, []);

  const handleMouseUp = useCallback(() => {
    const state = dragState.current;
    document.removeEventListener('mousemove', handleMouseMove);
    document.removeEventListener('mouseup', handleMouseUp);
    // Restore text selection disabled during the drag.
    if (document.body) document.body.style.userSelect = '';
    dragState.current = null;
    if (!state) return;
    setWidths((prev) => {
      writeStoredWidths(storageKey, prev);
      return prev;
    });
  }, [handleMouseMove, storageKey]);

  const handleMouseDown = useCallback(
    (id) => (event) => {
      const col = columnsById.current[id];
      if (!col) return;
      // Prevent the browser from starting a text selection on the header while
      // dragging — without this the drag gesture is swallowed by selection in
      // real browsers (jsdom does not reproduce it, so unit tests can't catch it).
      if (event.preventDefault) event.preventDefault();
      if (document.body) document.body.style.userSelect = 'none';
      const th = event.target.closest ? event.target.closest('th') : null;
      const baseWidth = (th && th.offsetWidth) || col.defaultWidth;
      dragState.current = { id, startX: event.clientX, baseWidth };
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    },
    [handleMouseMove, handleMouseUp]
  );

  const handleKeyDown = useCallback(
    (id) => (event) => {
      const col = columnsById.current[id];
      if (!col) return;
      const current = widths[id] !== undefined ? widths[id] : col.defaultWidth;
      const step = event.shiftKey ? STEP * SHIFT_MULTIPLIER : STEP;

      if (event.key === 'ArrowRight') {
        event.preventDefault();
        commitWidth(id, current + step, { debounce: true });
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        commitWidth(id, current - step, { debounce: true });
      } else if (event.key === 'Home') {
        event.preventDefault();
        commitWidth(id, col.min, { debounce: true });
      } else if (event.key === 'End') {
        event.preventDefault();
        commitWidth(id, col.max, { debounce: true });
      }
    },
    [widths, commitWidth]
  );

  const getHandleProps = useCallback(
    (id) => {
      const col = columnsById.current[id];
      const label = col ? col.label : id;
      return {
        role: 'separator',
        'aria-orientation': 'vertical',
        'aria-label': `Redimensionar columna ${label}`,
        tabIndex: 0,
        onMouseDown: handleMouseDown(id),
        onKeyDown: handleKeyDown(id),
        className: 'resizeHandle',
      };
    },
    [handleMouseDown, handleKeyDown]
  );

  const resetWidths = useCallback(() => {
    Object.values(debounceTimers.current).forEach((timer) => clearTimeout(timer));
    debounceTimers.current = {};
    setWidths({});
    try {
      localStorage.removeItem(storageKey);
    } catch {
      // swallow
    }
  }, [storageKey]);

  useEffect(() => {
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      Object.values(debounceTimers.current).forEach((timer) => clearTimeout(timer));
    };
  }, [handleMouseMove, handleMouseUp]);

  return { colWidth, effectiveWidth, tableWidth, isResized, getHandleProps, resetWidths };
}

export default useResizableColumns;
