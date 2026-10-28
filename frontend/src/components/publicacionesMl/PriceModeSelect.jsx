import styles from './ColorLayerSelect.module.css';

const OPTIONS = [
  { value: 'normal', label: 'Normal' },
  { value: 'cuotas', label: 'Cuotas' },
  { value: 'pvp', label: 'PVP' },
];

/**
 * Which of Productos' price columns the table shows (S11): Productos' Normal / Cuotas / PVP modes (Alt+V steps
 * through them). Labelled like the layer's select, in the filter card.
 */
export default function PriceModeSelect({ value, onChange, labelClassName }) {
  return (
    <label className={styles.layer}>
      <span className={labelClassName}>Precios:</span>
      <select
        className={styles.select}
        aria-label="Precios"
        title="Precios de Productos: Normal, Cuotas o PVP (Alt+V)"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
