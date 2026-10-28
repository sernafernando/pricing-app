import { COLORES_DISPONIBLES } from '../../utils/productosConstants';
import styles from './ColorFilterChips.module.css';

const valueOf = (color) => color.id ?? 'sin_color';

/**
 * Productos' color filter (P6) as swatch chips (the name in the label and the tooltip: one line next to Tienda at
 * 1366): any of its colors and "Sin color" (`sin_color`), several at once. `value` is the picked values
 * (`filters.colores`); the colors are the layer's on show, as the rows are painted.
 */
export default function ColorFilterChips({ value, onChange }) {
  const toggle = (picked) =>
    onChange(value.includes(picked) ? value.filter((v) => v !== picked) : [...value, picked]);

  return (
    <div className={styles.row} role="group" aria-label="Filtrar por color">
      {COLORES_DISPONIBLES.map((color) => {
        const picked = valueOf(color);
        const on = value.includes(picked);
        return (
          <button
            key={picked}
            type="button"
            className={on ? styles.chipActive : styles.chip}
            aria-pressed={on}
            aria-label={color.nombre}
            title={color.nombre}
            onClick={() => toggle(picked)}
          >
            <span
              className={styles.swatch}
              data-empty={color.color ? undefined : ''}
              style={color.color ? { background: color.color } : undefined}
              aria-hidden="true"
            />
          </button>
        );
      })}
    </div>
  );
}
