import { useId } from 'react';
import styles from './ParaGanarScopeFilters.module.css';

export default function ScopeTextFilter({ label, value, onChange, placeholder, disabled }) {
  const inputId = useId();
  return (
    <label className={styles.textFilter} htmlFor={inputId}>
      <span className={styles.srOnly}>{label}</span>
      <input
        id={inputId}
        type="search"
        className={styles.textInput}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder || label}
        disabled={disabled}
        autoComplete="off"
      />
    </label>
  );
}
