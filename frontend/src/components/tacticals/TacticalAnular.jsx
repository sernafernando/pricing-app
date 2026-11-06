/**
 * TacticalAnular — "¿Anular <tactical>?" from a Tacticals row's actions menu (tacticals vista única, S2b). It says what
 * voiding reverses, in the words the old Sell in / Sell out tabs used, takes an optional reason (it goes to the audit
 * rows) and voids the tactical with every child (`POST /tacticals/{id}/anular`). The server's refusal shows inside.
 * Same focus handling as the other Sell in / Sell out dialogs; Escape cancels, except while the void is on its way.
 */
import { useState } from 'react';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import { useFocoAtrapado } from '../sellOut/useFocoAtrapado';
import styles from './TacticalEditar.module.css';

/** What voiding reverses, per kind (the old campaign / bonus / purchase texts). */
const REVIERTE = {
  sell_out: 'Sus campañas dejan de acreditar y se recalculan las ventas que alcanzaban.',
  sell_in:
    'Sus bonos dejan de aplicarse y se anulan las compras que generaron: las ventas que tomaban pasan a las compras siguientes.',
};
const MOTIVO_MAX = 500;

export default function TacticalAnular({ tactical, onCerrar, onAnulado }) {
  const foco = useFocoAtrapado();
  const [motivo, setMotivo] = useState('');
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const titulo = `tactical-anular-${tactical.id}`;

  const anular = async () => {
    setEnviando(true);
    setError(null);
    try {
      await tacticalsAPI.anular(tactical.id, motivo.trim() || null);
      onAnulado();
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudo anular el tactical.'));
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
        <h3 id={titulo}>¿Anular {tactical.nombre}?</h3>
        <p className={styles.ayuda}>
          {REVIERTE[tactical.tipo]} Esta acción no se puede deshacer.
        </p>
        <label className={styles.campo}>
          <span>Motivo (opcional)</span>
          <textarea
            data-foco-inicial
            className={styles.control}
            rows={2}
            maxLength={MOTIVO_MAX}
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
          />
        </label>
        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}
        <div className={styles.dlgRow}>
          <button type="button" className={styles.ghost} onClick={onCerrar} disabled={enviando}>
            Cancelar
          </button>
          <button type="button" className={styles.danger} onClick={anular} disabled={enviando}>
            {enviando ? 'Anulando…' : 'Anular tactical'}
          </button>
        </div>
      </div>
    </div>
  );
}
