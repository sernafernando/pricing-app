/**
 * Where a product's current sell in comes from, for the sell in tooltips (Productos, Publicaciones ML).
 *
 * - A purchase lot (FIFO): the units the lot has left.
 * - A % of cost bonus (T25c, `bono_id` set; no lot left): the bonuses giving the discount, in id order
 *   (`bono_ids`; several stack up to the cost).
 */
export function sellInOrigen(sellIn) {
  if (sellIn.bono_id != null) {
    const ids = sellIn.bono_ids?.length ? sellIn.bono_ids : [sellIn.bono_id];
    const nombre = ids.length > 1 ? 'Bonos' : 'Bono';
    return `${nombre} ${ids.map((id) => `#${id}`).join(', ')} sobre el costo`;
  }
  return `Unidades restantes del lote: ${sellIn.unidades_restantes}`;
}
