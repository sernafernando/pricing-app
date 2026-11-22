/**
 * AvisoAprobacion — what approval means on the tactical form (tacticals approval S2, S4, S8): a new tactical waits
 * for approval before applying; an approved one goes back to pending when its money changes; a pending one stays
 * pending. Nothing for a voided tactical, or while the tactical to edit is still loading. `de="offset"` words it
 * for a profit offset (the offsets screen).
 */
import styles from './AvisoAprobacion.module.css';

export const TEXTO_NUEVO = 'Al crearlo queda pendiente de aprobación: no aplica a ninguna venta hasta que lo aprueben.';
export const TEXTO_APROBADO =
  'Está aprobado: si cambiás montos, topes, fechas o alcance vuelve a quedar pendiente de aprobación y deja de aplicar hasta que lo aprueben de nuevo. El nombre y la nota no.';
export const TEXTO_PENDIENTE = 'Sigue pendiente de aprobación: no aplica hasta que lo aprueben.';

const TEXTOS_TACTICAL = { nuevo: TEXTO_NUEVO, aprobado: TEXTO_APROBADO, pendiente: TEXTO_PENDIENTE, aprobadoEstado: 'activo' };

/** The same notice on the profit offsets screen (S10): an offset's approved state is `activa`. */
const TEXTOS_OFFSET = {
  nuevo: 'Al crearlo queda pendiente de aprobación: no aplica a la rentabilidad ni consume topes hasta que lo aprueben.',
  aprobado:
    'Está aprobado: si cambiás monto, porcentaje, fechas, topes, canales o alcance vuelve a quedar pendiente de aprobación y deja de aplicar hasta que lo aprueben de nuevo. La descripción no.',
  pendiente: TEXTO_PENDIENTE,
  aprobadoEstado: 'activa',
};

export default function AvisoAprobacion({ editando, estado, de = 'tactical' }) {
  const textos = de === 'offset' ? TEXTOS_OFFSET : TEXTOS_TACTICAL;
  const texto = !editando
    ? textos.nuevo
    : estado === textos.aprobadoEstado
      ? textos.aprobado
      : estado === 'pendiente'
        ? textos.pendiente
        : null;
  if (!texto) return null;
  return (
    <p className={styles.aviso} role="note">
      {texto}
    </p>
  );
}
