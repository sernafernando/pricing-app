import { useState, useEffect } from 'react';
import { Edit3 } from 'lucide-react';
import { horasExtrasApi } from '../../services/api';
import styles from '../RRHHHorasExtras.module.css';

/**
 * Modal detalle del bloque + timeline cronológico de historial.
 * Spec: T-6.7
 *
 * Props:
 *  - open: boolean
 *  - heId: number|null
 *  - onClose: () => void
 *  - onUpdated: () => void  (callback luego de editar % u observaciones)
 *  - puedeGestionar: boolean  (perm `gestionar` para mostrar botón Editar)
 */
const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  try {
    const d = new Date(dateStr);
    if (Number.isNaN(d.getTime())) return dateStr;
    return d.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    return dateStr;
  }
};

const formatDateOnly = (dateStr) => {
  if (!dateStr) return '-';
  try {
    const d = new Date(dateStr + 'T12:00:00');
    if (Number.isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return dateStr;
  }
};

export default function HEModalHistorial({ open, heId, onClose, onUpdated, puedeGestionar }) {
  const [bloque, setBloque] = useState(null);
  const [historial, setHistorial] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Edit mode
  const [editing, setEditing] = useState(false);
  const [editPct, setEditPct] = useState('');
  const [editObs, setEditObs] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);

  useEffect(() => {
    if (!open || !heId) return;
    setEditing(false);
    setError(null);
    setLoading(true);
    Promise.all([
      horasExtrasApi.get(heId).catch((e) => { throw e; }),
      horasExtrasApi.historial(heId).catch(() => ({ data: [] })),
    ])
      .then(([bloqueRes, histRes]) => {
        const b = bloqueRes.data || null;
        setBloque(b);
        setHistorial(Array.isArray(histRes.data) ? histRes.data : (histRes.data?.items || []));
        if (b) {
          setEditPct(String(b.porcentaje_recargo ?? ''));
          setEditObs(b.observaciones || '');
        }
      })
      .catch((err) => {
        setError(err?.response?.data?.detail || 'Error al cargar el bloque');
        setBloque(null);
        setHistorial([]);
      })
      .finally(() => setLoading(false));
  }, [open, heId]);

  useEffect(() => {
    if (!open) return;
    const handleKey = (e) => {
      if (e.key === 'Escape' && !savingEdit) onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, savingEdit, onClose]);

  if (!open) return null;

  const canEdit = puedeGestionar && bloque && ['detectada', 'error_fichadas', 'pendiente_asignacion_turno'].includes(bloque.estado);

  const handleSaveEdit = async (e) => {
    e.preventDefault();
    if (!bloque) return;
    setSavingEdit(true);
    setError(null);
    try {
      await horasExtrasApi.update(bloque.id, {
        porcentaje_recargo: editPct === '' ? null : Number(editPct),
        observaciones: editObs.trim() || null,
      });
      setEditing(false);
      if (onUpdated) onUpdated();
      // Refresh
      const { data } = await horasExtrasApi.get(bloque.id);
      setBloque(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Error al guardar');
    } finally {
      setSavingEdit(false);
    }
  };

  return (
    <div className="modal-overlay-tesla" onClick={() => !savingEdit && onClose()}>
      <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-tesla">
          <h2 className="modal-title-tesla">
            Detalle del bloque {bloque ? `#${bloque.id}` : ''}
          </h2>
          <button className="btn-close-tesla" onClick={onClose} aria-label="Cerrar" disabled={savingEdit}>
            ✕
          </button>
        </div>
        <div className="modal-body-tesla">
          {loading && <div className={styles.loading}>Cargando...</div>}
          {error && <div className={styles.errorMsg}>{error}</div>}

          {bloque && !loading && (
            <>
              {/* Datos del bloque */}
              <div className={styles.detailGrid}>
                <div className={styles.detailField}>
                  <label>Empleado</label>
                  <span>{bloque.empleado_nombre || `#${bloque.empleado_id}`}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Legajo</label>
                  <span>{bloque.legajo || '-'}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Fecha</label>
                  <span>{formatDateOnly(bloque.fecha)}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Tipo día</label>
                  <span>{bloque.tipo_dia || '-'}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Estado</label>
                  <span className={styles[`estado--${bloque.estado}`] || styles.estadoBadge}>
                    {bloque.estado}
                  </span>
                </div>
                <div className={styles.detailField}>
                  <label>% recargo</label>
                  <span>{bloque.porcentaje_recargo ?? '-'}%</span>
                </div>
                <div className={styles.detailField}>
                  <label>Minutos extras</label>
                  <span>{bloque.minutos_extra ?? '-'}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Turno esperado (min)</label>
                  <span>{bloque.turno_esperado_minutos ?? '-'}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Trabajado (min)</label>
                  <span>{bloque.minutos_trabajados ?? '-'}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Error tipo</label>
                  <span>{bloque.error_tipo || '-'}</span>
                </div>
              </div>

              {/* Fichadas asociadas */}
              {(bloque.fichada_entrada || bloque.fichada_salida) && (
                <>
                  <div className={styles.sectionTitle}>Fichadas</div>
                  <div className={styles.detailGrid}>
                    <div className={styles.detailField}>
                      <label>Entrada</label>
                      <span>{bloque.fichada_entrada ? formatDate(bloque.fichada_entrada.timestamp) : '-'}</span>
                    </div>
                    <div className={styles.detailField}>
                      <label>Salida</label>
                      <span>{bloque.fichada_salida ? formatDate(bloque.fichada_salida.timestamp) : '-'}</span>
                    </div>
                  </div>
                </>
              )}

              {/* Audit fields */}
              <div className={styles.sectionTitle}>Auditoría</div>
              <div className={styles.detailGrid}>
                <div className={styles.detailField}>
                  <label>Aprobado por</label>
                  <span>{bloque.aprobado_por_nombre || bloque.aprobado_por_id || '-'}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Aprobado el</label>
                  <span>{formatDate(bloque.aprobado_at)}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Liquidado por</label>
                  <span>{bloque.liquidado_por_nombre || bloque.liquidado_por_id || '-'}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Liquidado el</label>
                  <span>{formatDate(bloque.liquidado_at)}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Reabierto por</label>
                  <span>{bloque.reabierto_por_nombre || bloque.reabierto_por_id || '-'}</span>
                </div>
                <div className={styles.detailField}>
                  <label>Reabierto el</label>
                  <span>{formatDate(bloque.reabierto_at)}</span>
                </div>
              </div>

              {/* Observaciones */}
              {bloque.observaciones && !editing && (
                <>
                  <div className={styles.sectionTitle}>Observaciones</div>
                  <p style={{ color: 'var(--cf-text-secondary)', fontSize: 'var(--font-sm)', whiteSpace: 'pre-wrap' }}>
                    {bloque.observaciones}
                  </p>
                </>
              )}

              {/* Edit form */}
              {editing && (
                <form onSubmit={handleSaveEdit}>
                  <div className={styles.sectionTitle}>Editar</div>
                  <div className={styles.formRow}>
                    <div className={styles.formGroup}>
                      <label htmlFor="edit-pct">% recargo</label>
                      <input
                        id="edit-pct"
                        type="number"
                        className={styles.input}
                        value={editPct}
                        onChange={(e) => setEditPct(e.target.value)}
                        min={0}
                        max={500}
                        step={1}
                      />
                    </div>
                  </div>
                  <div className={styles.formGroup}>
                    <label htmlFor="edit-obs">Observaciones</label>
                    <textarea
                      id="edit-obs"
                      className={styles.textarea}
                      value={editObs}
                      onChange={(e) => setEditObs(e.target.value)}
                      maxLength={2000}
                    />
                  </div>
                  <div style={{ display: 'flex', gap: 'var(--spacing-sm)', justifyContent: 'flex-end' }}>
                    <button type="button" className={styles.btnSecondary} onClick={() => setEditing(false)} disabled={savingEdit}>
                      Cancelar edición
                    </button>
                    <button type="submit" className={styles.btnPrimary} disabled={savingEdit}>
                      {savingEdit ? 'Guardando...' : 'Guardar cambios'}
                    </button>
                  </div>
                </form>
              )}

              {/* Historial timeline */}
              <div className={styles.sectionTitle}>
                Historial ({historial.length})
              </div>
              {historial.length === 0 ? (
                <div className={styles.empty}>Sin eventos registrados</div>
              ) : (
                <div className={styles.timeline}>
                  {historial.slice(0, 10).map((h) => (
                    <div key={h.id} className={styles.timelineItem}>
                      <div className={styles.timelineHeader}>
                        <span>{formatDate(h.created_at)}</span>
                        <span>{h.usuario_nombre || (h.usuario_id ? `#${h.usuario_id}` : 'Sistema')}</span>
                      </div>
                      <div className={styles.timelineAction}>
                        {h.accion}
                        {h.estado_anterior && h.estado_nuevo && (
                          <> — <em>{h.estado_anterior}</em> → <strong>{h.estado_nuevo}</strong></>
                        )}
                      </div>
                      {h.motivo && <div className={styles.timelineMotivo}>"{h.motivo}"</div>}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
        <div className="modal-footer-tesla">
          {canEdit && !editing && (
            <button type="button" className={styles.btnPrimary} onClick={() => setEditing(true)}>
              <Edit3 size={14} /> Editar
            </button>
          )}
          <button type="button" className={styles.btnSecondary} onClick={onClose} disabled={savingEdit}>
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}
