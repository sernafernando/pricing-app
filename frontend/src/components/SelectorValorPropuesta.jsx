import styles from './SelectorValorPropuesta.module.css';

/**
 * Closed-vocabulary value selector shown on confirm for `severidad`/
 * `urgencia` proposals only (tickets-triage-feedback PR2) — the two fields
 * PR1's backend `confirmacion_service._resolver_correccion` accepts a
 * corrected value for (`CAMPOS_CORREGIBLES`,
 * `backend/app/tickets/services/vocabularios.py`).
 *
 * A THIRD copy of the vocabulary, unavoidable across the wire: the backend
 * already carries two (the `VOCABULARIOS` dict and the `TriagePropuesta`
 * `Literal` annotations, kept honest there by a drift-guard test). This one
 * has no such guard — if the backend vocabulary ever changes, this object
 * must be updated too, or a valid correction is rejected with a 400 the
 * user can't explain from the selector alone.
 */
const VOCABULARIOS = {
  severidad: ['trivial', 'menor', 'mayor', 'critica'],
  urgencia: ['baja', 'normal', 'alta', 'inmediata'],
};

// Exported so `TicketProposals` can gate the selector's affordance without
// duplicating the field list a second time.
export const CAMPOS_CORREGIBLES = new Set(Object.keys(VOCABULARIOS));

export default function SelectorValorPropuesta({ campo, valorPropuesto, value, onChange, disabled = false }) {
  const opciones = VOCABULARIOS[campo] || [];
  const seleccionado = value ?? valorPropuesto;
  // Ratification vs correction is decided server-side (spec: never inferred
  // client-side) — this indicator is purely a live preview of what would be
  // sent, not a claim about what the backend will record.
  const fueCorregido = seleccionado != null && seleccionado !== valorPropuesto;

  return (
    <span className={styles.container}>
      <span className={styles.propuesto}>IA propuso: {valorPropuesto}</span>
      <select
        className={styles.select}
        value={seleccionado ?? ''}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        aria-label={`Valor corregido de ${campo}`}
      >
        {opciones.map((opcion) => (
          <option key={opcion} value={opcion}>
            {opcion}
          </option>
        ))}
      </select>
      {fueCorregido && <span className={styles.corregido}>Corregido a: {seleccionado}</span>}
    </span>
  );
}
