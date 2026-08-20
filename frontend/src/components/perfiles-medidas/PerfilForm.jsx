/**
 * PerfilForm — create/edit form body extracted verbatim from
 * `AdministracionPerfilesMedidas.jsx` (structural extraction, PR-6 pattern).
 */
import styles from '../../pages/AdministracionPerfilesMedidas.module.css';
import { AlertTriangle, Info } from 'lucide-react';
import { MEASUREMENT_FIELDS } from './perfilesMedidasHelpers';

export default function PerfilForm({ formId, form, setForm, errors, touched, setTouched, formError, onSubmit }) {
  return (
    <form id={formId} onSubmit={onSubmit}>
      {formError && (
        <div className={styles.alertError}>
          <AlertTriangle size={16} /> {formError}
        </div>
      )}
      <div className={styles.formGroup}>
        <label className={styles.formLabel} htmlFor="perfil-nombre">
          Nombre
        </label>
        <input
          id="perfil-nombre"
          className={styles.formInput}
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          autoFocus
        />
        <span className={styles.formHint}>
          Poné las medidas en el nombre: es lo único que vas a ver al elegir el perfil desde el publicador.
        </span>
      </div>

      <h3 className={styles.groupHeading}>Medidas de la caja</h3>
      <div className={styles.formGrid}>
        {MEASUREMENT_FIELDS.map(({ key, label, unit }) => (
          <div className={styles.formGroup} key={key}>
            <label className={styles.formLabel} htmlFor={`perfil-${key}`}>
              {label}
            </label>
            <div className={styles.numericFieldWrap}>
              <input
                id={`perfil-${key}`}
                className={`${styles.formInput} ${styles.numericInput}`}
                type="number"
                step="0.01"
                value={form[key]}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                onBlur={() => setTouched(true)}
              />
              <span className={styles.unitSuffix}>{unit}</span>
            </div>
            {touched && errors[key] && <span className={styles.fieldError}>{errors[key]}</span>}
          </div>
        ))}
      </div>

      <div className={styles.infoNote}>
        <Info size={16} />
        <span>
          Editar un perfil no cambia lo ya publicado. Solo afecta las publicaciones que se hagan de acá en
          adelante.
        </span>
      </div>
    </form>
  );
}
