import { PROMO_TYPES } from '../../constants/promoTypes';

/**
 * Productos' promo filter on Publicaciones ML: promo types, promo state and "Precios mayoristas", with Productos'
 * URL keys and labels. What each value asks the backend lives in `usePublicacionesMLFilters`.
 */
export const EMPTY_PROMO_FILTERS = { promo_tipos: [], promo_estado: '', pxq: '' };
export const PROMO_STATE_OPTIONS = [
  ['', 'Disponible'],
  ['aplicada', 'Aplicada'],
  ['sin_aplicar', 'Sin aplicar'],
];
const TYPE_LABELS = Object.fromEntries(PROMO_TYPES.map(({ type, label }) => [type, label]));

/** One chip per active value, and the `setFilters` update that clears it. */
export function activePromoChips(filters) {
  const state = PROMO_STATE_OPTIONS.find(([value]) => value && value === filters.promo_estado);
  return [
    ...filters.promo_tipos.map((type) => ({
      id: type,
      label: `Promo: ${TYPE_LABELS[type] ?? type}`,
      remove: { promo_tipos: filters.promo_tipos.filter((t) => t !== type) },
    })),
    ...(state ? [{ id: 'estado', label: `Estado de promo: ${state[1]}`, remove: { promo_estado: '' } }] : []),
    ...(filters.pxq ? [{ id: 'pxq', label: 'Con precios mayoristas', remove: { pxq: '' } }] : []),
  ];
}
