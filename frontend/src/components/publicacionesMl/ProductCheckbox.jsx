import { useEffect, useRef } from 'react';
import styles from './productSelection.module.css';

/**
 * Row selection of Publicaciones ML. A publication's checkbox checks that publication only, not the other
 * publications of its product; a product row's checkbox (Producto view) checks the product. The price actions and
 * painting are per product: they take the products behind the checked rows. A product row with no product cannot be
 * checked and says why. `row` is the row's selection entry (`selectionRow`); `onToggle(row, extend)`: `extend` is
 * Shift, a range.
 */
export function RowCheckbox({ row, product = false, checked, onToggle, label }) {
  const missing = row.key == null;
  return (
    <input
      type="checkbox"
      className={styles.check}
      checked={!missing && checked}
      disabled={missing}
      onChange={(event) => {
        // Shift+click checks the range from the row toggled last (S12d); it would also select the rows' text.
        const extend = Boolean(event.nativeEvent?.shiftKey);
        if (extend) window.getSelection()?.removeAllRanges();
        onToggle(row, extend);
      }}
      aria-label={product ? `Seleccionar el producto ${label}` : `Seleccionar la publicación ${label}`}
      title={
        missing
          ? 'Sin producto vinculado: no recibe acciones'
          : product
            ? 'Selecciona el producto: las acciones de precio lo cambian en todas sus publicaciones'
            : 'Selecciona esta publicación; las acciones de precio usan su producto vinculado'
      }
    />
  );
}

/**
 * The checkbox of the row `row` (`selectionRow`) under `selection` (`{ checked: Map, onToggle }`). A title cell places it after its own
 * leading toggle, so the tree's indentation stays driven by depth alone.
 */
export function SelectionCheckbox({ row, product = false, label, selection }) {
  return (
    <RowCheckbox
      row={row}
      product={product}
      checked={row.key != null && selection.checked.has(row.key)}
      onToggle={selection.onToggle}
      label={label}
    />
  );
}

/**
 * The header's checkbox (S12d, Productos' "select all"): checks every row on the page, or unchecks them when they
 * all are. `state` is `useRowSelection`'s `pageState`; 'some' shows it half checked.
 */
export function PageCheckbox({ state, onToggle }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === 'some';
  }, [state]);
  return (
    <input
      ref={ref}
      type="checkbox"
      className={styles.pageCheck}
      checked={state === 'all'}
      onChange={onToggle}
      aria-label="Seleccionar las filas de la página"
      title={
        state === 'all'
          ? 'Quita de la selección las filas de esta página'
          : 'Selecciona las filas de esta página; las de otras páginas o filtros quedan como están'
      }
    />
  );
}
