/**
 * OffsetAprobar — "¿Aprobar <offset>?" from a pending legacy profit offset of the approval inbox (tacticals approval
 * S10, S11). An offset has no record panel to approve it from, so the inbox asks here: approving makes it apply to
 * rentabilidad from now on (`POST /offsets-ganancia/{id}/aprobar`), and the approver is recorded. The server's refusal
 * shows inside. Same focus handling as TacticalAprobar; Escape cancels, except while the approval is on its way.
 */
import { useState } from 'react';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import { useFocoAtrapado } from '../sellOut/useFocoAtrapado';
import styles from './tacticalDialogos.module.css';

export default function OffsetAprobar({ offset, onCerrar, onAprobado }) {
  const foco = useFocoAtrapado();
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const titulo = `offset-aprobar-${offset.id}`;

  const aprobar = async () => {
    setEnviando(true);
    setError(null);
    try {
      await tacticalsAPI.aprobarOffset(offset.id);
      onAprobado();
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudo aprobar el offset.'));
      setEnviando(false);
    }
  };

  return (
    <div className={styles.overlay}>
      <div
        ref={foco.ref}
        className={styles.dlg}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titulo}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            if (!enviando) onCerrar();
          } else foco.onKeyDown(e);
        }}
      >
        <h3 id={titulo}>¿Aprobar {offset.nombre}?</h3>
        <p className={styles.ayuda}>
          Empieza a aplicar en la rentabilidad desde ahora, dentro de sus fechas. Queda registrado quién lo aprobó.
        </p>
        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}
        <div className={styles.dlgRow}>
          <button type="button" className={styles.ghost} onClick={onCerrar} disabled={enviando}>
            Cancelar
          </button>
          <button type="button" data-foco-inicial className={styles.primary} onClick={aprobar} disabled={enviando}>
            {enviando ? 'Aprobando…' : 'Aprobar offset'}
          </button>
        </div>
      </div>
    </div>
  );
}
