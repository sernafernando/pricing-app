/**
 * seedSeoTags — D12: one isolated, pure seeding function for `seo_title`,
 * `seo_description` and `tags`. Called ONCE when the draft envelope loads
 * (see `useDraftFields`'s lazy `useReducer` init) — never re-applied over
 * an operator edit.
 *
 * `tags = Marca + Categoría` is an ORCHESTRATOR ASSUMPTION pending
 * maintainer confirmation (design.md D12, tasks.md 7.9) — keeping the rule
 * in this single function, isolated from the resolver/backend, means a
 * maintainer correction only touches this file.
 */
import { stripHtmlToText } from '../../utils/htmlText';

const SEO_TITLE_MAX = 70;
const SEO_DESCRIPTION_MAX = 320;

export function seedSeoTags({ name, descriptionHtml, marca, categoria }) {
  const seoTitle = (name || '').trim().slice(0, SEO_TITLE_MAX);
  const seoDescription = stripHtmlToText(descriptionHtml).slice(0, SEO_DESCRIPTION_MAX);
  const tags = [marca, categoria]
    .map((v) => (v || '').trim())
    .filter(Boolean)
    .join(', ');
  return { seoTitle, seoDescription, tags };
}

export { SEO_TITLE_MAX, SEO_DESCRIPTION_MAX };
