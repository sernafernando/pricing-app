import styles from './productSelection.module.css';

/**
 * Row selection of Publicaciones ML for the bulk pricing actions. Pricing is per PRODUCT, so a row's checkbox
 * checks its linked product: every publication of that product reads checked, in any view. A publication with no
 * linked product cannot be checked and says why.
 */
export function ProductCheckbox({ productId, checked, onToggle, label }) {
  const missing = productId == null;
  return (
    <input
      type="checkbox"
      className={styles.check}
      checked={!missing && checked}
      disabled={missing}
      onChange={() => onToggle(productId)}
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
