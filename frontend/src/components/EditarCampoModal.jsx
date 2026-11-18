import { useEffect, useState } from 'react';
import ModalTesla, { ModalFooterButtons } from './ModalTesla';
import styles from './EditarCampoModal.module.css';

/**
 * Edits one field of a Ventas por Fuera operation (client, code, quantity, ...).
 *
 * `edicion` is `{ label, valor, numerico }` or null (closed). On save it calls
 * `onSave(valor)`: the trimmed text, or for numeric fields a number (null when
 * left empty, which clears the override), the same values the old dashboard sent.
 */
export default function EditarCampoModal({ edicion, onClose, onSave }) {
  const [valor, setValor] = useState('');

  useEffect(() => {
    if (edicion) setValor(String(edicion.valor ?? ''));
  }, [edicion]);

  if (!edicion) return null;

  const guardar = () => {
    if (!edicion.numerico) {
      onSave(valor);
      return;
    }
    const texto = valor.trim().replace(',', '.');
    onSave(texto ? parseFloat(texto) : null);
  };

  const invalido = edicion.numerico && valor.trim() !== '' && Number.isNaN(parseFloat(valor.trim().replace(',', '.')));

  return (
    <ModalTesla
      isOpen
      onClose={onClose}
      title={`Editar ${edicion.label.toLowerCase()}`}
      size="sm"
      footer={<ModalFooterButtons onCancel={onClose} onConfirm={guardar} confirmDisabled={invalido} />}
    >
      <form
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault();
          if (!invalido) guardar();
        }}
      >
        <label className={styles.label} htmlFor="editar-campo-valor">{edicion.label}</label>
        <input
          id="editar-campo-valor"
          className={styles.input}
          type="text"
          inputMode={edicion.numerico ? 'decimal' : 'text'}
          value={valor}
          onChange={(e) => setValor(e.target.value)}
          autoFocus
        />
      </form>
    </ModalTesla>
  );
}
