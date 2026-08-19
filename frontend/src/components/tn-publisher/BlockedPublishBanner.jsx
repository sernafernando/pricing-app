/**
 * BlockedPublishBanner — the D3/D13/UI4 blocked-publish surface (PR-9
 * design item e), moved from a buried 12.5px paragraph mid-form into the
 * right pane's own block. Three DISTINCT reads, same testids as before
 * (`blocked-banner-error` / `-missing` / `-backend`) so the D13 schema/
 * extraction error never gets confused with a genuinely-absent measurement
 * an operator could fix here:
 *
 * - `error` (red): `publish_fields_error` — a report-78 shape break. Not
 *   something the operator can resolve by typing a value.
 * - `missing`: the operator-fixable case — weight/width/height/depth are
 *   genuinely empty. Offers the two real paths to unblock: apply the
 *   suggested profile, or type the value by hand.
 * - `backend`: the backend's own D3 gate rejected the row for a reason that
 *   isn't a measurement at all (e.g. unresolvable USD cost) — named as-is,
 *   `backendReasons` is the authoritative copy.
 */
import { AlertTriangle, Copy } from 'lucide-react';
import { MEASUREMENT_FIELDS } from './hooks/useDraftFields';
import shellStyles from './TnPublisherShell.module.css';
import styles from './TnPublishModal.module.css';

const MEASUREMENT_LABELS = {
  weight: 'Peso (kg)',
  width: 'Ancho (cm)',
  height: 'Alto (cm)',
  depth: 'Profundidad (cm)',
};

function focusField(name) {
  document.getElementById(`tn-publish-${name}`)?.focus();
}

export default function BlockedPublishBanner({
  publishFieldsError,
  missingFields,
  backendReasons = [],
  suggestedProfile,
  onApplyProfile,
}) {
  if (publishFieldsError) {
    return (
      <div className={styles.blockedBannerRed} data-testid="blocked-banner-error">
        <p className={styles.blockedTitle}>
          <AlertTriangle size={15} aria-hidden="true" /> El reporte GBP cambió de forma
        </p>
        <p className={styles.fieldError}>
          Error de esquema/extracción en los datos del reporte — contactá a un administrador.
        </p>
        <p className={styles.blockedExplain}>
          Esta columna del reporte 78 no tiene la forma esperada — no es algo que puedas cargar acá.
        </p>
        <code className={styles.blockedChip}>{publishFieldsError}</code>
        <button
          type="button"
          className="btn-tesla ghost sm"
          onClick={() => navigator.clipboard?.writeText(publishFieldsError)}
        >
          <Copy size={13} aria-hidden="true" /> Copiar detalle para el administrador
        </button>
      </div>
    );
  }

  if (missingFields.length > 0) {
    return (
      <div className={styles.blockedBannerAmber} data-testid="blocked-banner-missing">
        <p className={styles.blockedTitle}>
          <AlertTriangle size={15} aria-hidden="true" /> Faltan medidas para poder publicar
        </p>
        <p className={styles.blockedExplain}>
          Tienda Nube rechaza una publicación sin medidas, y el reporte GBP no las trae para este producto. Elegí
          un perfil de medidas o completá los valores manualmente para poder publicar.
        </p>
        <p className={styles.blockedStepsLabel}>Dos formas de resolverlo:</p>
        <ol className={styles.blockedOptions}>
          <li className={styles.blockedOption}>
            <div>
              <p className={styles.blockedOptionTitle}>1. Aplicar el perfil sugerido</p>
              {suggestedProfile ? (
                <p className={styles.fieldHint}>
                  {suggestedProfile.name} ({suggestedProfile.weight}×{suggestedProfile.width}×
                  {suggestedProfile.height}) — usado en {suggestedProfile.total_categorias_afectadas ?? 0} categorías
                </p>
              ) : (
                <p className={styles.fieldHint}>No hay un perfil sugerido para esta categoría.</p>
              )}
            </div>
            <button
              type="button"
              className="btn-tesla outline-subtle-success sm"
              disabled={!suggestedProfile}
              onClick={() => suggestedProfile && onApplyProfile(suggestedProfile)}
            >
              Aplicar
            </button>
          </li>
          <li className={styles.blockedOption}>
            <div>
              <p className={styles.blockedOptionTitle}>2. Cargar el valor a mano</p>
              <p className={styles.fieldHint}>Queda guardado para las próximas publicaciones de este EAN.</p>
            </div>
            <button type="button" className="btn-tesla ghost sm" onClick={() => focusField('weight')}>
              Ir al campo
            </button>
          </li>
        </ol>
        <ul className={styles.blockedMeasurementList}>
          {MEASUREMENT_FIELDS.map((name) => (
            <li
              key={name}
              className={missingFields.includes(name) ? styles.blockedMeasurementMissing : styles.blockedMeasurementOk}
            >
              {MEASUREMENT_LABELS[name]}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  if (backendReasons.length > 0) {
    return (
      <div className={styles.blockedBannerAmber} data-testid="blocked-banner-backend">
        <p className={styles.blockedTitle}>
          <AlertTriangle size={15} aria-hidden="true" /> No se puede publicar
        </p>
        <p className={shellStyles.summaryLabel}>No se puede publicar: {backendReasons.join('; ')}.</p>
      </div>
    );
  }

  return null;
}
