/** Bidirectional criteria sync via Pricing endpoints (D11).
 *
 * Markup → price: POST /precios/calcular-por-markup (adicional_markup=0).
 * Price → markup: GET /precios/calcular-markup.
 * Same commission/shipping/cost chain as Productos — not costo*(1+markup).
 */

export const MARKUP_PRICE_LINKS = {
  markup_min: 'precio_min',
  markup_max: 'precio_max',
  precio_min: 'markup_min',
  precio_max: 'markup_max',
};

function round2(value) {
  return Math.round(Number(value) * 100) / 100;
}

/**
 * Resolve the peer field for a markup/precio edit using Pricing calculators.
 * @returns {{ peer: string, peerValue: string } | { peer: string, peerValue: '' } | null}
 */
export async function resolveLinkedCriteriaValue({
  key,
  rawValue,
  itemId,
  pricelistId,
  calcularPorMarkup,
  calcularMarkup,
}) {
  const peer = MARKUP_PRICE_LINKS[key];
  if (!peer) return null;
  if (itemId == null || pricelistId == null) return null;

  const trimmed = String(rawValue ?? '').trim();
  if (!trimmed) {
    return { peer, peerValue: '' };
  }
  const numeric = Number(trimmed);
  if (!Number.isFinite(numeric)) return null;

  if (key.startsWith('markup_')) {
    const { data } = await calcularPorMarkup({
      item_id: itemId,
      pricelist_id: pricelistId,
      markup_objetivo: numeric,
      adicional_markup: 0,
    });
    if (data?.precio == null || !Number.isFinite(Number(data.precio))) return null;
    return { peer, peerValue: String(round2(data.precio)) };
  }

  const { data } = await calcularMarkup({
    item_id: itemId,
    pricelist_id: pricelistId,
    precio: numeric,
  });
  if (data?.markup == null || !Number.isFinite(Number(data.markup))) return null;
  return { peer, peerValue: String(round2(data.markup)) };
}
