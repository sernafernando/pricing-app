import { MARKUP_REASONS, UNKNOWN_REASON } from './markupReasons';
import { formatMarkupRange, partialRangeTitle } from './markupRange';
import styles from './cells.module.css';

const SISO_TITLE = { true: 'Con sell out al precio de hoy', false: 'Sin sell out: es el markup actual' };

/**
 * Markup actual c/ SO of a publication or a group (`markup_siso`: `{min, max, worst, pending, applies}`, only with
 * `ml_metricas.ver_ganancia`): today's price with the sell out the panel gives each unit. "Pendiente", as
 * Precios, when a unit cannot be priced (a missing rate or campaign base) and none has a value.
 */
export function SisoMarkupCell({ siso }) {
  if (siso == null) return <span className={styles.empty}>—</span>;
  const pending = siso.pending ?? 0;
  if (siso.min == null || siso.max == null) {
    if (pending > 0) {
      return (
        <span className={styles.note} title="Falta el tipo de cambio o la base para calcular el markup">
          Pendiente
        </span>
      );
    }
    return <span className={styles.empty}>—</span>;
  }
  // A group's range mixes publications with and without them: no claim either way (`applies` null).
  const title = siso.applies == null ? undefined : SISO_TITLE[siso.applies];
  return (
    <div className={`${styles.stack} ${styles.stackEnd}`}>
      <span className={styles.markup} data-negative={siso.min < 0 ? '' : undefined} title={title}>
        {formatMarkupRange(siso.min, siso.max)}
      </span>
      {pending > 0 && (
        <span className={styles.note} title="Falta el tipo de cambio o la base para calcular el markup">
          ({pending} {pending === 1 ? 'pendiente' : 'pendientes'})
        </span>
      )}
    </div>
  );
}

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
