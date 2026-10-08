/**
 * The one place that reads a variation of
 * `GET /ml-publications/view/items/{item_id}/variations` (P6c). Whatever P6c
 * names its fields, the sub-rows depend only on what this returns.
 *
 * `cost` and `markup` exist only for users with `ml_metricas.ver_ganancia`;
 * with `canSeeMargin` false they are dropped even if the payload carried them.
 * A variation's markup is a single figure (`value`, null when it cannot be
 * computed, with its `reason`); it is shaped like the list's range so the same
 * cell renders both.
 */
export function readVariation(raw, { canSeeMargin }) {
  const link = raw.link ?? {};
  const linked = link.codigo != null || link.descripcion != null;
  const hasMarkup = canSeeMargin && raw.markup != null;
  const value = hasMarkup ? (raw.markup.value ?? null) : null;
  return {
    id: raw.variation_id,
    sku: link.codigo ?? raw.seller_sku ?? null,
    ean: raw.ean ?? link.ean ?? null,
    productName: link.descripcion ?? null,
    linked,
    available: raw.available_quantity ?? null,
    cost: canSeeMargin ? (raw.cost ?? null) : null,
    markup: hasMarkup
      ? { min: value, max: value, worst: value, any_negative: value != null && value < 0, reason: raw.markup.reason ?? 'ok', partial: 0 }
      : null,
    negative: value != null && value < 0,
  };
}
