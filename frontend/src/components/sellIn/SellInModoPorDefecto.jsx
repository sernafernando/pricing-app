import { useState } from 'react';
import ModalTesla from '../ModalTesla';
import SegmentedControl from '../kit/SegmentedControl';
import { sellInLotesAPI } from '../../services/sellInAPI';
import styles from './SellInModoCosto.module.css';

/**
 * Admin modal for the mode the cost-mode selector opens preselected with (`PUT /sell-in/productos/modo-por-defecto`).
 * It only preselects: nothing is recomputed, a product without a mode stays FIFO, and each user is still offered only
 * the modes their permissions allow (FIFO when the default is not one of them). Mounted only while open, so each
 * opening starts from the saved value.
 *
 * @param {object} props
 * @param {string} props.actual The saved default.
 * @param {{ value: string, label: string }[]} props.options Every mode, in the selector's order.
 * @param {Function} props.onClose Closes without saving.
 * @param {Function} props.onSaved Called with the saved mode.
 */
export default function SellInModoPorDefecto({ actual, options, onClose, onSaved }) {
  const [elegido, setElegido] = useState(actual);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const { data } = await sellInLotesAPI.fijarModoPorDefecto(elegido);
      onSaved(data.modo);
    } catch (err) {
      setError(
        err?.response?.status === 403
          ? 'No tenés permiso para ese cambio.'
          : 'No se pudo guardar el modo por defecto. Probá de nuevo.',
      );
      setSaving(false);
    }
  };

  return (
    <ModalTesla
      isOpen
      onClose={onClose}
      title="Modo por defecto"
      subtitle="Con qué modo abre el selector de modo de costo, para todos los productos."
      size="sm"
      footer={
        <div className={styles.actions}>
          <button type="button" className="btn-tesla outline sm" onClick={onClose} disabled={saving}>
            Cancelar
          </button>
          <button type="button" className="btn-tesla primary sm" onClick={save} disabled={saving || elegido === actual}>
            {saving ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      }
    >
      <div className={styles.wrap}>
        <div className={styles.field}>
          <span className={styles.label}>Abrir en</span>
          <SegmentedControl label="Modo por defecto" options={options} value={elegido} onChange={setElegido} />
        </div>
        <p className={styles.help}>
          No recalcula nada: los productos sin modo propio siguen en FIFO. Quien no tenga permiso para el modo elegido
          ve el selector en FIFO.
        </p>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
      </div>
    </ModalTesla>
  );
}
