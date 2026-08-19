/**
 * VariantFieldsSection — Precio de publicación (Slice 2, money path). Two
 * mutually exclusive bases, always labeled so the operator knows which
 * business quantity is in play — see the pre-decomposition
 * `TnPublishModal.jsx` file header for the full rationale. Moved verbatim;
 * the remaining variant fields (sku, barcode, cost, weight, dimensions,
 * stock…) land in PR-7's UI1.
 */
import { Check } from 'lucide-react';
import styles from './TnPublishModal.module.css';

export default function VariantFieldsSection({
  hasWebPrice,
  basePrice,
  offsetPercent,
  setOffsetPercent,
  loadingOffset,
  offsetError,
  computedPrice,
  manualPrice,
  setManualPrice,
  finalPriceIsValid,
}) {
  return (
    <div className={styles.section}>
      <h3 className={styles.sectionTitle}>Precio de publicación</h3>
      {hasWebPrice ? (
        <>
          <p className={styles.fieldHint}>Base: precio web transferencia (${basePrice.toFixed(2)})</p>
          <label className={styles.searchLabel} htmlFor="tn-publish-offset">
            Recargo (%)
          </label>
          <input
            id="tn-publish-offset"
            type="number"
            className={styles.titleInput}
            value={offsetPercent ?? ''}
            min={0}
            step="0.01"
            disabled={loadingOffset || offsetPercent === null}
            onChange={(e) => setOffsetPercent(e.target.value === '' ? '' : Number(e.target.value))}
          />
          {loadingOffset && <p className={styles.fieldHint}>Cargando recargo configurado...</p>}
          {offsetError && <p className={styles.fieldError}>{offsetError}</p>}
          <p className={styles.selectedCategory}>
            <Check size={13} aria-hidden="true" />
            <span>
              Precio final a publicar: <strong>${computedPrice ?? '—'}</strong>
            </span>
          </p>
        </>
      ) : (
        <>
          <p className={styles.fieldHint}>
            Base: precio lista ML (Clásica) — no hay precio web transferencia para este producto. Editá el
            precio antes de publicar.
          </p>
          <label className={styles.searchLabel} htmlFor="tn-publish-manual-price">
            Precio de publicación
          </label>
          <input
            id="tn-publish-manual-price"
            type="number"
            className={styles.titleInput}
            value={manualPrice}
            min={0}
            step="0.01"
            onChange={(e) => setManualPrice(e.target.value)}
          />
        </>
      )}
      {/* Mientras se carga el recargo el precio todavía no existe: mostrar
          "debe ser mayor a cero" ahí sería ruido, no un error del operador. */}
      {!finalPriceIsValid && !loadingOffset && (
        <p className={styles.fieldError}>El precio de publicación debe ser mayor a cero.</p>
      )}
    </div>
  );
}
