/**
 * Display label map for MercadoLibre publication types, keyed by pricelist_id.
 *
 * Order is NOT derived from this map — the backend endpoint
 * (`GET /productos/{item_id}/mercadolibre`) already returns
 * `publicaciones_ml` pre-sorted Clásica -> 3 -> 6 -> 9 -> 12 cuotas
 * (productos_detail.py:288-291). Do not re-sort on the FE.
 */
export const ML_PUBLICATION_TYPE_LABELS = {
  4: 'Clásica',
  17: '3 Cuotas',
  14: '6 Cuotas',
  13: '9 Cuotas',
  23: '12 Cuotas',
};

/**
 * Returns the display label for a given pricelist_id, or a fallback.
 */
export function getPublicationTypeLabel(pricelistId) {
  return ML_PUBLICATION_TYPE_LABELS[pricelistId] || 'Desconocido';
}

export default ML_PUBLICATION_TYPE_LABELS;
