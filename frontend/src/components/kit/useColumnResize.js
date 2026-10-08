import { useCallback, useEffect, useRef } from 'react';
import { resizeColumns } from '../../pages/ventasMlTableHelpers';

const KEYBOARD_STEP = 10;

/**
 * Pointer + keyboard resizing for the Ventas ML header grips.
 *
 * The table renders every `size` as a SHARE of the visible total (see the
 * `<colgroup>` in `VentasML.jsx`), so TanStack's own drag handler would move
 * the border at the wrong scale. Instead the real rendered pixel widths are
 * measured when a drag starts, the border between two columns is moved with
 * `resizeColumns`, and the full pixel map goes into the shared
 * `useColumnSizing` state (persisted + resettable).
 */
export function useColumnResize({ visibleColumns, theadRef, onSizingChange }) {
  const cleanupRef = useRef(null);

  const measure = useCallback(() => {
    const widths = {};
    const mins = {};
    visibleColumns.forEach((col) => {
      const th = theadRef.current?.querySelector(`[data-col-id="${col.id}"]`);
      const real = th ? th.getBoundingClientRect().width : 0;
      // jsdom / hidden table: no layout, fall back to the column's own size.
      widths[col.id] = real > 0 ? real : col.getSize();
      mins[col.id] = col.columnDef.minSize ?? 40;
    });
    return { widths, mins, order: visibleColumns.map((c) => c.id) };
  }, [visibleColumns, theadRef]);

  useEffect(() => () => cleanupRef.current?.(), []);

  const startDrag = useCallback(
    (columnId, event) => {
      if (event.type === 'mousedown') event.preventDefault();
      const startX = event.touches ? event.touches[0].clientX : event.clientX;
      const start = measure();
      const move = (e) => {
        const x = e.touches ? e.touches[0].clientX : e.clientX;
        onSizingChange(resizeColumns(start.widths, start.order, columnId, x - startX, start.mins));
      };
      const end = () => {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', end);
        document.removeEventListener('touchmove', move);
        document.removeEventListener('touchend', end);
        cleanupRef.current = null;
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', end);
      document.addEventListener('touchmove', move);
      document.addEventListener('touchend', end);
      cleanupRef.current = end;
    },
    [measure, onSizingChange],
  );

  const keyResize = useCallback(
    (columnId, event) => {
      const direction = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
      if (!direction) return;
      event.preventDefault();
      const { widths, mins, order } = measure();
      onSizingChange(resizeColumns(widths, order, columnId, direction * KEYBOARD_STEP, mins));
    },
    [measure, onSizingChange],
  );

  return { startDrag, keyResize };
}
