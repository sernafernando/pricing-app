import { useState, useEffect } from 'react';
import { AlertTriangle } from 'lucide-react';
import styles from '../RRHHHorasExtras.module.css';

/**
 * Modal liquidar bloques aprobados — pide periodo YYYYMM.
 *
 * Props:
 *  - open: boolean
 *  - selectedIds: number[]
 *  - onConfirm: async ({ periodo, ids }) => void
 *  - onClose: () => void
 */
function currentPeriodo() {
  const now = new Date();
  return `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}`;
}

export default function HEModalLiquidar({ open, selectedIds = [], onConfirm, onClose }) {
  const [periodo, setPeriodo] = useState(currentPeriodo());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) {
      setPeriodo(currentPeriodo());
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

  const isValid = /^\d{6}$/.test(periodo) && selectedIds.length > 0;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isValid || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onConfirm({ periodo, ids: selectedIds });
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Error al liquidar');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay-tesla" onClick={() => !saving && onClose()}>
      <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-tesla">
          <h2 className="modal-title-tesla">Liquidar bloques aprobados</h2>
          <button className="btn-close-tesla" onClick={onClose} aria-label="Cerrar" disabled={saving}>
            ✕
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body-tesla">
            {error && <div className={styles.errorMsg}>{error}</div>}
            <div className={styles.warningBox}>
              <AlertTriangle size={16} />
              <span>
                Se liquidarán <strong>{selectedIds.length}</strong> bloque{selectedIds.length === 1 ? '' : 's'}.
                Esta acción es reversible solo con permiso <code>liquidar_horas_extras</code>.
              </span>
            </div>
            <div className={styles.formGroup}>
              <label htmlFor="he-periodo">Período de liquidación (YYYYMM)</label>
              <input
                id="he-periodo"
                type="text"
                className={styles.input}
                value={periodo}
                onChange={(e) => setPeriodo(e.target.value.replace(/[^0-9]/g, '').slice(0, 6))}
                pattern="\d{6}"
                placeholder="202604"
                required
                autoFocus
              />
            </div>
          </div>
          <div className="modal-footer-tesla">
            <button type="button" className={styles.btnSecondary} onClick={onClose} disabled={saving}>
              Cancelar
            </button>
            <button type="submit" className={styles.btnPrimary} disabled={!isValid || saving}>
              {saving ? 'Liquidando...' : `Liquidar ${selectedIds.length}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
