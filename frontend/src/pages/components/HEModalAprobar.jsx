import { useState, useEffect } from 'react';
import styles from '../RRHHHorasExtras.module.css';

/**
 * Modal aprobar HE — individual o bulk — con override % opcional.
 *
 * Props:
 *  - open: boolean
 *  - bulkCount: number|null  (si null/0 → individual)
 *  - defaultPorcentaje: number|null (% sugerido del bloque)
 *  - onConfirm: async ({ porcentaje_override, observaciones }) => void
 *  - onClose: () => void
 *
 * Spec: T-6.10 — input numérico opcional 0-500, observaciones opcional.
 */
export default function HEModalAprobar({
  open,
  bulkCount = null,
  defaultPorcentaje = null,
  onConfirm,
  onClose,
}) {
  const [porcentaje, setPorcentaje] = useState('');
  const [observaciones, setObservaciones] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) {
      setPorcentaje('');
      setObservaciones('');
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

  const isBulk = bulkCount !== null && bulkCount > 0;
  const pctNum = porcentaje === '' ? null : Number(porcentaje);
  const pctValid = pctNum === null || (Number.isFinite(pctNum) && pctNum >= 0 && pctNum <= 500);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!pctValid || saving) return;
    setSaving(true);
    setError(null);
    try {
      const body = {};
      if (pctNum !== null) body.porcentaje_override = pctNum;
      if (observaciones.trim()) body.observaciones = observaciones.trim();
      await onConfirm(body);
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Error al aprobar');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay-tesla" onClick={() => !saving && onClose()}>
      <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-tesla">
          <h2 className="modal-title-tesla">
            {isBulk ? `Aprobar ${bulkCount} bloque${bulkCount === 1 ? '' : 's'}` : 'Aprobar bloque'}
          </h2>
          <button className="btn-close-tesla" onClick={onClose} aria-label="Cerrar" disabled={saving}>
            ✕
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body-tesla">
            {error && <div className={styles.errorMsg}>{error}</div>}

            <div className={styles.formGroup}>
              <label htmlFor="he-porcentaje">% recargo (opcional, override)</label>
              <input
                id="he-porcentaje"
                type="number"
                className={styles.input}
                value={porcentaje}
                onChange={(e) => setPorcentaje(e.target.value)}
                min={0}
                max={500}
                step={1}
                placeholder={defaultPorcentaje !== null ? `Por defecto: ${defaultPorcentaje}%` : 'Dejar vacío = mantener'}
                autoFocus
              />
              <div className={styles.quickPicks}>
                <button type="button" className={styles.quickPick} onClick={() => setPorcentaje('50')}>50%</button>
                <button type="button" className={styles.quickPick} onClick={() => setPorcentaje('100')}>100%</button>
                <button type="button" className={styles.quickPick} onClick={() => setPorcentaje('')}>Limpiar</button>
              </div>
              {!pctValid && (
                <span style={{ color: 'var(--cf-accent-red)', fontSize: 'var(--font-xs)' }}>
                  El porcentaje debe estar entre 0 y 500.
                </span>
              )}
            </div>

            <div className={styles.formGroup}>
              <label htmlFor="he-obs">Observaciones (opcional)</label>
              <textarea
                id="he-obs"
                className={styles.textarea}
                value={observaciones}
                onChange={(e) => setObservaciones(e.target.value)}
                maxLength={2000}
                placeholder="Notas internas..."
              />
            </div>
          </div>
          <div className="modal-footer-tesla">
            <button type="button" className={styles.btnSecondary} onClick={onClose} disabled={saving}>
              Cancelar
            </button>
            <button type="submit" className={styles.btnApprove} disabled={!pctValid || saving}>
              {saving ? 'Aprobando...' : (isBulk ? `Aprobar ${bulkCount}` : 'Aprobar')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
