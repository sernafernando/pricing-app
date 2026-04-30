import { useState, useEffect } from 'react';
import styles from '../RRHHHorasExtras.module.css';

/**
 * Modal recalcular HE en un rango de fechas.
 *
 * Props:
 *  - open: boolean
 *  - onConfirm: async ({ fecha_desde, fecha_hasta }) => void
 *  - onClose: () => void
 *
 * Action global header — perm `gestionar`.
 */
export default function HEModalRecalcular({ open, onConfirm, onClose }) {
  const [desde, setDesde] = useState('');
  const [hasta, setHasta] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (open) {
      setDesde('');
      setHasta('');
      setError(null);
      setResult(null);
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

  const isValid = !!desde && !!hasta && desde <= hasta;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isValid || saving) return;
    setSaving(true);
    setError(null);
    setResult(null);
    try {
      const data = await onConfirm({ fecha_desde: desde, fecha_hasta: hasta });
      setResult(data || { ok: true });
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Error al recalcular');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay-tesla" onClick={() => !saving && onClose()}>
      <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-tesla">
          <h2 className="modal-title-tesla">Recalcular horas extras</h2>
          <button className="btn-close-tesla" onClick={onClose} aria-label="Cerrar" disabled={saving}>
            ✕
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body-tesla">
            {error && <div className={styles.errorMsg}>{error}</div>}
            {result && (
              <div className={styles.warningBox} style={{ background: 'rgba(34, 197, 94, 0.1)', borderColor: 'rgba(34,197,94,0.3)', color: 'var(--cf-accent-green)' }}>
                Recálculo finalizado.
              </div>
            )}
            <p style={{ color: 'var(--cf-text-secondary)', fontSize: 'var(--font-sm)', marginTop: 0 }}>
              Solo afecta bloques en estado <strong>detectada</strong>. Bloques aprobados o liquidados no se modifican.
            </p>
            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label htmlFor="rec-desde">Fecha desde</label>
                <input
                  id="rec-desde"
                  type="date"
                  className={styles.input}
                  value={desde}
                  onChange={(e) => setDesde(e.target.value)}
                  required
                  autoFocus
                />
              </div>
              <div className={styles.formGroup}>
                <label htmlFor="rec-hasta">Fecha hasta</label>
                <input
                  id="rec-hasta"
                  type="date"
                  className={styles.input}
                  value={hasta}
                  onChange={(e) => setHasta(e.target.value)}
                  required
                />
              </div>
            </div>
          </div>
          <div className="modal-footer-tesla">
            <button type="button" className={styles.btnSecondary} onClick={onClose} disabled={saving}>
              Cerrar
            </button>
            <button type="submit" className={styles.btnPrimary} disabled={!isValid || saving}>
              {saving ? 'Recalculando...' : 'Recalcular'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
