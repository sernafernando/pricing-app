/**
 * Seg — the approved tactical design's segmented control: plain buttons with `aria-pressed`, the current one filled
 * with the primary color. `size` `xs` / `xxs` are the design's compact versions inside a line; `disabled` lists the
 * values that cannot be chosen.
 */
import styles from './Seg.module.css';

export default function Seg({ label, options, value, onChange, size, disabled = [] }) {
  return (
    <div className={`${styles.seg} ${size ? styles[size] : ''}`} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          disabled={disabled.includes(option.value)}
          onClick={() => option.value !== value && onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
