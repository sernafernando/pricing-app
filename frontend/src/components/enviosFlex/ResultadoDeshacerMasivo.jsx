import { CheckCircle2, AlertTriangle } from 'lucide-react';
import styles from './DeshacerMasivo.module.css';

// Neutral chip with a dot in the logística's own color (gray when unassigned).
export function LogisticaChip({ logistica }) {
  return (
    <span className={styles.chip}>
      <span
        className={styles.dot}
        style={logistica?.color ? { background: logistica.color } : undefined}
        aria-hidden="true"
      />
      {logistica?.nombre || 'Sin asignar'}
    </span>
  );
}

// What a mass undo did: how many labels went back and, grouped by reason, which ones did not.
export default function ResultadoDeshacerMasivo({ resultado }) {
  const { revertidas, no_revertidas: noRevertidas, no_revertidas_por_motivo: motivos } = resultado;
  return (
    <div className={styles.resultado} role="status">
      <div className={revertidas > 0 ? styles.resumenOk : styles.resumenAviso}>
        <CheckCircle2 size={16} aria-hidden="true" />
        {revertidas === 1
          ? '1 volvió a su logística anterior.'
          : `${revertidas} volvieron a su logística anterior.`}
      </div>
      {noRevertidas > 0 && (
        <>
          <div className={styles.resumenAviso}>
            <AlertTriangle size={16} aria-hidden="true" />
            {noRevertidas === 1
              ? '1 no se pudo deshacer:'
              : `${noRevertidas} no se pudieron deshacer:`}
          </div>
          <ul className={styles.motivos}>
            {motivos.map((m) => (
              <li key={m.motivo} className={styles.motivo}>
                <span>{m.motivo}</span>
                <div className={styles.envios}>
                  {m.shipping_ids.map((id) => (
                    <span key={id} className={styles.envio}>
                      {id}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
