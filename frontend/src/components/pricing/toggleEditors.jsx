import { useState } from 'react';
import styles from './ProductPrices.module.css';

/**
 * The rebate and web transfer editors of ONE product (their drafts and writes are in `toggleWrites`). Shared by the
 * product panel's ProductToggles and Publicaciones ML's row.
 */

// The editors' controls are checkboxes, text inputs and buttons only: the Tab wrap below takes its first and last
// control from this selector (a new kind of control must be added here).
const CONTROLS = 'input, button';

/**
 * The editor's keys: Enter saves, Escape cancels the edit (not the side panel or the row around it), and Tab stays
 * inside the editor as in Productos (`useProductosKeyboard.js`): from its last control it goes back to the first, and
 * Shift+Tab from the first goes to the last. In between, the browser's own order.
 */
const editorKeys = (onSave, onCancel) => (event) => {
  if (event.key === 'Tab') {
    // Disabled while saving: with no enabled control left, Tab is not held.
    const controls = [...event.currentTarget.querySelectorAll(CONTROLS)].filter((el) => !el.disabled);
    if (controls.length === 0) return;
    const [first, last] = [controls[0], controls[controls.length - 1]];
    const [from, to] = event.shiftKey ? [first, last] : [last, first];
    if (event.target === from) {
      event.preventDefault();
      event.stopPropagation();
      to.focus();
    }
    return;
  }
  // Enter on a button is that button's click (Cancelar must not save).
  if (event.key === 'Enter' && event.target.tagName !== 'BUTTON') {
    event.preventDefault();
    onSave();
  } else if (event.key === 'Escape') {
    event.stopPropagation();
    onCancel();
  }
};

function EditorActions({ saving, onCancel }) {
  return (
    // `data-editor-actions`: a narrower layout (a table cell) wraps this row.
    <div className={styles.warningActions} data-editor-actions="">
      <button type="button" className="btn-tesla outline sm" onClick={onCancel} disabled={saving}>
        Cancelar
      </button>
      <button type="submit" className="btn-tesla primary sm" disabled={saving}>
        Guardar
      </button>
    </div>
  );
}

function EditorForm({ label, className, onSave, onCancel, children }) {
  return (
    <form
      className={className ?? styles.editor}
      role="group"
      aria-label={label}
      onKeyDown={editorKeys(onSave, onCancel)}
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
    >
      {children}
    </form>
  );
}

/** `className` replaces the panel's layout (a table cell lays it out narrower). */
export function RebateEditor({ initial, saving, onSave, onCancel, className }) {
  const [draft, setDraft] = useState(initial);
  return (
    <EditorForm label="Rebate" className={className} onSave={() => onSave(draft)} onCancel={onCancel}>
      <label className={styles.check}>
        <input type="checkbox" checked={draft.participa} onChange={(event) => setDraft({ ...draft, participa: event.target.checked })} autoFocus={!draft.participa} disabled={saving} />
        Participa
      </label>
      {draft.participa && (
        <input
          className={styles.input}
          type="text"
          inputMode="decimal"
          aria-label="% de rebate"
          placeholder="%"
          value={draft.porcentaje}
          onChange={(event) => setDraft({ ...draft, porcentaje: event.target.value })}
          onFocus={(event) => event.target.select()}
          disabled={saving}
          autoFocus
        />
      )}
      <EditorActions saving={saving} onCancel={onCancel} />
    </EditorForm>
  );
}

export function WebTransfEditor({ initial, saving, onSave, onCancel, className }) {
  const [draft, setDraft] = useState(initial);
  return (
    <EditorForm label="Web transferencia" className={className} onSave={() => onSave(draft)} onCancel={onCancel}>
      <label className={styles.check}>
        <input type="checkbox" checked={draft.participa} onChange={(event) => setDraft({ ...draft, participa: event.target.checked })} disabled={saving} autoFocus />
        Participa
      </label>
      <input
        className={styles.input}
        type="text"
        inputMode="decimal"
        aria-label="% sobre la clásica"
        placeholder="%"
        value={draft.porcentaje}
        onChange={(event) => setDraft({ ...draft, porcentaje: event.target.value })}
        onFocus={(event) => event.target.select()}
        disabled={saving}
      />
      <label className={styles.check}>
        <input type="checkbox" checked={draft.preservar} onChange={(event) => setDraft({ ...draft, preservar: event.target.checked })} disabled={saving} />
        Conservar el % en cambios masivos
      </label>
      <EditorActions saving={saving} onCancel={onCancel} />
    </EditorForm>
  );
}
