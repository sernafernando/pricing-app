/**
 * VariantFieldsSection — "Precio y stock" card (PR-9 design item b): a
 * 4-column grid (Base / Recargo (%) / Costo / Stock), plus Precio
 * promocional below the grid (not in the brief's 4-column list, but a real
 * editable field the D2 audit still requires a visible control for).
 *
 * Two mutually exclusive price bases, always labeled so the operator knows
 * which business quantity is in play — see the pre-decomposition
 * `TnPublishModal.jsx` file header for the full rationale. The two-base
 * rule and its error copy are unchanged (money path, PR-9 non-goal).
 */
import PublishFieldRow from './PublishFieldRow';
import shellStyles from './TnPublisherShell.module.css';
import styles from './TnPublishModal.module.css';

export default function VariantFieldsSection({
  hasWebPrice,
  basePrice,
  offsetPercent,
  setOffsetPercent,
  loadingOffset,
  offsetError,
  manualPrice,
  setManualPrice,
  finalPriceIsValid,
  cost,
  onCostChange,
  stock,
  onStockChange,
  promotionalPrice,
  onPromotionalPriceChange,
}) {
  return (
    <div className={shellStyles.card} data-testid="tn-publish-field-price">
      <h3 className={shellStyles.cardTitle}>Precio y stock</h3>

      <div className={shellStyles.grid4}>
        <div className={styles.subSection}>
          {hasWebPrice ? (
            <>
              <label className={styles.sectionTitle} htmlFor="tn-publish-base-price">
                Base
              </label>
              <input
                id="tn-publish-base-price"
                type="text"
                className={`${styles.titleInput} ${styles.numericInput}`}
                value={`$${basePrice.toFixed(2)}`}
                readOnly
              />
              <p className={styles.fieldHint}>Base: precio web transferencia (${basePrice.toFixed(2)})</p>
            </>
          ) : (
            <>
              <label className={styles.sectionTitle} htmlFor="tn-publish-manual-price">
                Precio de publicación
              </label>
              <input
                id="tn-publish-manual-price"
                type="number"
                className={`${styles.titleInput} ${styles.numericInput}`}
                value={manualPrice}
                min={0}
                step="0.01"
                onChange={(e) => setManualPrice(e.target.value)}
              />
              <p className={styles.fieldHint}>
                Base: precio lista ML (Clásica) — no hay precio web transferencia para este producto. Editá el
                precio antes de publicar.
              </p>
            </>
          )}
        </div>

        <div className={styles.subSection}>
          <label className={styles.sectionTitle} htmlFor="tn-publish-offset">
            Recargo (%)
          </label>
          <input
            id="tn-publish-offset"
            type="number"
            className={`${styles.titleInput} ${styles.numericInput}`}
            value={offsetPercent ?? ''}
            min={0}
            step="0.01"
            disabled={!hasWebPrice || loadingOffset || offsetPercent === null}
            onChange={(e) => setOffsetPercent(e.target.value === '' ? '' : Number(e.target.value))}
          />
          {loadingOffset && <p className={styles.fieldHint}>Cargando...</p>}
          {offsetError && <p className={styles.fieldError}>{offsetError}</p>}
        </div>

        <PublishFieldRow
          id="tn-publish-cost"
          label="Costo"
          type="number"
          value={cost}
          onChange={onCostChange}
          testId="tn-publish-field-cost"
        />

        <PublishFieldRow
          id="tn-publish-stock"
          label="Stock"
          type="number"
          value={stock}
          onChange={onStockChange}
          testId="tn-publish-field-stock"
        />
      </div>

      <PublishFieldRow
        id="tn-publish-promotional-price"
        label="Precio promocional"
        type="number"
        value={promotionalPrice}
        onChange={onPromotionalPriceChange}
        testId="tn-publish-field-promotional_price"
      />

      {/* Mientras se carga el recargo el precio todavía no existe: mostrar
          "debe ser mayor a cero" ahí sería ruido, no un error del operador. */}
      {!finalPriceIsValid && !loadingOffset && (
        <p className={styles.fieldError}>El precio de publicación debe ser mayor a cero.</p>
      )}
    </div>
  );
}
