import { Calculator } from 'lucide-react';
import styles from './cells.module.css';

/**
 * Productos' Calcular (P3c) for one product of the listing: opens the pricing modal on it (its cost and stock come
 * from the same listing). The list's Calcular column and a panel's reference line show the same button.
 */
export default function CalculatePriceButton({ product, onCalculate }) {
  const label = product.descripcion ? `Calcular el precio de ${product.descripcion}` : `Calcular el precio del producto ${product.item_id}`;
  return (
    <button type="button" className={styles.calculate} aria-label={label} title={label} onClick={() => onCalculate(product)}>
      <Calculator size={14} aria-hidden="true" />
    </button>
  );
}
