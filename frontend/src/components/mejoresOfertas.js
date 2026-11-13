// Shared by the PMs' better-offers badges (MejoresOfertasBadge, and the grouped one).

export const MEJORES_OFERTAS_CHANNEL = 'ml-publications:mejores-ofertas';

/** A PM's Publicaciones ML page with the badge's filters (the badge's count is that page's total). */
export const mejoresOfertasPath = (pmId) => `/ml-publicaciones?estado=active&hay_mejores_ofertas=1&pms=${pmId}`;

/** The owner's sentence, singular for one as the top bar badges pluralize their counts. */
export const mejoresOfertasText = (count) =>
  count === 1 ? 'tenés 1 promo mejor para revisar' : `tenés ${count} promos mejores para revisar`;
