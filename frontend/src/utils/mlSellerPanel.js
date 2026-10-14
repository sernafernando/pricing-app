/**
 * Links to a publication in the Mercado Libre seller panel
 * (vendedores.mercadolibre.com.ar). The panel searches by the MLA number
 * without its "MLA" prefix: MLA1173065146 -> 1173065146.
 */

const SELLER_PANEL = 'https://vendedores.mercadolibre.com.ar/publicaciones';

/** The MLA number without its leading "MLA" (any case), or null when nothing is left. */
export function mlaNumber(itemId) {
  if (itemId == null) return null;
  const number = String(itemId).trim().replace(/^MLA/i, '');
  return number || null;
}

/** The publication in the seller panel's listing. */
export function buildMlSellerListingUrl(itemId) {
  const number = mlaNumber(itemId);
  return number && `${SELLER_PANEL}?page=1&sort=DEFAULT&search=${encodeURIComponent(number)}`;
}

/** The publication's promotions in the seller panel. */
export function buildMlSellerPromosUrl(itemId) {
  const number = mlaNumber(itemId);
  return number && `${SELLER_PANEL}/listado/promos?page=1&search=${encodeURIComponent(number)}`;
}

/** Open a seller panel URL in a new tab; nothing when there is none. */
export function openMlSellerUrl(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer');
}
