import { useState, useEffect, useCallback } from 'react';
import { Check, X as XIcon } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { ticketsAPI, propuestasAPI } from '../services/api';
import styles from './TicketProposals.module.css';

const CAMPO_LABEL = {
  severidad: 'Severidad',
  urgencia: 'Urgencia',
  titulo: 'Título',
  resumen: 'Resumen',
};

/**
 * Pending AI-triage proposals for one ticket (tickets-ai-triage PR 4c).
 * Confidence is always visible, independent of permission — only the
 * confirm/discard/batch controls require `tickets.triage.confirmar`. Batch
 * confirm always sends exactly ONE request with every selected id.
 */
export default function TicketProposals({ ticketId, onChanged, refreshToken }) {
  const { tienePermiso } = usePermisos();
  const puedeConfirmar = tienePermiso('tickets.triage.confirmar');

  const [propuestas, setPropuestas] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [busyId, setBusyId] = useState(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [error, setError] = useState(null);

  const fetchPropuestas = useCallback(async () => {
    try {
      const { data } = await ticketsAPI.listarPropuestas(ticketId);
      setPropuestas(Array.isArray(data) ? data : []);
    } catch {
      setPropuestas([]);
    }
  }, [ticketId]);

  useEffect(() => {
    fetchPropuestas();
    // refreshToken is an external re-fetch trigger (fix/tickets-triage-
    // backfill) — bumping it forces this effect to rerun even when
    // ticketId/fetchPropuestas are unchanged.
  }, [fetchPropuestas, refreshToken]);

  const toggleSelected = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleConfirmar = async (id) => {
    setBusyId(id);
    setError(null);
    try {
      await propuestasAPI.confirmar(id);
      await fetchPropuestas();
      onChanged?.();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al confirmar la propuesta');
    } finally {
      setBusyId(null);
    }
  };

  const handleDescartar = async (id) => {
    setBusyId(id);
    setError(null);
    try {
      await propuestasAPI.descartar(id);
      await fetchPropuestas();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al descartar la propuesta');
    } finally {
      setBusyId(null);
    }
  };

  const handleConfirmarSeleccionadas = async () => {
    setBatchBusy(true);
    setError(null);
    try {
      await propuestasAPI.confirmarBatch(Array.from(selected));
      setSelected(new Set());
      await fetchPropuestas();
      onChanged?.();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al confirmar las propuestas seleccionadas');
    } finally {
      setBatchBusy(false);
    }
  };

  if (propuestas.length === 0) return null;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.title}>Propuestas de IA pendientes</span>
        {puedeConfirmar && selected.size > 0 && (
          <button className={styles.btnBatch} onClick={handleConfirmarSeleccionadas} disabled={batchBusy}>
            <Check size={13} />
            {batchBusy ? 'Confirmando...' : `Confirmar seleccionadas (${selected.size})`}
          </button>
        )}
      </div>

      {error && <div className={styles.inlineError}>{error}</div>}

      <ul className={styles.list}>
        {propuestas.map((p) => {
          const label = CAMPO_LABEL[p.campo] || p.campo;
          return (
            <li key={p.id} className={styles.item}>
              {puedeConfirmar && (
                <input
                  type="checkbox"
                  className={styles.checkbox}
                  checked={selected.has(p.id)}
                  onChange={() => toggleSelected(p.id)}
                  aria-label={`Seleccionar propuesta ${label}`}
                />
              )}
              <span className={styles.label}>
                {label}: {String(p.valor_propuesto?.valor ?? '-')}
                {typeof p.confianza === 'number' && (
                  <span className={styles.confianza}> · IA {p.confianza.toFixed(2)}</span>
                )}
              </span>
              {puedeConfirmar && (
                <span className={styles.actions}>
                  <button
                    className={styles.btnConfirm}
                    onClick={() => handleConfirmar(p.id)}
                    disabled={busyId === p.id}
                    aria-label={`Confirmar ${label}`}
                  >
                    <Check size={13} />
                  </button>
                  <button
                    className={styles.btnDiscard}
                    onClick={() => handleDescartar(p.id)}
                    disabled={busyId === p.id}
                    aria-label={`Descartar ${label}`}
                  >
                    <XIcon size={13} />
                  </button>
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
