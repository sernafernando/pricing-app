/**
 * The markup the Tienda screen shows for a manual Gremio price (Costo SI T3 PR 6).
 *
 * The cost is the product's costo SI in pesos (`producto.costo_si.costo_ars`, the `/productos/tienda` payload): S13
 * "costo SI is THE cost for everything", D1 markups over costo SI. Without it (no `costo_si`, a USD cost without a
 * rate, or no positive cost) the markup is unknown: never over the list cost (`producto.costo_ars`), never over 0.
 * Only the markup shown moves: how a price is built stays as it is (D4; its cost base waits for the owner).
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
