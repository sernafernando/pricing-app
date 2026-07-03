import DOMPurify from 'dompurify';

const ALLOWED_TAGS = ['strong', 'b', 'em', 'i', 'u', 'br', 'p', 'ul', 'ol', 'li', 'a'];
const ALLOWED_ATTR = ['href', 'target', 'rel'];

// Registered ONCE at module load (ES modules evaluate a single time).
// Must run AFTER DOMPurify's attribute pass so forced target/rel are not
// stripped and so we read the already scheme-validated href.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.nodeName !== 'A') return;
  const href = node.getAttribute('href') || '';
  if (/^https?:\/\//i.test(href)) {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  } else {
    node.removeAttribute('href');
    node.removeAttribute('target');
    node.removeAttribute('rel');
  }
});

/**
 * Sanitiza HTML no confiable para renderizado seguro vía dangerouslySetInnerHTML.
 * Devuelve '' para entradas vacías/null (preserva el fallback `|| '(sin texto)'`
 * de ClaimCards). En caso contrario, devuelve un string de HTML sanitizado.
 */
export function sanitizeHtml(html) {
  if (!html) return '';
  return DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR });
}
