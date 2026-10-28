import { useEffect, useRef } from 'react';
import styles from './productSelection.module.css';

/**
 * Row selection of Publicaciones ML for the bulk pricing actions. Pricing is per PRODUCT, so a row's checkbox
 * checks its linked product: every publication of that product reads checked, in any view. A publication with no
 * linked product cannot be checked and says why. `onToggle(productId, extend)`: `extend` is Shift, a range.
 */
export function ProductCheckbox({ productId, checked, onToggle, label }) {
  const missing = productId == null;
  return (
    <input
      type="checkbox"
      className={styles.check}
      checked={!missing && checked}
      disabled={missing}
      onChange={(event) => {
        // Shift+click checks the range from the product toggled last (S12d); it would also select the rows' text.
        const extend = Boolean(event.nativeEvent?.shiftKey);
        if (extend) window.getSelection()?.removeAllRanges();
        onToggle(productId, extend);
      }}
      aria-label={`Seleccionar el producto de ${label}`}
      title={
        missing
          ? 'Sin producto vinculado: no recibe acciones de precio'
          : 'Selecciona el producto: las acciones masivas cambian su precio en todas sus publicaciones'
      }
    />
  );
}

/**
 * The checkbox of `productId` under `selection` (`{ checked: Set, onToggle }`). A title cell places it after its
 * own leading toggle, so the tree's indentation stays driven by depth alone.
 */
export function SelectionCheckbox({ productId, label, selection }) {
  return (
    <ProductCheckbox
      productId={productId}
      checked={productId != null && selection.checked.has(productId)}
      onToggle={selection.onToggle}
      label={label}
    />
  );
}

/**
 * The header's checkbox (S12d, Productos' "select all"): checks every product on the page, or unchecks them when
 * they all are. `state` is `useProductSelection`'s `pageState`; 'some' shows it half checked.
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
      aria-label="Seleccionar los productos de la página"
      title={
        state === 'all'
          ? 'Quita de la selección los productos de esta página'
          : 'Selecciona los productos de esta página; los de otras páginas o filtros quedan como están'
      }
    />
  );
}
