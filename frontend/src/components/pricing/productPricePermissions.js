/**
 * Who may see and write a product's prices. The edit sets mirror the backend
 * (`backend/app/api/endpoints/pricing.py`, PERMISOS_*).
 */

/** Productos editors: `/precios/set-rapido`, every `/precios/set-cuota`. */
export const PERMISOS_EDITAR_PRODUCTOS = [
  'productos.editar_precio_clasica',
  'productos.editar_precio_cuotas',
  'productos.toggle_rebate',
  'productos.toggle_web_transferencia',
];

/**
 * Tienda editors: `/precios/set-cuota` on the ML instalments only, `/precios/set`.
 * `productos.editar_precio_cuotas` is in both sets on purpose: the backend's
 * PERMISOS_EDITAR_TIENDA lists it too, and these lists mirror it as is.
 */
export const PERMISOS_EDITAR_TIENDA = [
  'tienda.editar_precio_gremio',
  'tienda.editar_precio_web_transf',
  'productos.editar_precio_cuotas',
];

/**
 * Whoever sees products, or can edit any of these prices, sees them.
 * @param {(code: string) => boolean} tienePermiso From `usePermisos()`.
 */
export function canViewProductPrices(tienePermiso) {
  return ['productos.ver', ...PERMISOS_EDITAR_PRODUCTOS, ...PERMISOS_EDITAR_TIENDA].some((code) => tienePermiso(code));
}

/**
 * Which prices the user may write, with exactly the set each endpoint enforces.
 * @param {(code: string) => boolean} tienePermiso From `usePermisos()`.
 * @returns {{ canEditClasica: boolean, canEditMlCuotas: boolean, canEditPvp: boolean,
 *   canToggleRebate: boolean, canToggleWebTransf: boolean, canToggleOutOfCards: boolean }}
 */
export function pricePermissions(tienePermiso) {
  const productos = PERMISOS_EDITAR_PRODUCTOS.some((code) => tienePermiso(code));
  const tienda = PERMISOS_EDITAR_TIENDA.some((code) => tienePermiso(code));
  return {
    // /precios/set-rapido (ML list): Productos editors only.
    canEditClasica: productos,
    // /precios/set-cuota on the ML list's 3/6/9/12: Productos or Tienda editors.
    canEditMlCuotas: productos || tienda,
    // set-rapido / set-cuota with lista_tipo=pvp: Productos editors only.
    canEditPvp: productos,
    // The Productos toggles: each endpoint checks one code (productos_pricing.py).
    canToggleRebate: tienePermiso('productos.toggle_rebate'),
    canToggleWebTransf: tienePermiso('productos.toggle_web_transferencia'),
    canToggleOutOfCards: tienePermiso('productos.toggle_out_of_cards'),
  };
}
