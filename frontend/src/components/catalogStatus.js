/**
 * The catalog competition states ML reports, one table for Productos' row badge and Publicaciones ML's
 * `CatalogStatusBadge`: the state in words, Productos' emoji mark and the tone of the badge. A status missing here is
 * shown as a neutral badge with no mark (`CatalogStatusBadge.module.css` keys its tones by these same statuses).
 */
export const CATALOG_STATES = {
  winning: { label: 'ganando', mark: '🏆', tone: 'var(--success)' },
  sharing_first_place: { label: 'compartiendo el primer lugar', mark: '🤝', tone: 'var(--info)' },
  competing: { label: 'compitiendo', mark: '!', tone: 'var(--warning)' },
};

// A price as the catalog tooltip writes it; null when it is not a usable number (no tooltip, never a crash). A price
// of 0 counts as none: Productos always read it that way (its check was the price's truthiness).
const price = (value) => {
  const number = Number(value);
  return value != null && value !== '' && Number.isFinite(number) && number !== 0 ? number.toFixed(2) : null;
};

/**
 * The catalog competition tooltip of a product, one for Productos' row badge and Publicaciones ML's
 * `CatalogStatusBadge`: the price it wins or ties at, or the price to win; undefined without that price.
 *
 * @param {{ catalog_status?: string, catalog_winner_price?: number | string, catalog_price_to_win?: number | string }} product
 * @returns {string | undefined}
 */
export function catalogTooltip(product) {
  const { catalog_status: status } = product;
  const winner = price(product.catalog_winner_price);
  const toWin = price(product.catalog_price_to_win);
  if (status === 'winning' && winner) return `Ganando a $${winner}`;
  if (status === 'competing' && toWin) return `Precio para ganar: $${toWin}`;
  if (status === 'sharing_first_place' && winner) return `Empatando a $${winner}`;
  return undefined;
}
