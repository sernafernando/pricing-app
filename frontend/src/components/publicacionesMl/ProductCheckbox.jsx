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

/** `children` (a title cell) led by the checkbox of `productId`; `selection` is `{ checked: Set, onToggle }`. */
export function WithProductCheckbox({ productId, label, selection, children }) {
  return (
    <div className={styles.withCheck}>
      <ProductCheckbox
        productId={productId}
        checked={productId != null && selection.checked.has(productId)}
        onToggle={selection.onToggle}
        label={label}
      />
      {children}
    </div>
  );
}
