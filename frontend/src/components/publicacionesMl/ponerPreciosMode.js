/**
 * MODO PONER PRECIOS (Publicaciones ML): workflow flag + fixed column preset.
 * Distinct from URL `modo` / PRICE_MODES (Normal|Cuotas|PVP price-column set).
 */

import { PERMISOS_EDITAR_PRODUCTOS, PERMISOS_EDITAR_TIENDA } from '../pricing/productPricePermissions';

/** Spec S3 keys, plus `titulo` as the table identity column (always kept). */
export const PONER_PRECIOS_COLUMN_KEYS = [
  'titulo',
  // Owner, 2026-11-04: "en la vista de poner precios ... también tienen que estar los badges de Clásica, 3 cuotas".
  'tipo',
  'estado',
  'precio',
  'unidades_7d',
  'unidades_30d',
  'markup',
  'markup_30d',
  'last_sale',
  'ageing',
  'stock_full',
  'stock_erp',
  'codigo',
  'marca',
];

/**
 * Visibility map for the columns currently in the table: only the mode preset
 * (and titulo) stay on. Keys missing from the table (no sales/margin perm) are
 * simply omitted — never invent columns.
 * @param {string[]} columnKeys
 * @returns {Record<string, boolean>}
 */
export function visibilityForPonerPreciosMode(columnKeys) {
  const allowed = new Set(PONER_PRECIOS_COLUMN_KEYS);
  return Object.fromEntries(columnKeys.map((key) => [key, allowed.has(key)]));
}

/**
 * Same gate as edit-price + activate-promos (S8).
 * @param {(code: string) => boolean} tienePermiso
 */
export function canUsePonerPreciosMode(tienePermiso) {
  const canEditPrice = [...PERMISOS_EDITAR_PRODUCTOS, ...PERMISOS_EDITAR_TIENDA].some((code) =>
    tienePermiso(code),
  );
  return canEditPrice && tienePermiso('promos.escribir');
}
