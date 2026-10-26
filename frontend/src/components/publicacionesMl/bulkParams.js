import { buildItemsParams, buildProductIdsParams } from '../../hooks/usePublicacionesMLFilters';

const MARKUP_KEYS = ['markup_neg', 'markup_min', 'markup_max'];

/**
 * What a bulk resolver (`product-ids`, `status-item-ids`) is asked: the list's filters and, where the list applies them (the publication list, with
 * `ml_metricas.ver_ganancia`), its markup filters exactly as `/items` gets them -- the resolver applies them the
 * same way, so the set comes from exactly the publications the operator sees.
 */
export function resolverParams(filters, canSeeMargin) {
  const params = buildProductIdsParams(filters);
  if (!canSeeMargin || filters.vista === 'producto' || filters.vista === 'agrupado') return params;
  const listed = buildItemsParams(filters, 1, { canSeeMargin: true });
  for (const key of MARKUP_KEYS) if (key in listed) params[key] = listed[key];
  return params;
}
