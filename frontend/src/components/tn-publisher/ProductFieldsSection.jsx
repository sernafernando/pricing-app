/**
 * ProductFieldsSection — "Identidad" card (PR-9 design item b): Título full
 * width, a 3-column grid (Marca / Código de barras / SKU), and a 2-column
 * grid (Visibilidad / Envío gratis). SKU/barcode used to live in
 * `VariantFieldsSection` (PR-7) — moved here purely for layout grouping,
 * same testids/labels, zero contract change. `seo_title`/`seo_description`
 * moved out to `DescriptionSeoCard` (design item b, "Descripción y SEO").
 */
import PublishFieldRow from './PublishFieldRow';
import shellStyles from './TnPublisherShell.module.css';
import styles from './TnPublishModal.module.css';

export default function ProductFieldsSection({
  title,
  onTitleChange,
  titleInputRef,
  brand,
  onBrandChange,
  barcode,
  onBarcodeChange,
  sku,
  onSkuChange,
  visibility,
  onVisibilityChange,
  freeShipping,
  onFreeShippingChange,
}) {
  return (
    <div className={shellStyles.card}>
      <h3 className={shellStyles.cardTitle}>Identidad</h3>

      <PublishFieldRow
        id="tn-publish-title"
        label="Título"
        value={title}
        onChange={onTitleChange}
        maxLength={255}
        placeholder="Título del producto en Tienda Nube"
        hint={title.trim().length === 0 ? 'El título no puede quedar vacío.' : null}
        testId="tn-publish-field-name"
        inputRef={titleInputRef}
      />

      <div className={shellStyles.grid3}>
        <PublishFieldRow
          id="tn-publish-brand"
          label="Marca"
          value={brand}
          onChange={onBrandChange}
          placeholder="Marca del producto"
          testId="tn-publish-field-brand"
        />

        <PublishFieldRow
          id="tn-publish-barcode"
          label="Código de barras"
          value={barcode}
          onChange={onBarcodeChange}
          testId="tn-publish-field-barcode"
        />

        {/* Read-only on purpose: `publish_product` always writes the EAN as
            the variant SKU — both the idempotency pre-check and the
            ambiguous-outcome read-back look the product up by it. An
            editable control here would swallow the operator's edit with no
            feedback. */}
        <PublishFieldRow
          id="tn-publish-sku"
          label="SKU"
          value={sku}
          onChange={onSkuChange}
          readOnly
          hint="Lo asigna el sistema"
          testId="tn-publish-field-sku"
        />
      </div>

      <div className={shellStyles.grid2}>
        <div className={styles.section} data-testid="tn-publish-field-visibility">
          {/* D4/PC7: TN v1 takes the string enum visible|unlisted|hidden — a
              boolean checkbox could not express `unlisted` at all, and
              `false` is not a value TN accepts. */}
          <label className={styles.sectionTitle} htmlFor="tn-publish-visibility">
            Visibilidad
          </label>
          <select
            id="tn-publish-visibility"
            className={styles.titleInput}
            value={visibility}
            onChange={(e) => onVisibilityChange(e.target.value)}
          >
            <option value="visible">Visible en la tienda</option>
            <option value="unlisted">No listada (accesible por link)</option>
            <option value="hidden">Oculta</option>
          </select>
        </div>

        <div className={shellStyles.checkboxRow} data-testid="tn-publish-field-free_shipping">
          <label className={styles.categoryOption}>
            <input
              id="tn-publish-free-shipping"
              type="checkbox"
              checked={freeShipping}
              onChange={(e) => onFreeShippingChange(e.target.checked)}
            />
            <span>Envío gratis</span>
          </label>
        </div>
      </div>
    </div>
  );
}
