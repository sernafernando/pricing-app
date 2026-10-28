import { useState } from 'react';
import { formatPrecioInput } from '../../utils/precioInput';
import { formatAmount } from '../../utils/ventasMlFormat';
import styles from './cells.module.css';

/**
 * A price of the table edited in place (S11c). The cell (`children`) is a button; a click opens an input with the
 * current `value` as editable text, Enter hands the typed text to `onSave` (which parses, confirms and writes it),
 * Escape or leaving the input drops it. The input's keys stay in the input: the row and its shortcuts never see them.
 */
export default function PriceEditCell({ label, value, onSave, saving = false, children }) {
  const [draft, setDraft] = useState(null);
  const priced = value != null && Number(value) > 0;

  if (draft === null) {
    return (
      <button
        type="button"
        className={styles.editable}
        // The price too: the name replaces the cell's text for a screen reader.
        aria-label={`Editar ${label}: ${priced ? formatAmount(value) : 'sin precio'}`}
        title={`Editar ${label}`}
        disabled={saving}
        onClick={() => setDraft(formatPrecioInput(priced ? value : null))}
      >
        {children}
      </button>
    );
  }

  const handleKeyDown = (event) => {
    event.stopPropagation();
    if (event.key === 'Enter') {
      event.preventDefault();
      const typed = draft;
      setDraft(null);
      onSave(typed);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      setDraft(null);
    }
  };

  return (
    <input
      className={styles.priceInput}
      aria-label={label}
      inputMode="decimal"
      autoFocus
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onKeyDown={handleKeyDown}
      onBlur={() => setDraft(null)}
    />
  );
}
