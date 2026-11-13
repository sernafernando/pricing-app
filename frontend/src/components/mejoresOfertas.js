// Shared by the PMs' better-offers badges (MejoresOfertasBadge, and the grouped one).

/** Whoever reviews the PMs: the grouped notifier with every PM's count. */
export const PERMISO_MEJORES_OFERTAS_PMS = 'alertas.ver_mejores_ofertas_pms';

export const MEJORES_OFERTAS_CHANNEL = 'ml-publications:mejores-ofertas';

/** A PM's Publicaciones ML page with the badge's filters (the badge's count is that page's total). */
export const mejoresOfertasPath = (pmId) => `/ml-publicaciones?estado=active&hay_mejores_ofertas=1&pms=${pmId}`;

/** The owner's sentence, singular for one as the top bar badges pluralize their counts. */
export const mejoresOfertasText = (count) =>
  count === 1 ? 'tenés 1 promo mejor para revisar' : `tenés ${count} promos mejores para revisar`;
