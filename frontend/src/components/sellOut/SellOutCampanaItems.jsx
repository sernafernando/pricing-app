import { X } from 'lucide-react';
import SellInBuscador from '../sellIn/SellInBuscador';
import styles from '../sellIn/SellInPanel.module.css';
import { buscarProductos } from './sellOutBuscar';
import { nombreDeItem } from './sellOutFormat';


/**
 * The products of a `por_unidad` campaign that get their own amount per unit (T22c, legacy grouped offsets),
 * in the campaign's currency: picked with the catalog search, edited and removed in place. Controlled.
 */
export default function SellOutCampanaItems({ items, moneda, onChange }) {
  const agregar = ({ producto }) => {
    if (items.some((i) => i.itemId === producto.item_id)) return;
    onChange([...items, { itemId: producto.item_id, codigo: producto.codigo, descripcion: producto.descripcion, monto: '' }]);
  };
  const setMonto = (itemId, monto) => onChange(items.map((i) => (i.itemId === itemId ? { ...i, monto } : i)));

  return (
    <section className={styles.section} aria-label="Montos por producto">
      <h3>Montos por producto</h3>
      <p className={styles.hint}>
        Opcional. Los productos sin monto propio usan el monto por unidad de la campaña; todos comparten el tope de la campaña.
      </p>
      <SellInBuscador label="Agregar producto" placeholder="Buscar por código o descripción…" buscar={buscarProductos} onPick={agregar} errorMessage="No se pudieron buscar productos." />
      {items.map((item) => (
        <div key={item.itemId} className={styles.linea}>
          <span className={styles.lineaNombre}>
            <span className={styles.mono}>{nombreDeItem(item)}</span> {item.descripcion}
          </span>
          <input
            type="number"
            min="0"
            step="0.01"
            className={styles.inputSm}
            aria-label={`Monto de ${nombreDeItem(item)}`}
            placeholder={`Monto (${moneda})`}
            value={item.monto}
            onChange={(e) => setMonto(item.itemId, e.target.value)}
          />
          <button type="button" className={styles.close} aria-label={`Quitar ${nombreDeItem(item)}`} onClick={() => onChange(items.filter((i) => i.itemId !== item.itemId))}>
            <X size={14} />
          </button>
        </div>
      ))}
    </section>
  );
}
