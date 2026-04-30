import { useState, useEffect } from 'react';
import styles from '../RRHHHorasExtras.module.css';

/**
 * Modal completar fichada faltante (anomalías).
 *
 * Props:
 *  - open: boolean
 *  - heId: number|null
 *  - onConfirm: async (heId, body) => void
 *  - onClose: () => void
 *
 * Spec: T-6.8 — datetime + tipo (entrada/salida) + motivo (min 3 chars).
 */
export default function HEModalCompletarFichada({ open, heId, onConfirm, onClose }) {
  const [timestamp, setTimestamp] = useState('');
  const [tipo, setTipo] = useState('entrada');
  const [motivo, setMotivo] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) {
      setTimestamp('');
      setTipo('entrada');
      setMotivo('');
      setError(null);
      setSaving(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKey = (e) => {
      if (e.key === 'Escape' && !saving) onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, saving, onClose]);

  if (!open) return null;

  const motivoTrim = motivo.trim();
  const isValid = !!timestamp && !!tipo && motivoTrim.length >= 3;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isValid || saving || !heId) return;
    setSaving(true);
    setError(null);
    try {
      await onConfirm(heId, {
        timestamp,
        tipo,
        motivo: motivoTrim,
      });
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Error al completar fichada');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay-tesla" onClick={() => !saving && onClose()}>
      <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-tesla">
          <h2 className="modal-title-tesla">Completar fichada faltante</h2>
          <button className="btn-close-tesla" onClick={onClose} aria-label="Cerrar" disabled={saving}>
            ✕
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body-tesla">
            {error && <div className={styles.errorMsg}>{error}</div>}

            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label htmlFor="he-timestamp">Timestamp</label>
                <input
                  id="he-timestamp"
                  type="datetime-local"
                  className={styles.input}
                  value={timestamp}
                  onChange={(e) => setTimestamp(e.target.value)}
                  required
                  autoFocus
                />
              </div>
              <div className={styles.formGroup}>
                <label htmlFor="he-tipo">Tipo</label>
                <select
                  id="he-tipo"
                  className={styles.select}
                  value={tipo}
                  onChange={(e) => setTipo(e.target.value)}
                  required
                >
                  <option value="entrada">Entrada</option>
                  <option value="salida">Salida</option>
                </select>
              </div>
            </div>

            <div className={styles.formGroup}>
              <label htmlFor="he-motivo">Motivo (mínimo 3 caracteres)</label>
              <textarea
                id="he-motivo"
                className={styles.textarea}
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                maxLength={2000}
                placeholder="Ej: Empleado olvidó fichar entrada, confirmado con supervisor..."
                required
              />
            </div>
          </div>
          <div className="modal-footer-tesla">
            <button type="button" className={styles.btnSecondary} onClick={onClose} disabled={saving}>
              Cancelar
            </button>
            <button type="submit" className={styles.btnPrimary} disabled={!isValid || saving}>
              {saving ? 'Guardando...' : 'Confirmar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
