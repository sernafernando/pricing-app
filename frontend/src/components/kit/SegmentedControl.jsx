import styles from './SegmentedControl.module.css';

/**
 * Two-or-more-way switch ("Agrupar por: Producto | Publicación"), the
 * design's segmented pill. Plain buttons with `aria-pressed`: one of them is
 * always the current value.
 */
export default function SegmentedControl({ label, options, value, onChange }) {
  return (
    <div className={styles.group} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`${styles.option} ${option.value === value ? styles.active : ''}`}
          aria-pressed={option.value === value}
          onClick={() => option.value !== value && onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
