import { X } from 'lucide-react';
import SellInLotes from './SellInLotes';
import { formatEntero } from './sellInFormat';
import styles from './SellInPanel.module.css';

/**
 * The side panel a row of Sell in's Productos list opens: the product's lots and its cost mode (`SellInLotes`, which
 * holds `SellInModoCosto`), under "Costo de sell in · <producto>" and its code with the units in stock, as in the
 * approved cost-mode design. `onChanged` runs after a mode change, so the list can read it again.
 */
export default function SellInProductoCostoPanel({ producto, onChanged, onClose }) {
  const nombre = producto.descripcion ?? producto.codigo;
  return (
    <div className={styles.panel}>
      <header className={styles.panelHeader}>
        <div>
          <h2>Costo de sell in · {nombre}</h2>
          <p className={styles.hint}>
            {producto.codigo} · {formatEntero(producto.unidades)} unidades en stock
          </p>
        </div>
        <button type="button" className={styles.close} aria-label="Cerrar" onClick={onClose}>
          <X size={18} />
        </button>
      </header>
      <div className={styles.panelBody}>
        <SellInLotes key={producto.item_id} productItemId={producto.item_id} onChanged={onChanged} />
      </div>
    </div>
  );
}
