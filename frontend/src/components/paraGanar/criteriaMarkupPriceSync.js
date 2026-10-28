/** Bidirectional criteria sync: markup % ↔ precio using ERP cost in ARS.
 *
 * Simple commercial floor: precio = costo_ars * (1 + markup/100).
 * Not commission-adjusted “limpio” markup — criteria thresholds only (D11).
 */

function round2(value) {
  return Math.round(value * 100) / 100;
}

export function priceFromMarkup(costoArs, markupPct) {
  const cost = Number(costoArs);
  const markup = Number(markupPct);
  if (!(cost > 0) || !Number.isFinite(markup)) return null;
  return round2(cost * (1 + markup / 100));
}

export function markupFromPrice(costoArs, precio) {
  const cost = Number(costoArs);
  const price = Number(precio);
  if (!(cost > 0) || !Number.isFinite(price)) return null;
  return round2((price / cost - 1) * 100);
}

/** Map which sibling field to update when the operator edits one side. */
export const MARKUP_PRICE_LINKS = {
  markup_min: 'precio_min',
  markup_max: 'precio_max',
  precio_min: 'markup_min',
  precio_max: 'markup_max',
};

export function syncLinkedCriteriaField(form, key, rawValue, costoArs) {
  const next = { ...form, [key]: rawValue };
  const peer = MARKUP_PRICE_LINKS[key];
  if (!peer || !(Number(costoArs) > 0)) return next;

  const trimmed = String(rawValue ?? '').trim();
  if (!trimmed) {
    next[peer] = '';
    return next;
  }
  const numeric = Number(trimmed);
  if (!Number.isFinite(numeric)) return next;

  if (key.startsWith('markup_')) {
    const price = priceFromMarkup(costoArs, numeric);
    if (price != null) next[peer] = String(price);
  } else {
    const markup = markupFromPrice(costoArs, numeric);
    if (markup != null) next[peer] = String(markup);
  }
  return next;
}
