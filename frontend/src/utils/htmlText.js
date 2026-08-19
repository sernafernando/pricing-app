/**
 * stripHtmlToText — extracts plain text from an untrusted HTML string.
 *
 * Uses `DOMParser`, NOT `element.innerHTML`: assigning innerHTML on a
 * detached element still executes handlers such as
 * `<img src=x onerror=...>`, and this input comes from ML/GBP (external,
 * untrusted). `DOMParser.parseFromString` builds an inert document that
 * never runs scripts or loads resources.
 *
 * Shared by `TiendaNubeReconcile.jsx` (row preview text) and
 * `tn-publisher/seedSeoTags.js` (D12 seo_description seeding) so the safe
 * implementation has exactly one home.
 */
export function stripHtmlToText(html) {
  if (!html) return '';
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    return (doc.body.textContent || '').replace(/\s+/g, ' ').trim();
  } catch {
    return '';
  }
}
