/**
 * Promotion types the panel/chooser may enroll (Aplicar).
 * Keep in sync with backend `WRITABLE_PROMOTION_TYPES`
 * (`ml_promotions_write_service.py`) and `PromoApplyControl` WRITABLE_TYPES.
 *
 * SMART_LIGHTNING / DOD / PRICE_DISCOUNT stay out (read-only).
 * PRICE_MATCHING_MELI_ALL stays excluded (ML-managed, never writable).
 */
export const APPLICABLE_PROMOTION_TYPES = new Set([
  'SELLER_CAMPAIGN',
  'DEAL',
  'SMART',
  'PRE_NEGOTIATED',
  'PRICE_MATCHING',
  'LIGHTNING',
]);

/** Co-funded types (meli_percentage / seller_percentage). */
export const COFUNDED_PROMOTION_TYPES = new Set(['SMART', 'PRE_NEGOTIATED', 'PRICE_MATCHING']);

/** Enroll with precio_visto / markup_visto. */
export const SMART_LIKE_PROMOTION_TYPES = new Set(['SMART', 'PRE_NEGOTIATED', 'PRICE_MATCHING']);

/** Shown before one-click LIGHTNING enroll (same meaning as PromoApplyControl). */
export const LIGHTNING_IRREVERSIBLE_WARNING =
  'Una vez que empieza no se puede quitar (solo pausando la publicación). La oferta termina cuando se vende el stock reservado.';
