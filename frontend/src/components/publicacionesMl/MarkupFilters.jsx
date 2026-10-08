import { useEffect, useState } from 'react';
import { SwitchChip } from '../kit';
import styles from './MarkupFilters.module.css';

/**
 * One bound of the markup range. The operator types freely; the value reaches
 * the URL (and so the backend) on Enter or when the field loses focus, never
 * on every keystroke. A value that is not a number is not sent.
 */
function BoundInput({ label, value, onCommit }) {
  const [draft, setDraft] = useState(value);
  // The URL is the source of truth: a reset or a shared link rewrites the field.
  useEffect(() => setDraft(value), [value]);

  const commit = () => {
    const text = draft.trim().replace(',', '.');
    if (text !== '' && !Number.isFinite(Number(text))) {
      setDraft(value);
      return;
    }
    if (text !== value) onCommit(text);
    // Same bound as the URL's (`-2,5` for `-2.5`): show it the way the URL has it.
    else setDraft(value);
  };

  return (
    <input
      type="text"
      inputMode="decimal"
      className={styles.input}
      aria-label={label}
      placeholder={label.includes('mínimo') ? 'mín. %' : 'máx. %'}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => event.key === 'Enter' && commit()}
    />
  );
}

/**
 * Markup filters of the Publicaciones ML list (decision 5). The markup is the
 * WORST variation's, so "Solo negativos" means ANY variation is negative.
 * Mounted only for users with `ml_metricas.ver_ganancia`.
 */
export default function MarkupFilters({ negative, min, max, onChange }) {
  return (
    <>
      <SwitchChip
        label="Solo negativos"
        title="Publicaciones con alguna variación en markup negativo"
        checked={negative}
        onChange={(next) => onChange({ markup_neg: next ? '1' : '' })}
      />
      <span className={styles.range}>
        <BoundInput label="Markup mínimo (%)" value={min} onCommit={(markup_min) => onChange({ markup_min })} />
        <span aria-hidden="true">–</span>
        <BoundInput label="Markup máximo (%)" value={max} onCommit={(markup_max) => onChange({ markup_max })} />
      </span>
    </>
  );
}
