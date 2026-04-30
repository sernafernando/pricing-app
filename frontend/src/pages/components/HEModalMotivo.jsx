import { useState, useEffect } from 'react';
import { AlertTriangle } from 'lucide-react';
import styles from '../RRHHHorasExtras.module.css';

/**
 * Modal genérico para acciones que requieren motivo (rechazo / descarte / reapertura).
 *
 * Props:
 *  - open: boolean
 *  - title: string
 *  - confirmLabel: string ("Rechazar" | "Descartar día" | "Reabrir")
 *  - confirmVariant: 'danger' | 'warning' | 'primary'  (estilo del botón Confirmar)
 *  - placeholder: string (placeholder del textarea)
 *  - warning: string|null  (texto opcional de advertencia, ej. liquidación cerrada)
 *  - bulkCount: number|null (cuántos bloques aplica el motivo, para variante bulk)
 *  - onConfirm: async (motivo) => void
 *  - onClose: () => void
 *
 * Spec: T-6.9 — motivo obligatorio (min 3 chars, max 2000).
 */
export default function HEModalMotivo({
  open,
  title,
  confirmLabel = 'Confirmar',
  confirmVariant = 'danger',
  placeholder = 'Indique el motivo...',
  warning = null,
  bulkCount = null,
  onConfirm,
  onClose,
}) {
  const [motivo, setMotivo] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) {
      setMotivo('');
      setError(null);
      setSaving(false);
    }
  }, [open]);

  // ESC para cerrar
  useEffect(() => {
    if (!open) return;
    const handleKey = (e) => {
      if (e.key === 'Escape' && !saving) onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, saving, onClose]);

  if (!open) return null;

  const trimmed = motivo.trim();
  const isValid = trimmed.length >= 3 && trimmed.length <= 2000;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isValid || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onConfirm(trimmed);
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Error al procesar la acción');
    } finally {
      setSaving(false);
    }
  };

  const btnClass =
    confirmVariant === 'warning'
      ? styles.btnWarning
      : confirmVariant === 'primary'
        ? styles.btnPrimary
        : styles.btnDanger;

  return (
    <div className="modal-overlay-tesla" onClick={() => !saving && onClose()}>
      <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-tesla">
          <h2 className="modal-title-tesla">{title}</h2>
          <button className="btn-close-tesla" onClick={onClose} aria-label="Cerrar" disabled={saving}>
            ✕
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body-tesla">
            {warning && (
              <div className={styles.warningBox}>
                <AlertTriangle size={16} />
                <span>{warning}</span>
              </div>
            )}
            {bulkCount !== null && bulkCount > 0 && (
              <div className={styles.warningBox}>
                <AlertTriangle size={16} />
                <span>El motivo se aplicará a <strong>{bulkCount}</strong> bloque{bulkCount === 1 ? '' : 's'} seleccionado{bulkCount === 1 ? '' : 's'}.</span>
              </div>
            )}
            {error && <div className={styles.errorMsg}>{error}</div>}
            <div className={styles.formGroup}>
              <label htmlFor="he-motivo">Motivo (mínimo 3 caracteres)</label>
              <textarea
                id="he-motivo"
                className={styles.textarea}
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                maxLength={2000}
                placeholder={placeholder}
                required
                autoFocus
              />
            </div>
          </div>
          <div className="modal-footer-tesla">
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={onClose}
              disabled={saving}
            >
              Cancelar
            </button>
            <button
              type="submit"
              className={btnClass}
              disabled={!isValid || saving}
            >
              {saving ? 'Procesando...' : confirmLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
