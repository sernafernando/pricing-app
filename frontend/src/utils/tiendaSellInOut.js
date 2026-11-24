/**
 * The Tienda listing's `sell_in_out` (backend `SellInOutTienda`) as `SellInOutLine` reads it for one markup key.
 * The sell out is per key, because each Tienda price sells through its own channel (gremio / sugerido: off-ML;
 * web_transf: Tienda Nube). No sell in (costo SI T5 PR B). Null when the row has none.
 */
export function tiendaSellInOutDe(sellInOut, key) {
  if (!sellInOut) return null;
  return {
    sell_out: sellInOut.sell_out?.[key] ?? null,
    markups_sell_in_out: sellInOut.markups_sell_in_out ?? {},
  };
}
