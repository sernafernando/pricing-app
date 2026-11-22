/**
 * AprobacionCarga — the approval box of a bonus, purchase or campaign panel while the record is `pendiente`
 * (tacticals approval S6, S8): a pending load applies to nothing until it is approved. A record loaded on its own is
 * approved here (`onAprobar`, after a confirmation) by a user with `tacticals.aprobar`; a tactical's line is approved
 * with its tactical, from the Tacticals list. Nothing shows for an approved or voided record.
 */
import { useState } from 'react';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import styles from './AprobacionCarga.module.css';

export default function AprobacionCarga({ estado, tacticalId = null, puedeAprobar = false, onAprobar }) {
  const [confirmando, setConfirmando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null);
  if (estado !== 'pendiente') return null;
  const suelta = tacticalId == null;

  const aprobar = async () => {
    setEnviando(true);
    setError(null);
    try {
      await onAprobar();
      setConfirmando(false);
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudo aprobar.'));
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className={styles.caja}>
      <p role="note">
        Pendiente de aprobación: no aplica hasta que lo aprueben.{!suelta && ' Se aprueba desde su tactical.'}
      </p>
      {suelta && puedeAprobar && !confirmando && (
        <div className={styles.acciones}>
          <button type="button" className={styles.primary} onClick={() => setConfirmando(true)}>
            Aprobar
          </button>
        </div>
      )}
      {suelta && puedeAprobar && confirmando && (
        <>
          <p>¿Aprobarlo? Empieza a aplicar desde ahora.</p>
          <div className={styles.acciones}>
            <button type="button" className={styles.ghost} onClick={() => setConfirmando(false)} disabled={enviando}>
              Cancelar
            </button>
            <button type="button" className={styles.primary} onClick={aprobar} disabled={enviando}>
              {enviando ? 'Aprobando…' : 'Confirmar aprobación'}
            </button>
          </div>
        </>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
