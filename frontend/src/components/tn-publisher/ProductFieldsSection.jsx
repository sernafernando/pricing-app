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
        <label className={styles.categoryOption}>
          <input
            id="tn-publish-visibility"
            type="checkbox"
            checked={visibility}
            onChange={(e) => onVisibilityChange(e.target.checked)}
          />
          <span>Visible en la tienda</span>
        </label>
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
