import { useState } from 'react';
import styles from './ProductPrices.module.css';

/**
 * The rebate and web transfer editors of ONE product (their drafts and writes are in `toggleWrites`). Shared by the
 * product panel's ProductToggles and Publicaciones ML's row.
 */

/** The editor's keys: Enter saves, Escape cancels the edit (not the side panel or the row around it). */
const editorKeys = (onSave, onCancel) => (event) => {
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
    <div className={styles.warningActions}>
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
