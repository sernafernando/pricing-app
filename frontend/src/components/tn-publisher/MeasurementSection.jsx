/**
 * MeasurementSection — profile selector (D11 preselect-not-apply confirm
 * flow, UI3) + the four measurement controls (weight/width/height/depth,
 * UI1) + the D3/UI4 blocked-publish banner. Distinguishes a D13
 * schema/extraction error (`publishFieldsError`) from a genuinely-absent
 * measurement — the two MUST read differently so an operator can't mask a
 * systemic report-78 break by hand-typing a value.
 */
import styles from './TnPublishModal.module.css';
import { MEASUREMENT_FIELDS } from './hooks/useDraftFields';

const MEASUREMENT_LABELS = {
  weight: 'Peso (kg)',
  width: 'Ancho (cm)',
  height: 'Alto (cm)',
  depth: 'Profundidad (cm)',
};

export default function MeasurementSection({
  fields,
  setField,
  profiles,
  loadingProfiles,
  profileError,
  selectedProfileId,
  setSelectedProfileId,
  onApplyProfile,
  onClearProfile,
  missingFields,
  backendReasons = [],
  blocked,
  publishFieldsError,
}) {
  return (
    <div className={styles.section} data-testid="tn-publish-field-measurements">
      <h3 className={styles.sectionTitle}>Medidas y perfil</h3>

      {publishFieldsError ? (
        <p className={styles.fieldError} data-testid="blocked-banner-error">
          Error de esquema/extracción en los datos del reporte — contactá a un administrador.
        </p>
      ) : (
        blocked &&
        (missingFields.length > 0 ? (
          <p className={styles.fieldError} data-testid="blocked-banner-missing">
            Faltan medidas: {missingFields.map((f) => MEASUREMENT_LABELS[f]).join(', ')}. Elegí un perfil de medidas
            o completá los valores manualmente para poder publicar.
          </p>
        ) : (
          // Blocked by the backend for something other than a measurement
          // the operator can type here — today that means an unresolvable
          // USD cost. Naming the real reason beats showing an empty
          // "Faltan medidas:" list.
          backendReasons.length > 0 && (
            <p className={styles.fieldError} data-testid="blocked-banner-backend">
              No se puede publicar: {backendReasons.join('; ')}.
            </p>
          )
        ))
      )}

      {loadingProfiles && <p className={styles.fieldHint}>Cargando perfiles de medidas...</p>}
      {profileError && <p className={styles.fieldError}>{profileError}</p>}

      {!loadingProfiles && profiles.length > 0 && (
        <div className={styles.subSection}>
          <label className={styles.searchLabel} htmlFor="tn-publish-profile">
            Perfil de medidas sugerido
          </label>
          <select
            id="tn-publish-profile"
            className={styles.titleInput}
            value={selectedProfileId ?? ''}
            onChange={(e) => setSelectedProfileId(e.target.value === '' ? null : Number(e.target.value))}
          >
            <option value="">Sin perfil</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn-tesla outline-subtle-success sm"
            disabled={selectedProfileId == null}
            onClick={() => onApplyProfile(profiles.find((p) => p.id === selectedProfileId))}
          >
            Aplicar perfil
          </button>
          <button type="button" className="btn-tesla ghost sm" onClick={onClearProfile}>
            Limpiar selección
          </button>
        </div>
      )}

      <div className={styles.measurementsGrid} data-testid="tn-publish-measurements-grid">
        {MEASUREMENT_FIELDS.map((name) => (
          <div key={name} className={styles.subSection} data-testid={`tn-publish-field-${name}`}>
            <label className={styles.sectionTitle} htmlFor={`tn-publish-${name}`}>
              {MEASUREMENT_LABELS[name]}
            </label>
            <input
              id={`tn-publish-${name}`}
              type="number"
              className={`${styles.titleInput} ${styles.numericInput}`}
              value={fields[name]}
              step="0.01"
              min={0}
              onChange={(e) => setField(name, e.target.value)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
