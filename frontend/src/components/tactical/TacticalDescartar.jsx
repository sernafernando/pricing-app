/**
 * TacticalDescartar — "¿Descartar el tactical?". Mounted while open, so the focus starts on "Seguir editando",
 * stays inside on Tab and goes back to what opened it when it closes (`useFocoAtrapado`, as the other dialogs of
 * Sell in / Sell out). Escape keeps editing.
 */
import { useFocoAtrapado } from '../sellOut/useFocoAtrapado';
import styles from './TacticalDescartar.module.css';

export default function TacticalDescartar({ onSeguir, onDescartar }) {
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
        <h3 id="tactical-descartar">¿Descartar el tactical?</h3>
        <p>Se pierden los datos y las líneas que cargaste. Esta acción no se puede deshacer.</p>
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
