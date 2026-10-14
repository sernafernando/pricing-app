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

/** Tienda editors: `/precios/set-cuota` on the ML instalments only, `/precios/set`. */
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
