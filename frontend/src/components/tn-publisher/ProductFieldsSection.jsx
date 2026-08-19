/**
 * ProductFieldsSection — product-level editable fields (UI1/D2): name,
 * brand, visibility, free_shipping, and the D12-seeded seo_title /
 * seo_description / tags. `seo_title`/`seo_description` enforce their
 * 70/320-char limits via native `maxLength` (blocks further input, UI1's
 * second scenario) rather than a separate validation-error path.
 */
import PublishFieldRow from './PublishFieldRow';
import { SEO_TITLE_MAX, SEO_DESCRIPTION_MAX } from './seedSeoTags';
import styles from './TnPublishModal.module.css';

export default function ProductFieldsSection({
  title,
  onTitleChange,
  brand,
  onBrandChange,
  visibility,
  onVisibilityChange,
  freeShipping,
  onFreeShippingChange,
  seoTitle,
  onSeoTitleChange,
  seoDescription,
  onSeoDescriptionChange,
  tags,
  onTagsChange,
  titleInputRef,
}) {
  return (
    <>
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

      <PublishFieldRow
        id="tn-publish-brand"
        label="Marca"
        value={brand}
        onChange={onBrandChange}
        placeholder="Marca del producto"
        testId="tn-publish-field-brand"
      />

      <div className={styles.section} data-testid="tn-publish-field-visibility">
        {/* D4/PC7: TN v1 takes the string enum visible|unlisted|hidden — a
            boolean checkbox could not express `unlisted` at all, and `false`
            is not a value TN accepts. */}
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

      <div className={styles.section} data-testid="tn-publish-field-free_shipping">
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

      <PublishFieldRow
        id="tn-publish-seo-title"
        label="SEO — Título"
        value={seoTitle}
        onChange={onSeoTitleChange}
        maxLength={SEO_TITLE_MAX}
        hint={`${seoTitle.length}/${SEO_TITLE_MAX}`}
        testId="tn-publish-field-seo_title"
      />

      <PublishFieldRow
        id="tn-publish-seo-description"
        label="SEO — Descripción"
        value={seoDescription}
        onChange={onSeoDescriptionChange}
        as="textarea"
        maxLength={SEO_DESCRIPTION_MAX}
        hint={`${seoDescription.length}/${SEO_DESCRIPTION_MAX}`}
        testId="tn-publish-field-seo_description"
      />

      <PublishFieldRow
        id="tn-publish-tags"
        label="Tags"
        value={tags}
        onChange={onTagsChange}
        placeholder="Separados por coma"
        testId="tn-publish-field-tags"
      />
    </>
  );
}
