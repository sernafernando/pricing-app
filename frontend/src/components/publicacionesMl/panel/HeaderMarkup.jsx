import { formatMarkupRange, partialRangeTitle } from '../markupRange';
import { MARKUP_REASONS, UNKNOWN_REASON } from '../markupReasons';
import cellStyles from '../cells.module.css';
import styles from './panel.module.css';

/**
 * The markup under the price: green, or red when any variation is negative, so it
 * reads apart from the price; the grey word "Markup" names it (approved S9 design). "—" with the reason when there is none.
 */
export default function HeaderMarkup({ markup }) {
  if (markup?.min == null || markup?.max == null) {
    return (
      <span className={cellStyles.empty} title={MARKUP_REASONS[markup?.reason] ?? UNKNOWN_REASON}>
        <span className={styles.figureMarkupWord}>Markup </span>—
      </span>
    );
  }
  const partial = markup.partial ?? 0;
  return (
    <span className={styles.figureMarkup} data-negative={markup.any_negative ? '' : undefined} title="Markup">
      <span className={styles.figureMarkupWord}>Markup </span>
      {formatMarkupRange(markup.min, markup.max)}
      {/* As the table: a range that leaves variations without a cost out says so. */}
      {partial > 0 && (
        <span className={styles.figurePartial} title={partialRangeTitle(partial)}>
          {' '}
          (parcial)
        </span>
      )}
    </span>
  );
}

