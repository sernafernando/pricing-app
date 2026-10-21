import { useId } from 'react';
import { SegmentedControl } from '../kit';
import styles from './SellInPanel.module.css';

const MONEDAS = [
  { value: 'USD', label: 'USD' },
  { value: 'ARS', label: 'ARS' },
];

/**
 * The fields of a brand bonus (Stitch `03`, "Definición"): brand from the
 * brand filter's list, amount per invoiced unit, currency (USD by default) and
 * the supplier-invoice date range. Controlled; `disabled` makes it read-only.
 */
export default function SellInBonoForm({ valores, onChange, marcas, disabled = false }) {
  const id = useId();
  const set = (patch) => onChange({ ...valores, ...patch });
  // A bonus keeps its brand even when it is no longer in the filter's list.
  const opciones = valores.marca && !marcas.includes(valores.marca) ? [valores.marca, ...marcas] : marcas;

  return (
    <>
      <div className={styles.grid2}>
        <label className={styles.field} htmlFor={`${id}-marca`}>
          <span className={styles.label}>Marca</span>
          <select id={`${id}-marca`} className={styles.select} value={valores.marca} disabled={disabled} onChange={(e) => set({ marca: e.target.value })}>
            <option value="">Elegir marca…</option>
            {opciones.map((marca) => (
              <option key={marca} value={marca}>
                {marca}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field} htmlFor={`${id}-monto`}>
          <span className={styles.label}>Monto por unidad</span>
          <input
            id={`${id}-monto`}
            type="number"
            min="0"
            step="0.01"
            className={styles.input}
            value={valores.montoUnit}
            disabled={disabled}
            onChange={(e) => set({ montoUnit: e.target.value })}
          />
        </label>
      </div>
      <div className={styles.field}>
        <span className={styles.label}>Moneda</span>
        {disabled ? (
          <span>{valores.moneda}</span>
        ) : (
          <SegmentedControl label="Moneda" options={MONEDAS} value={valores.moneda} onChange={(moneda) => set({ moneda })} />
        )}
      </div>
      <div className={styles.grid2}>
        <label className={styles.field} htmlFor={`${id}-desde`}>
          <span className={styles.label}>Factura desde</span>
          <input id={`${id}-desde`} type="date" className={styles.input} value={valores.fechaDesde} disabled={disabled} onChange={(e) => set({ fechaDesde: e.target.value })} />
        </label>
        <label className={styles.field} htmlFor={`${id}-hasta`}>
          <span className={styles.label}>Factura hasta</span>
          <input id={`${id}-hasta`} type="date" className={styles.input} value={valores.fechaHasta} disabled={disabled} onChange={(e) => set({ fechaHasta: e.target.value })} />
        </label>
      </div>
      <label className={styles.field} htmlFor={`${id}-desc`}>
        <span className={styles.label}>Descripción</span>
        <input id={`${id}-desc`} type="text" className={styles.input} value={valores.descripcion} disabled={disabled} onChange={(e) => set({ descripcion: e.target.value })} />
      </label>
      <p className={styles.hint}>
        Se aplica sola a cada compra de la marca cuya fecha de factura del proveedor cae en el rango, al vincularse la factura. Cuenta las unidades facturadas, netas de notas de crédito.
      </p>
    </>
  );
}
