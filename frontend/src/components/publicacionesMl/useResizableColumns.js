import { useCallback } from 'react';
import { useColumnSizing } from '../ml-bot/useColumnSizing';

/**
 * The widths the user gave the table's first column (Publicación, or Producto in the Producto view), one stored key
 * per view: each view reads its own column (pubml-tabla-columnas S5), the Agrupado tree's included.
 */
export const PUBML_COLUMN_SIZING_KEYS = {
  lista: 'pubml:colsizing:lista',
  producto: 'pubml:colsizing:producto',
  agrupado: 'pubml:colsizing:agrupado',
};

/**
 * `TableShell`'s `columnWidths` / `onColumnResize` over a persisted `useColumnSizing`: a width (px) is saved for its
 * column, `null` drops it (back to the default), and the key goes when no width is left.
 */
export default function useResizableColumns(storageKey) {
  const { columnSizing, onColumnSizingChange, reset } = useColumnSizing(storageKey);
  const onColumnResize = useCallback(
    (key, width) => {
      if (width != null) {
        onColumnSizingChange((prev) => ({ ...prev, [key]: width }));
        return;
      }
      if (Object.keys(columnSizing).every((other) => other === key)) {
        reset();
        return;
      }
      onColumnSizingChange((prev) => Object.fromEntries(Object.entries(prev).filter(([other]) => other !== key)));
    },
    [columnSizing, onColumnSizingChange, reset],
  );
  return { columnWidths: columnSizing, onColumnResize };
}
