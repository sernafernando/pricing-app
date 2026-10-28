import { AlertCircle, Handshake, Trophy } from 'lucide-react';

/**
 * The catalog competition states ML reports, one table for Productos' row badge and Publicaciones ML's
 * `CatalogStatusBadge`. Each state has its words, Productos' emoji mark, Publicaciones ML's icon and the badge's tone.
 */
export const CATALOG_STATES = {
  winning: { label: 'ganando', mark: '🏆', Icon: Trophy, tone: 'var(--success)' },
  sharing_first_place: { label: 'compartiendo el primer lugar', mark: '🤝', Icon: Handshake, tone: 'var(--info)' },
  competing: { label: 'compitiendo', mark: '!', Icon: AlertCircle, tone: 'var(--warning)' },
};

/**
 * The state of a catalog status, or undefined for a status the table does not have. Only the table's own keys count,
 * so a status named like an object member (`constructor`) is unknown too.
 *
 * @param {string | null | undefined} status
 */
export const catalogState = (status) => (Object.hasOwn(CATALOG_STATES, status ?? '') ? CATALOG_STATES[status] : undefined);

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
