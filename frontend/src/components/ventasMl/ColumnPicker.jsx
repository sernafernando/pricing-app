import { useState, useRef, useEffect } from 'react';
import { Columns3 } from 'lucide-react';
import styles from './ColumnPicker.module.css';

/**
 * ColumnPicker — ventas-ml-columnas T6/T7.
 *
 * A popover listing every column the `table` instance knows about
 * (`table.getAllLeafColumns()`), each with a checkbox wired to TanStack's
 * own `column.getToggleVisibilityHandler()` -- the SAME visibility state
 * the header/body render from, so there is no separate "picker state" that
 * could drift from what the table actually shows.
 *
 * Columns with `enableHiding: false` (Producto, Total Gauss -- see
 * `ventasMlColumns.jsx`) are left out of the list entirely: offering a
 * checkbox that TanStack itself refuses to uncheck would be a dead control.
 */
export default function ColumnPicker({ table }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function handleClickOutside(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  const toggleableColumns = table.getAllLeafColumns().filter((col) => col.getCanHide());

  return (
    <div className={styles.container} ref={containerRef}>
      <button
        type="button"
        className="btn-tesla outline sm"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <Columns3 size={14} />
        Columnas
      </button>
      {open && (
        <div className={styles.popover} role="menu" aria-label="Elegir columnas visibles">
          {toggleableColumns.map((col) => (
            <label key={col.id} className={styles.option}>
              <input
                type="checkbox"
                checked={col.getIsVisible()}
                onChange={col.getToggleVisibilityHandler()}
              />
              {col.columnDef.header || col.columnDef.headerAriaLabel || col.id}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
