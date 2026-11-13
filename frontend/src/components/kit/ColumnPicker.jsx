import { useState, useRef, useEffect, useId } from 'react';
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
 * Columns with `enableHiding: false` are left out of the list entirely:
 * offering a checkbox TanStack itself refuses to uncheck would be a dead
 * control. Which ones those are lives in `ventasMlColumns.jsx` and is NOT
 * repeated here -- the list grew once already (Producto and Total Gauss for
 * the information they carry, then alerta, orden and neto for the CONTROLS
 * they hold) and a copy of it here would just rot.
 *
 * `label`, `icon` and `groupLabel` let the same picker list other things a page shows or hides (the KPI
 * cards' "Indicadores"); each instance gets its own popover id, so two can sit side by side. `iconOnly` shows just
 * the icon, the label then naming the button and its tooltip; `buttonClassName` replaces the trigger's look.
 */
export default function ColumnPicker({
  table,
  label = 'Columnas',
  icon = Columns3,
  groupLabel = 'Elegir columnas visibles',
  iconOnly = false,
  buttonClassName = 'btn-tesla outline sm',
}) {
  const Icon = icon;
  const popoverId = useId();
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
        className={iconOnly ? `${buttonClassName} icon-only` : buttonClassName}
        aria-label={iconOnly ? label : undefined}
        title={iconOnly ? label : undefined}
        aria-expanded={open}
        aria-controls={popoverId}
        onClick={() => setOpen((prev) => !prev)}
      >
        <Icon size={14} />
        {!iconOnly && label}
      </button>
      {/* `role="group"`, NOT `role="menu"`: a `menu` expects
          `menuitemcheckbox` children with full arrow-key navigation, and these
          are plain `<label><input type="checkbox">` pairs. Claiming `menu`
          tells a screen reader to expect a keyboard contract this popover does
          not implement, which is worse than claiming nothing. A group of
          native checkboxes is already announced correctly. */}
      {open && (
        <div id={popoverId} className={styles.popover} role="group" aria-label={groupLabel}>
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
