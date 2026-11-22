/**
 * AvisoAprobacion — what approval means on the tactical form (tacticals approval S2, S4, S8): a new tactical waits
 * for approval before applying; an approved one goes back to pending when its money changes; a pending one stays
 * pending. Nothing for a voided tactical, or while the tactical to edit is still loading.
 */
import styles from './AvisoAprobacion.module.css';

export const TEXTO_NUEVO = 'Al crearlo queda pendiente de aprobación: no aplica a ninguna venta hasta que lo aprueben.';
export const TEXTO_APROBADO =
  'Está aprobado: si cambiás montos, topes, fechas o alcance vuelve a quedar pendiente de aprobación y deja de aplicar hasta que lo aprueben de nuevo. El nombre y la nota no.';
export const TEXTO_PENDIENTE = 'Sigue pendiente de aprobación: no aplica hasta que lo aprueben.';

export default function AvisoAprobacion({ editando, estado }) {
  const texto = !editando
    ? TEXTO_NUEVO
    : estado === 'activo'
      ? TEXTO_APROBADO
      : estado === 'pendiente'
        ? TEXTO_PENDIENTE
        : null;
  if (!texto) return null;
  return (
    <p className={styles.aviso} role="note">
      {texto}
    </p>
  );
}
