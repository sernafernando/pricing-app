import { useState } from 'react';
import { formatRate } from '../pricing/priceFormat';
import { RebateEditor, WebTransfEditor } from '../pricing/toggleEditors';
import { rebateDraft, storedRebate, webTransfDraft } from '../pricing/toggleWrites';
import styles from './cells.module.css';

const EDITORS = {
  rebate: {
    Editor: RebateEditor,
    draft: rebateDraft,
    summary: (product) => (product.participa_rebate ? `${formatRate(storedRebate(product))}% de rebate` : 'sin rebate'),
  },
  web: {
    Editor: WebTransfEditor,
    draft: webTransfDraft,
    summary: (product) => (product.participa_web_transferencia ? `+${webTransfDraft(product).porcentaje}% sobre la clásica` : 'sin web transferencia'),
  },
};

// Keys and clicks inside the editor belong to it: the row (its click opens the panel) and its shortcuts never see them.
const keep = (event) => event.stopPropagation();

/**
 * The rebate ('rebate') or web transfer ('web') of a row's product edited in place (S1), as Productos' row does it:
 * the cell (`children`) is a button that opens the panel's editor, takes part and its %, and for the web transfer
 * "preservar porcentaje". `onSave(draft)` writes it and resolves true when saved, which closes the editor; Cancelar
 * or Escape drop it.
 */
export default function ToggleEditCell({ kind, label, product, saving = false, onSave, children }) {
  const [open, setOpen] = useState(false);
  const { Editor, draft, summary } = EDITORS[kind];

  if (!open) {
    return (
      <button
        type="button"
        className={styles.editable}
        aria-label={`Editar ${label}: ${summary(product)}`}
        title={`Editar ${label}`}
        disabled={saving}
        onClick={() => setOpen(true)}
      >
        {children}
      </button>
    );
  }

  const save = async (edited) => {
    if (await onSave(edited)) setOpen(false);
  };

  return (
    <div onKeyDown={keep} onClick={keep}>
      <Editor initial={draft(product)} saving={saving} onSave={save} onCancel={() => setOpen(false)} className={styles.toggleEditor} />
    </div>
  );
}
