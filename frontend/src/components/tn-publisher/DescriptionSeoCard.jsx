/**
 * DescriptionSeoCard — "Descripción y SEO" card (PR-9 design item b). Wraps
 * `DescriptionEditor` (TipTap, moved VERBATIM — untouched, non-goal to
 * modify) and adds a 2-column grid for SEO Título (with its 31/70 counter
 * on the label row) and Tags (with its "N tags" count); SEO Descripción
 * sits full-width below, where it fits the grid sensibly.
 */
import DescriptionEditor from './DescriptionEditor';
import PublishFieldRow from './PublishFieldRow';
import { SEO_TITLE_MAX, SEO_DESCRIPTION_MAX } from './seedSeoTags';
import shellStyles from './TnPublisherShell.module.css';

export default function DescriptionSeoCard({
  editor,
  editorState,
  seoTitle,
  onSeoTitleChange,
  seoDescription,
  onSeoDescriptionChange,
  tags,
  onTagsChange,
}) {
  const tagCount = (tags || '')
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean).length;

  return (
    <div className={shellStyles.card}>
      <h3 className={shellStyles.cardTitle}>Descripción y SEO</h3>

      <DescriptionEditor editor={editor} editorState={editorState} />

      <div className={shellStyles.grid2}>
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
          id="tn-publish-tags"
          label="Tags"
          value={tags}
          onChange={onTagsChange}
          placeholder="Separados por coma"
          hint={`${tagCount} tags`}
          testId="tn-publish-field-tags"
        />
      </div>

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
    </div>
  );
}
