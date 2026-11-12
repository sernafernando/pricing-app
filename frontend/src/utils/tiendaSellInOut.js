/**
 * The Tienda listing's `sell_in_out` (backend `SellInOutTienda`) as `SellInOutLine` reads it for one markup key.
 * Sell in is one figure for the row; sell out is per key, because each Tienda price sells through its own channel
 * (gremio / sugerido: off-ML; web_transf: Tienda Nube). Null when the row has none.
 */
export function tiendaSellInOutDe(sellInOut, key) {
  if (!sellInOut) return null;
  return {
    sell_in: sellInOut.sell_in ?? null,
    sell_out: sellInOut.sell_out?.[key] ?? null,
    markups_sell_in: sellInOut.markups_sell_in ?? {},
    markups_sell_in_out: sellInOut.markups_sell_in_out ?? {},
  };
}
