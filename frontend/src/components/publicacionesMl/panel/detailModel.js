/**
 * The one place that reads `GET /ml-publications/view/items/{item_id}`
 * (`ItemDetail`, P8a), so the panel's tabs depend only on what this returns.
 *
 * The shape follows the design (§3.3, Engram #2279): P8a was still being built
 * when the panel was written. If the router differs, this module and the
 * fixtures (`test/visual/publicacionesMlFixtures.js`) are the only places to
 * change.
 *
 * Every nullable stays `null` here -- the tabs show "—", never 0. The markup
 * breakdown and the product's cost exist only for users with
 * `ml_metricas.ver_ganancia`; with `canSeeMargin` false they are dropped even
 * if the payload carried them (the backend already omits them, S59.2).
 */

/** The replenishment block: `null` when the publication is not Full. */
function readReplenishment(raw) {
  if (raw == null) return null;
  return {
    status: raw.status ?? 'never_fetched',
    contentMissing: raw.content_missing ?? null,
    period: raw.period ?? null,
    units30d: raw.units_30d ?? null,
    gmv30d: raw.gmv_30d ?? null,
    currency: raw.currency ?? null,
    units7d: raw.units_7d ?? null,
    units14d: raw.units_14d ?? null,
    units21d: raw.units_21d ?? null,
    daysOutOfStock21d: raw.days_out_of_stock_21d ?? null,
    shippingUrgency: raw.shipping_urgency ?? null,
    totalStock: raw.total_stock ?? null,
    fetchedAt: raw.fetched_at ?? null,
  };
}

function readProduct(raw, canSeeMargin) {
  if (raw == null) return null;
  const { costo, moneda_costo: costCurrency, iva, ...identity } = raw;
  return {
    ...identity,
    precios_lista: raw.precios_lista ?? {},
    ...(canSeeMargin ? { costo: costo ?? null, moneda_costo: costCurrency ?? null, iva: iva ?? null } : {}),
  };
}

/**
 * @param {object} raw The response body.
 * @param {{ canSeeMargin?: boolean }} [options]
 */
export function readDetail(raw, { canSeeMargin = false } = {}) {
  const row = raw.row ?? {};
  return {
    itemId: row.item_id ?? null,
    row,
    variationsCount: row.variations_count ?? 0,
    isFull: row.is_full === true,
    subStatus: raw.sub_status ?? [],
    tags: raw.tags ?? [],
    health: raw.health ?? null,
    condition: raw.condition ?? null,
    dateCreated: raw.date_created ?? null,
    mlLastUpdated: raw.ml_last_updated ?? null,
    fetchedAt: raw.fetched_at ?? null,
    stockLocations: raw.stock_locations ?? null,
    stockAsOf: raw.stock_as_of ?? null,
    replenishment: readReplenishment(raw.replenishment),
    links: raw.links ?? [],
    product: readProduct(raw.product, canSeeMargin),
    markupBreakdown: canSeeMargin ? (raw.markup_breakdown ?? null) : null,
    freshness: raw.freshness ?? [],
    canResync: raw.can_resync === true,
  };
}
