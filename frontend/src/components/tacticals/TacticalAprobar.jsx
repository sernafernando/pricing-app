/**
 * TacticalAprobar — "¿Aprobar <tactical>?" from a pending Tacticals row's actions menu (tacticals approval S3, S8).
 * Approving makes the tactical and all its lines apply from now on (`POST /tacticals/{id}/aprobar`); the approver is
 * recorded. The server's refusal shows inside. Same focus handling as TacticalAnular; Escape cancels, except while the
 * approval is on its way.
 */
import { useState } from 'react';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import { useFocoAtrapado } from '../sellOut/useFocoAtrapado';
import styles from './tacticalDialogos.module.css';

export default function TacticalAprobar({ tactical, onCerrar, onAprobado }) {
  const foco = useFocoAtrapado();
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const titulo = `tactical-aprobar-${tactical.id}`;
  const lineas = tactical.lineas?.length ?? 0;

  const aprobar = async () => {
    setEnviando(true);
    setError(null);
    try {
      await tacticalsAPI.aprobar(tactical.id);
      onAprobado();
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudo aprobar el tactical.'));
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
        <h3 id={titulo}>¿Aprobar {tactical.nombre}?</h3>
        <p className={styles.ayuda}>
          {lineas === 1 ? 'Su línea empieza' : `Sus ${lineas} líneas empiezan`} a aplicar desde ahora, también a lo ya
          vendido dentro de sus fechas. Queda registrado quién lo aprobó.
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
            {enviando ? 'Aprobando…' : 'Aprobar tactical'}
          </button>
        </div>
      </div>
    </div>
  );
}
