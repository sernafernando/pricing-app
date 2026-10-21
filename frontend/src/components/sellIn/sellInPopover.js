/** Geometry of the operation picker's products card (`SellInOperacionProductos`); width and height match its CSS. */

const ANCHO = 360;
const ALTO_MAX = 320;
const MARGEN = 8;

/**
 * Where the card goes: to the left of the option when it fits (the create panel docks on the right),
 * else under it; always inside the viewport. Without a measured option (tests) it sits at the corner.
 */
export function posicion(rect, vw = window.innerWidth, vh = window.innerHeight) {
  if (!rect) return { top: MARGEN, left: MARGEN };
  const limitar = (valor, max) => Math.max(MARGEN, Math.min(valor, max));
  if (rect.left - ANCHO - MARGEN >= MARGEN) {
    return { top: limitar(rect.top, vh - ALTO_MAX - MARGEN), left: rect.left - ANCHO - MARGEN };
  }
  return { top: limitar(rect.bottom + 4, vh - ALTO_MAX - MARGEN), left: limitar(rect.left, vw - ANCHO - MARGEN) };
}
