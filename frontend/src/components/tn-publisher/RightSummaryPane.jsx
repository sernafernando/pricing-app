/**
 * RightSummaryPane — the sticky right pane (PR-9 design item d): the "Qué
 * se va a publicar" summary card (each row's source line is read off the
 * `source` the draft already carries — `gbp`/`override`/`empty`, plus the
 * in-session `dirtyMeasurements` set for "editado por vos" — never
 * invented), the Precio final row, the publish button, and the two-step
 * Confirmar/Cancelar (moved here from the bottom of the scroll). Renders
 * `BlockedPublishBanner` above the button when publishing is blocked.
 */
import BlockedPublishBanner from './BlockedPublishBanner';
import { formatMoney } from '../../utils/formatMoney';
import shellStyles from './TnPublisherShell.module.css';
import styles from './TnPublishModal.module.css';

const MEASUREMENT_LABELS = {
  weight: 'Peso',
  width: 'Ancho',
  height: 'Alto',
  depth: 'Profundidad',
};

function measurementSourceLabel(name, draftFields, publishDraftFields) {
  if ((draftFields.dirtyMeasurements || []).includes(name)) return 'editado por vos';
  const source = publishDraftFields?.[name]?.source;
  if (source === 'gbp') return 'del reporte GBP';
  if (source === 'override') return 'guardado anteriormente';
  return null;
}

export default function RightSummaryPane({
  selectedCategory,
  draftFields,
  publishDraftFields,
  monedaCosto,
  finalPrice,
  measurementsBlocked,
  publishFieldsError,
  missingMeasurementFields,
  backendReasons,
  suggestedProfile,
  onApplyProfile,
  canPublish,
  confirming,
  submitting,
  onPublishClick,
  onConfirm,
  onCancelConfirm,
}) {
  const measurementsSummary = ['weight', 'width', 'height', 'depth']
    .map((name) => draftFields[name])
    .every((v) => v !== '' && v != null)
    ? `${draftFields.width} × ${draftFields.height} × ${draftFields.depth} cm`
    : '—';

  return (
    <>
      <div className={shellStyles.card}>
        <h3 className={shellStyles.cardTitle}>Qué se va a publicar</h3>
        <dl className={shellStyles.summaryList}>
          <div className={shellStyles.summaryRow}>
            <dt className={shellStyles.summaryLabel}>Categoría</dt>
            <dd className={shellStyles.summaryValueBlock}>
              <p className={shellStyles.summaryValue}>{selectedCategory?.path || '—'}</p>
            </dd>
          </div>
          <div className={shellStyles.summaryRow}>
            <dt className={shellStyles.summaryLabel}>Medidas</dt>
            <dd className={shellStyles.summaryValueBlock}>
              <p className={shellStyles.summaryValue}>{measurementsSummary}</p>
              {measurementSourceLabel('width', draftFields, publishDraftFields) && (
                <p className={shellStyles.summarySource}>
                  {measurementSourceLabel('width', draftFields, publishDraftFields)}
                </p>
              )}
            </dd>
          </div>
          <div className={shellStyles.summaryRow}>
            <dt className={shellStyles.summaryLabel}>Peso</dt>
            <dd className={shellStyles.summaryValueBlock}>
              <p className={shellStyles.summaryValue}>
                {draftFields.weight !== '' && draftFields.weight != null ? `${draftFields.weight} kg` : '—'}
              </p>
              {measurementSourceLabel('weight', draftFields, publishDraftFields) && (
                <p className={shellStyles.summarySource}>
                  {measurementSourceLabel('weight', draftFields, publishDraftFields)}
                </p>
              )}
            </dd>
          </div>
          <div className={shellStyles.summaryRow}>
            <dt className={shellStyles.summaryLabel}>Stock</dt>
            <dd className={shellStyles.summaryValueBlock}>
              <p className={shellStyles.summaryValue}>{draftFields.stock !== '' ? draftFields.stock : '—'}</p>
            </dd>
          </div>
          <div className={shellStyles.summaryRow}>
            <dt className={shellStyles.summaryLabel}>Costo</dt>
            <dd className={shellStyles.summaryValueBlock}>
              <p className={shellStyles.summaryValue}>
                {draftFields.cost !== '' ? (formatMoney(draftFields.cost) ?? draftFields.cost) : '—'}
              </p>
              {monedaCosto && <p className={shellStyles.summarySource}>{monedaCosto}</p>}
            </dd>
          </div>
          <div className={shellStyles.summaryRow}>
            <dt className={shellStyles.summaryLabel}>Visibilidad</dt>
            <dd className={shellStyles.summaryValueBlock}>
              <p className={shellStyles.summaryValue}>{draftFields.visibility}</p>
            </dd>
          </div>
        </dl>
        <div className={shellStyles.finalPriceRow}>
          <span className={shellStyles.finalPriceLabel}>Precio final</span>
          <span className={shellStyles.finalPriceValue}>{finalPrice != null ? formatMoney(finalPrice) : '—'}</span>
        </div>
      </div>

      {measurementsBlocked && (
        <BlockedPublishBanner
          publishFieldsError={publishFieldsError}
          missingFields={missingMeasurementFields}
          backendReasons={backendReasons}
          suggestedProfile={suggestedProfile}
          onApplyProfile={onApplyProfile}
        />
      )}

      {confirming ? (
        <div className={styles.confirmBar}>
          <span className={styles.confirmQuestion}>¿Publicar este producto en Tienda Nube?</span>
          <button
            type="button"
            className="btn-tesla outline-subtle-success sm"
            disabled={submitting}
            onClick={onConfirm}
          >
            Confirmar
          </button>
          <button type="button" className="btn-tesla ghost sm" disabled={submitting} onClick={onCancelConfirm}>
            Cancelar
          </button>
        </div>
      ) : (
        <>
          <button
            type="button"
            className={`btn-tesla primary ${styles.publishButtonFull}`}
            disabled={!canPublish}
            onClick={onPublishClick}
          >
            Publicar
          </button>
          {measurementsBlocked ? (
            <p className={styles.blockedPublishHint}>Resolvé el peso para habilitar la publicación.</p>
          ) : (
            <p className={shellStyles.publishHint}>Vas a poder revisar antes de confirmar.</p>
          )}
        </>
      )}
    </>
  );
}
