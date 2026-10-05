import { Check } from 'lucide-react';
import styles from './SwitchChip.module.css';

/**
 * An on/off filter shaped like the board's chips (Métricas ML "Solo con
 * ventas en el período"): a `role="switch"` pill, filled while on, with a
 * check box saying so. `onChange(next)` gets the state a click asks for.
 */
export default function SwitchChip({ label, checked, onChange, title }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={`${styles.chip} ${checked ? styles.on : ''}`}
      title={title}
      onClick={() => onChange(!checked)}
    >
      <span className={styles.box} aria-hidden="true">
        {checked && <Check size={11} strokeWidth={3} />}
      </span>
      {label}
    </button>
  );
}
