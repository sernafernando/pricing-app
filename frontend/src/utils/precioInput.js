/**
 * A price as an operator types it, in es-AR: the comma is the decimal
 * separator (at most 2 decimals) and the dot is ONLY a thousands separator,
 * so it must group exactly 3 digits ("120.000", "1.234.567,89"). Anything
 * else -- letters, a decimal dot, two commas, a sign -- is not a price.
 *
 * `parseFloat` would read "120.000" as 120 and "12abc" as 12: on the money
 * path a wrong reading must be refused, never truncated.
 */
const PRECIO_AR = /^(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?$/;

/**
 * @param {unknown} text
 * @returns {number | null} The price, or null when the text is not one.
 */
export function parsePrecioInput(text) {
  if (typeof text !== 'string') return null;
  const trimmed = text.trim();
  if (!PRECIO_AR.test(trimmed)) return null;
  return Number(trimmed.replaceAll('.', '').replace(',', '.'));
}

/**
 * A stored price as editable text that `parsePrecioInput` reads back to the
 * same number: no thousands separator, comma decimals ("98500,5").
 * @param {number | null | undefined} value
 */
export function formatPrecioInput(value) {
  if (value === null || value === undefined) return '';
  // Cents only: a stored 98500.123 (or 0.1 + 0.2) opens as text the parser accepts.
  return String(Math.round(Number(value) * 100) / 100).replace('.', ',');
}

/**
 * A markup percentage as an operator types it, in es-AR: digits with an
 * optional comma and at most 2 decimals, an optional leading minus and an
 * optional trailing "%" ("25", "-3,5", "18,4 %"). No thousands separator and
 * no decimal dot: "25.5" is refused, never read as 25 or 255.
 */
const MARKUP_AR = /^-?\d+(?:,\d{1,2})?(?: ?%)?$/;

/**
 * @param {unknown} text
 * @returns {number | null} The markup in percent (may be negative), or null.
 */
export function parseMarkupInput(text) {
  if (typeof text !== 'string') return null;
  const trimmed = text.trim();
  if (!MARKUP_AR.test(trimmed)) return null;
  // `+ 0` turns "-0" into 0.
  return Number(trimmed.replace(/ ?%$/, '').replace(',', '.')) + 0;
}

/**
 * A stored markup as editable text that `parseMarkupInput` reads back:
 * comma decimals, at most 2 ("18,4", "-2").
 * @param {number | null | undefined} value
 */
export function formatMarkupInput(value) {
  if (value === null || value === undefined) return '';
  return String(Math.round(Number(value) * 100) / 100 + 0).replace('.', ',');
}
