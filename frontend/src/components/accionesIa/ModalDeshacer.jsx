import { useState } from 'react';
import { createPortal } from 'react-dom';
import { accionesIaAPI } from '../../services/api';
import AntesDespues from './AntesDespues';
import { etiquetaAccion, etiquetaResultado, formatearHora } from './formato';
import styles from './ModalDeshacer.module.css';

const MOTIVO_MAX = 500;

function mensajeError(err) {
  const status = err?.response?.status;
  const detail = err?.response?.data?.detail;
  const textoDetalle = typeof detail === 'string' && detail ? ` (${detail})` : '';
  if (status === 409) return `El plan venció o ya se usó${textoDetalle}. Prepará uno nuevo.`;
  if (status === 503) return 'La escritura de la IA está apagada (kill switch): no se puede deshacer ahora.';
  if (status === 403) return 'No tenés permiso para deshacer acciones de la IA (mcp.escribir).';
  if (status === 422 && textoDetalle) return `Revisá los datos${textoDetalle}.`;
  return 'No se pudo completar. Probá de nuevo en unos minutos.';
}

/**
 * Undo of AI actions, same guards as any write: ask a motivo, prepare the plan
 * (rows "lista" or "bloqueada" with the reason), confirm with the single-use
 * token, show the per-row results. `objetivo` is `{ accion_ids: [...] }` or
 * `{ plan_id }`; `onAplicado` runs after a confirmed undo (to refresh the list).
 * Closes only with the X or Cancelar/Cerrar (never by clicking outside).
 */
export default function ModalDeshacer({ objetivo, titulo, onClose, onAplicado }) {
  const [motivo, setMotivo] = useState('');
  const [plan, setPlan] = useState(null);
  const [resultados, setResultados] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null);

  const preparar = async () => {
    setEnviando(true);
    setError(null);
    try {
      const { data } = await accionesIaAPI.planDeshacer({ ...objetivo, motivo: motivo.trim() });
      setPlan(data);
    } catch (err) {
      setError(mensajeError(err));
    } finally {
      setEnviando(false);
    }
  };

  const confirmar = async () => {
    setEnviando(true);
    setError(null);
    try {
      const { data } = await accionesIaAPI.aplicarDeshacer(plan.plan_id, plan.confirm_token);
      setResultados(data.resultados || []);
      onAplicado?.();
    } catch (err) {
      setError(mensajeError(err));
      // A used or expired token cannot be retried: back to the motivo step to prepare a new plan.
      if (err?.response?.status === 409) setPlan(null);
    } finally {
      setEnviando(false);
    }
  };

  const filas = plan?.filas || [];
  const listas = filas.filter((f) => f.estado === 'lista').length;
  const filaPorAccion = new Map(filas.map((f) => [f.accion_id, f]));
  const paso = resultados ? 'resultados' : plan ? 'plan' : 'motivo';

  const contenido = (
    <div className="modal-overlay-tesla">
      <div className="modal-tesla lg" role="dialog" aria-modal="true" aria-labelledby="modal-deshacer-titulo">
        <div className="modal-header-tesla">
          <h2 id="modal-deshacer-titulo" className="modal-title-tesla">
            {titulo}
          </h2>
          <button type="button" className="btn-close-tesla" onClick={onClose} aria-label="Cerrar">
            ×
          </button>
        </div>

        <div className={`modal-body-tesla ${styles.cuerpo}`}>
          {paso === 'motivo' && (
            <label className={styles.campo}>
              <span className={styles.etiqueta}>Motivo</span>
              <textarea
                className={styles.motivo}
                value={motivo}
                maxLength={MOTIVO_MAX}
                rows={3}
                placeholder="Por qué se deshace (queda en el registro)"
                onChange={(e) => setMotivo(e.target.value)}
              />
            </label>
          )}

          {paso === 'plan' && (
            <>
              <p className={styles.resumen}>
                {listas > 0
                  ? `${listas} de ${filas.length} filas se van a deshacer. Las bloqueadas no se tocan.`
                  : 'Ninguna fila se puede deshacer.'}
                {plan.expires_at && ` El plan vence a las ${formatearHora(plan.expires_at)}.`}
              </p>
              <div className={styles.tabla}>
                <table className="table-tesla">
                  <thead className="table-tesla-head">
                    <tr>
                      <th>Objetivo</th>
                      <th>Acción</th>
                      <th>Cambio</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody className="table-tesla-body">
                    {filas.map((f) => (
                      <tr key={f.accion_id}>
                        <td>{f.objetivo_label || f.objetivo}</td>
                        <td>{etiquetaAccion(f.accion)}</td>
                        <td>
                          <AntesDespues antes={f.antes} despues={f.despues} />
                        </td>
                        <td>
                          <span className={f.estado === 'lista' ? styles.lista : styles.bloqueada}>
                            {f.estado === 'lista' ? 'Lista' : 'Bloqueada'}
                          </span>
                          {f.detalle && <span className={styles.detalle}>{f.detalle}</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {paso === 'resultados' && (
            <div className={styles.tabla}>
              <table className="table-tesla">
                <thead className="table-tesla-head">
                  <tr>
                    <th>Objetivo</th>
                    <th>Resultado</th>
                    <th>Detalle</th>
                  </tr>
                </thead>
                <tbody className="table-tesla-body">
                  {resultados.map((r) => {
                    const fila = filaPorAccion.get(r.accion_id);
                    return (
                      <tr key={r.accion_id}>
                        <td>{fila?.objetivo_label || fila?.objetivo || `Acción #${r.accion_id}`}</td>
                        <td>
                          <span className={r.resultado === 'ok' ? styles.lista : styles.bloqueada}>
                            {etiquetaResultado(r.resultado)}
                          </span>
                        </td>
                        <td>
                          {r.detalle}
                          {r.nueva_accion_id && <span className={styles.detalle}>Acción nueva #{r.nueva_accion_id}</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {error && (
            <div className={styles.error} role="alert">
              {error}
            </div>
          )}
        </div>

        <div className="modal-footer-tesla">
          {paso === 'resultados' ? (
            <button type="button" className="btn-tesla ghost sm" onClick={onClose}>
              Cerrar
            </button>
          ) : (
            <>
              <button type="button" className="btn-tesla ghost sm" onClick={onClose} disabled={enviando}>
                Cancelar
              </button>
              {paso === 'motivo' && (
                <button
                  type="button"
                  className="btn-tesla outline-subtle-primary sm"
                  disabled={enviando || !motivo.trim()}
                  onClick={preparar}
                >
                  Preparar
                </button>
              )}
              {paso === 'plan' && listas > 0 && (
                <button type="button" className="btn-tesla outline-subtle-danger sm" disabled={enviando} onClick={confirmar}>
                  Confirmar
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );

  return createPortal(contenido, document.body);
}
