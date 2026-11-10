/**
 * Seg — the approved tactical design's segmented control: plain buttons with `aria-pressed`, the current one filled
 * with the primary color. `size` `xs` / `xxs` are the design's compact versions inside a line; `disabled` lists the
 * values that cannot be chosen, and `motivo` says why on a disabled one (its tooltip).
 */
import styles from './Seg.module.css';

export default function Seg({ label, options, value, onChange, size, disabled = [], motivo }) {
  return (
    <div className={`${styles.seg} ${size ? styles[size] : ''}`} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          disabled={disabled.includes(option.value)}
          title={motivo && disabled.includes(option.value) ? motivo : undefined}
          onClick={() => option.value !== value && onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
