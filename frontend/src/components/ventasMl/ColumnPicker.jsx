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
const POPOVER_ID = 'ventas-ml-column-picker';

export default function ColumnPicker({ table }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);
  const triggerRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function handleClickOutside(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    // Escape closes it and returns focus to the trigger, the behaviour any
    // keyboard user expects from something opened with `aria-expanded`.
    // Without it the only way out is a mouse click elsewhere.
    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  const toggleableColumns = table.getAllLeafColumns().filter((col) => col.getCanHide());

  return (
    <div className={styles.container} ref={containerRef}>
      {/* NO `aria-haspopup` on this trigger. In ARIA, `aria-haspopup="true"`
          is literally `"menu"` -- announcing to a screen reader the very
          contract the popover below deliberately does NOT claim.
          `aria-expanded` plus `aria-controls` say what is actually true: this
          button shows and hides that group. */}
      <button
        type="button"
        ref={triggerRef}
        className="btn-tesla outline sm"
        aria-expanded={open}
        aria-controls={POPOVER_ID}
        onClick={() => setOpen((prev) => !prev)}
      >
        <Columns3 size={14} />
        Columnas
      </button>
      {/* `role="group"`, NOT `role="menu"`: a `menu` expects
          `menuitemcheckbox` children with full arrow-key navigation, and these
          are plain `<label><input type="checkbox">` pairs. Claiming `menu`
          tells a screen reader to expect a keyboard contract this popover does
          not implement, which is worse than claiming nothing. A group of
          native checkboxes is already announced correctly. */}
      {open && (
        <div id={POPOVER_ID} className={styles.popover} role="group" aria-label="Elegir columnas visibles">
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
