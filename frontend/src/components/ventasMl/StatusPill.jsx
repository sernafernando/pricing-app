import styles from './StatusPill.module.css';

/**
 * A coloured status pill (Stitch `listado`/`detalle`): small, tinted
 * background + border in the tone's colour. `tone` is one of success /
 * danger / warning / info / purple / neutral -- see `utils/ventasMlTone.js`
 * for which status maps to which. An unknown tone falls back to neutral
 * rather than rendering unstyled.
 *
 * `variant="soft"` is the rounded, sentence-case look the detail panel's
 * header uses ("● Pagada"); the default is the table's uppercase tag.
 */
export default function StatusPill({ tone, children, title, dot = false, variant = 'caps' }) {
  const toneClass = styles[tone] || styles.neutral;
  const variantClass = variant === 'soft' ? styles.soft : styles.caps;
  return (
    <span className={`${styles.pill} ${variantClass} ${toneClass}`} title={title}>
      {dot && <span className={styles.dot} aria-hidden="true" />}
      {children}
    </span>
  );
}
