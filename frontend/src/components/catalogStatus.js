import { AlertCircle, Handshake, Trophy } from 'lucide-react';

/**
 * The catalog competition states ML reports, one table for Productos' row badge and Publicaciones ML's
 * `CatalogStatusBadge`. Each state has its words, Productos' emoji mark, Publicaciones ML's icon, the badge's tone and
 * its tooltip, from the product's usable prices (`winner`: the price it wins or ties at; `toWin`: the price to win).
 */
export const CATALOG_STATES = {
  winning: {
    label: 'ganando',
    mark: '🏆',
    Icon: Trophy,
    tone: 'var(--success)',
    tooltip: ({ winner }) => winner && `Ganando a $${winner}`,
  },
  sharing_first_place: {
    label: 'compartiendo el primer lugar',
    mark: '🤝',
    Icon: Handshake,
    tone: 'var(--info)',
    tooltip: ({ winner }) => winner && `Empatando a $${winner}`,
  },
  competing: {
    label: 'compitiendo',
    mark: '!',
    Icon: AlertCircle,
    tone: 'var(--warning)',
    tooltip: ({ toWin }) => toWin && `Precio para ganar: $${toWin}`,
  },
};

/** The badge's tone for a status the table does not have, in both badges. */
export const NEUTRAL_TONE = 'var(--text-tertiary)';

/**
 * The state of a catalog status, or undefined for a status the table does not have. Only the table's own keys count,
 * so a status named like an object member (`constructor`) is unknown too.
 *
 * @param {string | null | undefined} status
 */
export const catalogState = (status) => (Object.hasOwn(CATALOG_STATES, status ?? '') ? CATALOG_STATES[status] : undefined);

// A price as the catalog tooltip writes it; null when it is not a usable number (no tooltip, never a crash). Missing
// (`Number` reads it as NaN) and text that is no number fail the finite check; null, empty and 0 (read as 0) fail the
// zero one. Productos always read all of them as no price, by truthiness.
const price = (value) => {
  const number = Number(value);
  return Number.isFinite(number) && number !== 0 ? number.toFixed(2) : null;
};

/**
 * The catalog competition tooltip of a product, one for Productos' row badge and Publicaciones ML's
 * `CatalogStatusBadge`: the price it wins or ties at, or the price to win; undefined without that price.
 *
 * @param {{ catalog_status?: string, catalog_winner_price?: number | string, catalog_price_to_win?: number | string }} product
 * @returns {string | undefined}
 */
export function catalogTooltip(product) {
  const prices = { winner: price(product.catalog_winner_price), toWin: price(product.catalog_price_to_win) };
  return catalogState(product.catalog_status)?.tooltip(prices) || undefined;
}
