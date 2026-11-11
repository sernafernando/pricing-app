/**
 * TacticalDescartar — "¿Descartar el tactical?". Mounted while open, so the focus starts on "Seguir editando",
 * stays inside on Tab and goes back to what opened it when it closes (`useFocoAtrapado`, as the other dialogs of
 * Sell in / Sell out). Escape keeps editing. `edicion` (S8): the changes to an existing tactical are what is lost.
 */
import { useFocoAtrapado } from '../sellOut/useFocoAtrapado';
import styles from './TacticalDescartar.module.css';

export default function TacticalDescartar({ onSeguir, onDescartar, edicion = false }) {
  const foco = useFocoAtrapado();
  return (
    <div className={styles.overlay}>
      <div
        ref={foco.ref}
        className={styles.dlg}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tactical-descartar"
        onKeyDown={(e) => {
          if (e.key === 'Escape') onSeguir();
          else foco.onKeyDown(e);
        }}
      >
        <h3 id="tactical-descartar">{edicion ? '¿Descartar los cambios?' : '¿Descartar el tactical?'}</h3>
        <p>
          {edicion
            ? 'El tactical queda como estaba y se pierden los cambios que hiciste.'
            : 'Se pierden los datos y las líneas que cargaste. Esta acción no se puede deshacer.'}
        </p>
        <div className={styles.dlgRow}>
          <button type="button" className={styles.ghost} data-foco-inicial onClick={onSeguir}>
            Seguir editando
          </button>
          <button type="button" className={styles.danger} onClick={onDescartar}>
            Descartar
          </button>
        </div>
      </div>
    </div>
  );
}
