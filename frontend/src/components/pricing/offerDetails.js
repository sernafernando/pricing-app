import { formatAmount } from '../../utils/ventasMlFormat';

/**
 * The best offer's detail lines of ONE product, as Productos shows them under the offer's price. Shared by the
 * product panel's ProductToggles and Publicaciones ML's Mejor Oferta cell.
 */

/** "2099-12-31" as "31/12", read as a calendar date (no time-zone shift). */
function dayMonth(isoDate) {
  const [, month, day] = String(isoDate).split('-');
  return day && month ? `${day.slice(0, 2)}/${month}` : isoDate;
}

/** The best offer's details, in Productos' order (price and markup have their own cells). */
export function offerDetails(product) {
  const details = [];
  if (product.mejor_oferta_porcentaje_rebate) details.push(`Aporte ${formatAmount(product.mejor_oferta_porcentaje_rebate)}%`);
  if (product.mejor_oferta_monto_rebate) details.push(`Rebate $ ${formatAmount(product.mejor_oferta_monto_rebate)}`);
  if (product.mejor_oferta_fecha_hasta) details.push(`Hasta ${dayMonth(product.mejor_oferta_fecha_hasta)}`);
  if (product.mejor_oferta_pvp_seller) details.push(`PVP $ ${formatAmount(product.mejor_oferta_pvp_seller)}`);
  return details;
}
