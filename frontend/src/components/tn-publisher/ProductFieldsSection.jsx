/**
 * ProductFieldsSection — product-level editable fields. Only `name`/Título
 * exists pre-PR-7; the catalog loop (brand, visibility, seo_title, tags…)
 * lands in PR-7's UI1.
 */
import PublishFieldRow from './PublishFieldRow';

export default function ProductFieldsSection({ title, onTitleChange }) {
  return (
    <PublishFieldRow
      id="tn-publish-title"
      label="Título"
      value={title}
      onChange={onTitleChange}
      maxLength={255}
      placeholder="Título del producto en Tienda Nube"
      hint={title.trim().length === 0 ? 'El título no puede quedar vacío.' : null}
    />
  );
}
