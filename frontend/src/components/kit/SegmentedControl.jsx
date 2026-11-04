import styles from './SegmentedControl.module.css';

/**
 * Two-or-more-way switch ("Agrupar por: Producto | Publicación"), the
 * design's segmented pill. Plain buttons with `aria-pressed`: one of them is
 * always the current value, or none while nothing is picked yet. An option with
 * `disabled` (and a `title` saying why) cannot be picked.
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
          disabled={option.disabled}
          title={option.title}
          onClick={() => option.value !== value && onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
