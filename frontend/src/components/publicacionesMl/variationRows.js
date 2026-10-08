/**
 * The one place that reads a variation of
 * `GET /ml-publications/view/items/{item_id}/variations` (router
 * `VariationOut`, P6c), so the sub-rows depend only on what this returns.
 *
 * `costo` (`{amount, currency}`) and `markup` (`{value, reason}`) exist only for
 * users with `ml_metricas.ver_ganancia`; with `canSeeMargin` false they are
 * dropped even if the payload carried them. A variation's markup is a single
 * figure (null `value` with its `reason` when it cannot be computed); it is
 * shaped like the list's range so the same cell renders both.
 */
/** Pesos are the default; any other currency of the product's cost is named. */
export const costLabel = (currency) => (currency && currency !== 'ARS' ? `Costo ${currency}` : 'Costo');

export function readVariation(raw, { canSeeMargin }) {
  const link = raw.link ?? {};
  const linked = link.codigo != null || link.descripcion != null;
  const hasMarkup = canSeeMargin && raw.markup != null;
  const value = hasMarkup ? (raw.markup.value ?? null) : null;
  const cost = canSeeMargin ? (raw.costo ?? null) : null;
  return {
    id: raw.variation_id,
    sku: link.codigo ?? raw.seller_sku ?? null,
    attributes: (raw.attributes ?? [])
      .filter((attribute) => attribute.value != null)
      .map((attribute) => (attribute.name ? `${attribute.name}: ${attribute.value}` : String(attribute.value))),
    productName: link.descripcion ?? null,
    linked,
    // Priced with the publication's product because the variation has none of its own.
    inherited: linked && link.inherited === true,
    available: raw.available_quantity ?? null,
    sold: raw.sold_quantity ?? null,
    cost: cost?.amount ?? null,
    costCurrency: cost?.currency ?? null,
    markup: hasMarkup
      ? {
          min: value,
          max: value,
          worst: value,
          any_negative: value != null && value < 0,
          reason: raw.markup.reason ?? 'ok',
          partial: 0,
        }
      : null,
    negative: value != null && value < 0,
  };
}
