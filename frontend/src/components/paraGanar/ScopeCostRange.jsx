import { useId } from 'react';
import styles from './ParaGanarScopeFilters.module.css';

/**
 * Alcance filter: ERP cost band in USD (desde / hasta).
 * Not a criterion — only restricts which MLAs appear in the cola.
 */
export default function ScopeCostRange({ min, max, onMinChange, onMaxChange, disabled }) {
  const minId = useId();
  const maxId = useId();

  return (
    <div className={styles.costRange} aria-label="Costo USD">
      <label className={styles.costField} htmlFor={minId}>
        <span className={styles.srOnly}>Costo USD desde</span>
        <input
          id={minId}
          type="number"
          inputMode="decimal"
          min="0"
          step="any"
          className={styles.costInput}
          value={min}
          onChange={(event) => onMinChange(event.target.value)}
          placeholder="USD desde"
          disabled={disabled}
          autoComplete="off"
        />
      </label>
      <span className={styles.costSep} aria-hidden>
        –
      </span>
      <label className={styles.costField} htmlFor={maxId}>
        <span className={styles.srOnly}>Costo USD hasta</span>
        <input
          id={maxId}
          type="number"
          inputMode="decimal"
          min="0"
          step="any"
          className={styles.costInput}
          value={max}
          onChange={(event) => onMaxChange(event.target.value)}
          placeholder="USD hasta"
          disabled={disabled}
          autoComplete="off"
        />
      </label>
    </div>
  );
}
