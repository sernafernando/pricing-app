import { preciosAPI } from '../../services/api';
import { formatAmount } from '../../utils/ventasMlFormat';
import { isBlank } from './priceFormat';

/*
 * How a product's prices are written: the lists and the endpoint of each price, shared by the panel's Precios tab
 * (`ProductPrices`) and Publicaciones ML's table (S11), so both write exactly as Productos does.
 */

/**
 * The prices shown, per list, with the `ProductoResponse` columns of each
 * price and its markup. "Lista ML" is what pricing.py calls `lista_tipo=web`
 * (there are no separate web cuotas).
 *
 * To write one, `write` names the endpoint Productos uses for that cell
 * (`rapido` = /precios/set-rapido, `cuota` = /precios/set-cuota),
 * `pricelist` the list its negative-markup check asks about and `perm` the
 * `pricePermissions` flag that allows it. `short` is the visible label of an
 * installments row ("12C"), so every list fits the side panel; `label` stays
 * its full name (tooltip, accessible name, messages). `sellInOut` is the row's key in
 * `sell_in_out.markups_sell_in[_out]` of GET /productos/{item_id}, the PPP
 * markup keys (costo_ppp_service.ppp_key_*).
 */
const ML_CUOTAS = [
  ['3', 17],
  ['6', 14],
  ['9', 13],
  ['12', 23],
];
const PVP_CUOTAS = [
  ['3', 18],
  ['6', 19],
  ['9', 20],
  ['12', 21],
];

export const LISTS = [
  {
    id: 'ml',
    title: 'Lista ML',
    subtitle: 'Precio de las publicaciones en Mercado Libre',
    rows: [
      { id: 'ml-clasica', label: 'Clásica', precio: 'precio_lista_ml', markup: 'markup', pricelist: 4, write: 'rapido', listaTipo: 'web', perm: 'canEditClasica', sellInOut: 'clasica' },
      ...ML_CUOTAS.map(([cuota, pricelist]) => ({
        id: `ml-${cuota}`,
        label: `${cuota} cuotas`,
        short: `${cuota}C`,
        precio: `precio_${cuota}_cuotas`,
        markup: `markup_${cuota}_cuotas`,
        pricelist,
        write: 'cuota',
        cuota,
        listaTipo: 'web',
        perm: 'canEditMlCuotas',
        sellInOut: `cuota_clasica_${cuota}`,
      })),
    ],
  },
  {
    id: 'pvp',
    title: 'PVP',
    subtitle: 'Precio de venta al público',
    rows: [
      { id: 'pvp-clasica', label: 'PVP clásica', short: 'PVP clás.', precio: 'precio_pvp', markup: 'markup_pvp', pricelist: 12, write: 'rapido', listaTipo: 'pvp', perm: 'canEditPvp', sellInOut: 'pvp_clasica' },
      ...PVP_CUOTAS.map(([cuota, pricelist]) => ({
        id: `pvp-${cuota}`,
        label: `PVP ${cuota} cuotas`,
        short: `PVP ${cuota}C`,
        precio: `precio_pvp_${cuota}_cuotas`,
        markup: `markup_pvp_${cuota}_cuotas`,
        pricelist,
        write: 'cuota',
        cuota,
        listaTipo: 'pvp',
        perm: 'canEditPvp',
        sellInOut: `pvp_cuota_${cuota}`,
      })),
    ],
  },
];

export const errorText = (error, fallback) => {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' && detail ? detail : fallback;
};

export const RECALCULAR_CUOTAS_KEY = 'recalcularCuotasAuto';
// This tab's last choice while the browser refuses to save it (blocked or full storage): it wins over whatever
// storage still holds, so the switch and the saves agree. A save that works clears it.
let unsavedPreference = null;

/** The user's Productos preference for recalculating instalments, default on. */
export function recalcularCuotasPreference() {
  if (unsavedPreference !== null) return unsavedPreference;
  try {
    const saved = window.localStorage.getItem(RECALCULAR_CUOTAS_KEY);
    return saved === null ? true : JSON.parse(saved);
  } catch {
    return true;
  }
}

/** Sets the preference Productos and Tienda flip too (same key), for this browser. */
export function setRecalcularCuotasPreference(value) {
  try {
    window.localStorage.setItem(RECALCULAR_CUOTAS_KEY, JSON.stringify(value));
    unsavedPreference = null;
  } catch {
    unsavedPreference = value;
  }
}

/** Same rule as Productos: the product's own setting wins over the preference. */
export const recalcularCuotas = (product) =>
  isBlank(product.recalcular_cuotas_auto) ? recalcularCuotasPreference() : product.recalcular_cuotas_auto;

export function writePrice(row, itemId, precio, product) {
  if (row.write === 'rapido') {
    const params = { item_id: itemId, precio, recalcular_cuotas: recalcularCuotas(product) };
    return preciosAPI.setRapido(row.listaTipo === 'pvp' ? { ...params, lista_tipo: 'pvp' } : params);
  }
  return preciosAPI.setCuota({ item_id: itemId, tipo_cuota: row.cuota, precio, lista_tipo: row.listaTipo });
}

/**
 * What the inline confirmation says before a price is saved: a cleared price,
 * a negative markup, or the price a target markup resolved to.
 */
export function warningText(pending) {
  const { row } = pending;
  const resulting = pending.precio === undefined ? '' : ` Precio resultante: $ ${formatAmount(pending.precio)}.`;
  if (pending.kind === 'markup') {
    return `Precio resultante para ${row.label} con markup ${formatAmount(pending.markup)}%: $ ${formatAmount(pending.precio)}.`;
  }
  if (pending.kind === 'zero') {
    return row.write === 'rapido'
      ? `Esto borra el precio de la lista ${row.listaTipo === 'pvp' ? 'PVP' : 'ML'} y todas sus cuotas.`
      : `Esto borra el precio de ${row.label}.`;
  }
  return `Markup negativo en ${row.label}: ${formatAmount(pending.markup)}%. El precio queda por debajo del costo más comisiones.${resulting}`;
}
