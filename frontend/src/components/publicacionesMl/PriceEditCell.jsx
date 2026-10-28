import { useEffect, useRef, useState } from 'react';
import { formatPrecioInput } from '../../utils/precioInput';
import { formatAmount } from '../../utils/ventasMlFormat';
import styles from './cells.module.css';

/**
 * A price of the table edited in place (S11c). The cell (`children`) is a button; a click opens an input with the
 * current `value` as editable text, Enter hands the typed text to `onSave` (which parses, confirms and writes it),
 * Escape or leaving the input drops it. The input's keys stay in the input: the row and its shortcuts never see them.
 *
 * Keyboard, as Productos' editors: Tab / Shift+Tab cycle the editor's own controls (wrapping, so the focus never
 * leaves it), and Escape puts the focus back on the cell's button, the active price of `usePublicacionesMLKeyboard`
 * (which finds the button by `data-price-cell`).
 */
const FOCUSABLE = 'input, button';

/** Tab / Shift+Tab move over `root`'s enabled controls, wrapping around. */
function cycleFocus(event, root) {
  const focusable = Array.from(root.querySelectorAll(FOCUSABLE)).filter((element) => !element.disabled);
  if (focusable.length === 0) return;
  const index = focusable.indexOf(document.activeElement);
  const next = event.shiftKey ? (index <= 0 ? focusable.length - 1 : index - 1) : (index + 1) % focusable.length;
  focusable[next].focus();
}

export default function PriceEditCell({ label, value, onSave, saving = false, children }) {
  const [draft, setDraft] = useState(null);
  const priced = value != null && Number(value) > 0;
  const button = useRef(null);
  const editor = useRef(null);
  // Escape hands the focus back to the button once it is drawn again.
  const refocus = useRef(false);
  useEffect(() => {
    if (draft !== null || !refocus.current) return;
    refocus.current = false;
    button.current?.focus();
  }, [draft]);

  if (draft === null) {
    return (
      <button
        ref={button}
        type="button"
        data-price-cell=""
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
      refocus.current = true;
      setDraft(null);
    } else if (event.key === 'Tab') {
      event.preventDefault();
      cycleFocus(event, editor.current);
    }
  };

  return (
    <span ref={editor} className={styles.priceEditor}>
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
    </span>
  );
}
