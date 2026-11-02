import { MARKUP_REASONS, UNKNOWN_REASON } from './markupReasons';
import { formatMarkupRange, partialRangeTitle } from './markupRange';
import styles from './cells.module.css';

/** Markup of a publication (`row.markup`, only with `ml_metricas.ver_ganancia`). */
export default function MarkupCell({ markup }) {
  if (markup == null) return <span className={styles.empty}>—</span>;
  if (markup.min == null || markup.max == null) {
    return (
      <span className={styles.empty} title={MARKUP_REASONS[markup.reason] ?? UNKNOWN_REASON}>
        —
      </span>
    );
  }
  const partial = markup.partial ?? 0;
  return (
    <div className={`${styles.stack} ${styles.stackEnd}`}>
      <span className={styles.markup} data-negative={markup.any_negative ? '' : undefined}>
        {formatMarkupRange(markup.min, markup.max)}
      </span>
      {partial > 0 && (
        <span
          className={styles.note}
          title={partialRangeTitle(partial)}
        >
          (parcial)
        </span>
      )}
    </div>
  );
}
