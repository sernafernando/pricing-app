import { formatMarkupRange } from '../markupRange';
import { MARKUP_REASONS, UNKNOWN_REASON } from '../markupReasons';
import cellStyles from '../cells.module.css';
import styles from './panel.module.css';

/**
 * The markup under the price: green, or red when any variation is negative, so it
 * reads apart from the price without a label. "—" with the reason when there is none.
 */
export default function HeaderMarkup({ markup }) {
  if (markup?.min == null || markup?.max == null) {
    return (
      <span className={cellStyles.empty} title={MARKUP_REASONS[markup?.reason] ?? UNKNOWN_REASON}>
        <span className={styles.visuallyHidden}>Markup </span>—
      </span>
    );
  }
  return (
    <span className={styles.figureMarkup} data-negative={markup.any_negative ? '' : undefined} title="Markup">
      <span className={styles.visuallyHidden}>Markup </span>
      {formatMarkupRange(markup.min, markup.max)}
    </span>
  );
}

