/**
 * MeasurementSection — "Medidas" card (PR-9 design item b): a tinted
 * sub-block for the D11 preselect-not-apply profile confirm flow, then the
 * 4-column measurement grid (weight/width/height/depth, UI1). The D3/UI4
 * blocked-publish banner moved to `RightSummaryPane`/`BlockedPublishBanner`
 * (design item e) — this card only owns the controls, never the block
 * copy, so D13 vs. genuinely-absent stays a single source of truth there.
 */
import shellStyles from './TnPublisherShell.module.css';
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
  categoria,
}) {
  return (
    <div className={shellStyles.card} data-testid="tn-publish-field-measurements">
      <div className={shellStyles.cardHeaderRow}>
        <h3 className={shellStyles.cardTitle} style={{ margin: 0 }}>
          Medidas
        </h3>
        <span className={shellStyles.cardHeaderHint}>Del reporte GBP · editable</span>
      </div>

      {loadingProfiles && <p className={styles.fieldHint}>Cargando perfiles de medidas...</p>}
      {profileError && <p className={styles.fieldError}>{profileError}</p>}

      {!loadingProfiles && profiles.length > 0 && (
        <div className={styles.subSectionTinted}>
          <label className={styles.searchLabel} htmlFor="tn-publish-profile">
            Perfil de medidas sugerido{categoria ? ` para "${categoria}"` : ''}
          </label>
          <div className={styles.profileRow}>
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
        </div>
      )}

      <div className={shellStyles.grid4} data-testid="tn-publish-measurements-grid">
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
