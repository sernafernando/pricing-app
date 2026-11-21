/**
 * The Tienda screen's Gremio price <-> markup math (Costo SI T3 PR 6).
 *
 * The cost is the product's costo SI in pesos (`producto.costo_si.costo_ars`, the `/productos/tienda` payload): S13
 * "costo SI is THE cost for everything", D1 markups over costo SI, owner L20 "los precios de gremio y sugerido toman
 * costo si". Without it (no `costo_si`, a USD cost without a rate, or no positive cost) the cost is unknown: no markup
 * and no price, never over the list cost (`producto.costo_ars`), never over 0 (interfaz §7).
 */

// System constant the screen has always used here.
const VARIOS_PORCENTAJE = 7;

export function costoSiArs(producto) {
  const pesos = producto?.costo_si?.costo_ars;
  return pesos != null && pesos > 0 ? Number(pesos) : null;
}

export function markupGremioDesdePrecio(costoArs, precioSinIva) {
  if (costoArs == null) return null;
  return ((precioSinIva / (1 + VARIOS_PORCENTAJE / 100)) / costoArs - 1) * 100;
}

// Price = cost x (1 + varios%) x (1 + markup%); null without a cost.
export function precioGremioDesdeMarkup(costoArs, markupPorcentaje, iva) {
  if (costoArs == null) return null;
  const sinIva = costoArs * (1 + VARIOS_PORCENTAJE / 100) * (1 + Number(markupPorcentaje) / 100);
  return { sin_iva: sinIva, con_iva: sinIva * (1 + (iva || 21) / 100) };
}
