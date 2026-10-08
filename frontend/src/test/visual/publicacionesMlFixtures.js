/**
 * Fixtures shaped like `GET /ml-publications/view/items` (router
 * `ml_publications_view.py`, `ItemsResponse`). Every field, name and type is the
 * backend's; nothing here is an invention of the screen. The response is
 * serialised with `response_model_exclude_unset`, so `last_event` exists only
 * while `events_enabled` and `facets` only when the request asked for them.
 */
const ITEM_DEFAULTS = {
  title: null,
  thumbnail: null,
  permalink: null,
  status: 'active',
  sub_status: [],
  listing_type_id: 'gold_special',
  catalog_listing: false,
  logistic_type: 'xd_drop_off',
  is_full: false,
  official_store_id: null,
  store_label: null,
  ml_brand: null,
  family_id: null,
  family_name: null,
  user_product_id: null,
  variations_count: 0,
  gone: false,
  gone_at: null,
  price: { amount: null, source: null, regular_amount: null, promotion_type: null, campaign: null, pricelist_id: null },
  stock: { available: null, full: null, own: null, as_of: null },
  link: { state: 'no_evaluado', producto_item_id: null, codigo: null, descripcion: null, marca: null },
  last_activity_at: null,
};

export const makeItem = (overrides) => ({ ...ITEM_DEFAULTS, ...overrides });

export const ITEMS = [
  makeItem({
    item_id: 'MLA1100000001',
    title: 'Router TP-Link Archer AX55 Wi-Fi 6 Dual Band 3000 Mbps',
    thumbnail: null,
    permalink: 'https://articulo.mercadolibre.com.ar/MLA-1100000001-router-tp-link-archer-ax55-_JM',
    status: 'active',
    listing_type_id: 'gold_pro',
    logistic_type: 'fulfillment',
    is_full: true,
    official_store_id: 471846,
    store_label: 'TP-Link',
    ml_brand: 'TP-Link',
    family_id: 7001,
    family_name: 'Archer AX55',
    price: {
      amount: 98500.5,
      source: 'sale_price',
      regular_amount: 112000,
      promotion_type: 'DEAL',
      campaign: 'Hot Sale',
      pricelist_id: 12,
    },
    stock: { available: 34, full: 20, own: 14, as_of: '2026-10-08T09:30:00Z' },
    link: {
      state: 'auto',
      producto_item_id: 4101,
      codigo: 'ARCHER-AX55',
      descripcion: 'Router Archer AX55',
      marca: 'TP-LINK',
    },
    last_activity_at: '2026-10-08T10:05:00Z',
    last_event: { event_type: 'price_changed', observed_at: '2026-10-08T10:05:00Z' },
  }),
  makeItem({
    item_id: 'MLA1100000002',
    title: 'Cartucho Epson 544 Negro Original Ecotank L3110 L3150 65 ml',
    permalink: 'https://articulo.mercadolibre.com.ar/MLA-1100000002-cartucho-epson-544-_JM',
    status: 'paused',
    sub_status: ['out_of_stock'],
    official_store_id: 57997,
    store_label: 'Gauss',
    ml_brand: 'Epson',
    price: { amount: 18900, source: 'productos_fallback', regular_amount: null, promotion_type: null, campaign: null, pricelist_id: null },
    stock: { available: 0, full: null, own: 0, as_of: null },
    link: { state: 'manual', producto_item_id: 4102, codigo: 'EP-544-BK', descripcion: 'Tinta Epson 544 negro', marca: 'EPSON' },
    last_activity_at: '2026-10-07T18:00:00Z',
    last_event: { event_type: 'stock_depleted', observed_at: '2026-10-07T18:00:00Z' },
  }),
  makeItem({
    item_id: 'MLA1100000003',
    title: null,
    permalink: null,
    status: null,
    price: { amount: null, source: null, regular_amount: null, promotion_type: null, campaign: null, pricelist_id: null },
    last_activity_at: null,
  }),
  makeItem({
    item_id: 'MLA1100000004',
    title: 'Mouse inalámbrico Logitech M170 gris',
    permalink: 'https://articulo.mercadolibre.com.ar/MLA-1100000004-mouse-logitech-m170-_JM',
    status: 'closed',
    gone: true,
    gone_at: '2026-10-01T00:00:00Z',
    variations_count: 3,
    price: { amount: 12500, source: 'item_price', regular_amount: null, promotion_type: null, campaign: null, pricelist_id: 12 },
    stock: { available: 5, full: null, own: null, as_of: null },
    link: { state: 'sin_producto', producto_item_id: null, codigo: null, descripcion: null, marca: null },
    last_activity_at: '2026-10-01T09:00:00Z',
  }),
];

const withoutLastEvent = (item) => {
  const { last_event: _ignored, ...rest } = item;
  return rest;
};

export const DATA_STATE_OK = {
  available: true,
  generated_at: '2026-10-08T10:00:00Z',
  store_empty: false,
  kill_switch: false,
  degraded: false,
  degradations: [],
  sections_failed: [],
};

export const FACETS = {
  status: { active: 180, paused: 40, closed: 12, gone: 3 },
  stores: { 471846: 90, 57997: 110, none: 35 },
  marcas: { 'TP-LINK': 90, EPSON: 60 },
  listing: { clasica: 120, premium: 100, catalogo: 30, full: 55 },
  link: { auto: 150, manual: 40, sin_producto: 25, conflicto: 2, no_evaluado: 18 },
  stock: { sin_stock: 14, full_sin_stock: 6 },
  total: 235,
};

export const ITEMS_RESPONSE = {
  items: ITEMS,
  total: 235,
  limit: 50,
  offset: 0,
  can_see_margin: false,
  events_enabled: true,
  data_state: DATA_STATE_OK,
};

export const itemsResponse = (overrides = {}) => ({ ...ITEMS_RESPONSE, ...overrides });

/** The same page with the events flag off: no `last_event` key at all. */
export const ITEMS_RESPONSE_EVENTS_OFF = {
  ...ITEMS_RESPONSE,
  events_enabled: false,
  items: ITEMS.map(withoutLastEvent),
};

/**
 * `GET /ml-publications/view/items/{item_id}/variations` (router
 * `ml_publications_view.py`, `VariationsResponse`; P6c). `costo` and `markup`
 * exist only with `ml_metricas.ver_ganancia`; `link.inherited` says the product
 * is the item-level one because the variation has no link of its own.
 */
export const makeVariation = (overrides) => ({
  variation_id: 1,
  seller_sku: null,
  user_product_id: null,
  available_quantity: 0,
  sold_quantity: 0,
  attributes: [],
  link: { state: 'no_evaluado', inherited: false, producto_item_id: null, codigo: null, descripcion: null, marca: null },
  ...overrides,
});

export const VARIATIONS = [
  makeVariation({
    variation_id: 9001,
    seller_sku: 'ARCH-AX55-N',
    attributes: [{ name: 'Color', value: 'Negro' }],
    link: { state: 'auto', inherited: false, producto_item_id: 4101, codigo: 'ARCHER-AX55', descripcion: 'Router Archer AX55 negro', marca: 'TP-LINK' },
    available_quantity: 14,
    sold_quantity: 120,
    costo: { amount: 41000.5, currency: 'ARS' },
    markup: { value: 12.5, reason: 'ok' },
  }),
  makeVariation({
    variation_id: 9002,
    seller_sku: 'ARCH-AX55-B',
    attributes: [{ name: 'Color', value: 'Blanco' }],
    link: { state: 'manual', inherited: true, producto_item_id: 4102, codigo: 'ARCHER-AX55-B', descripcion: 'Router Archer AX55 blanco', marca: 'TP-LINK' },
    available_quantity: 0,
    sold_quantity: 40,
    costo: { amount: 520, currency: 'USD' },
    markup: { value: -4.2, reason: 'ok' },
  }),
  makeVariation({
    variation_id: 9003,
    seller_sku: null,
    attributes: [{ name: 'Color', value: 'Gris' }],
    link: { state: 'sin_producto', inherited: false, producto_item_id: null, codigo: null, descripcion: null, marca: null },
    available_quantity: 3,
    sold_quantity: 0,
    costo: null,
    markup: { value: null, reason: 'sin_vinculo' },
  }),
];

export const VARIATIONS_RESPONSE = { item_id: 'MLA1100000005', variations: VARIATIONS };

/** A publication with variations and a markup range, for the expandable row. */
export const VARIATION_ITEM = makeItem({
  item_id: 'MLA1100000005',
  title: 'Router TP-Link Archer AX55 por color',
  permalink: 'https://articulo.mercadolibre.com.ar/MLA-1100000005-router-archer-_JM',
  variations_count: 3,
  price: { amount: 98500.5, source: 'sale_price', regular_amount: null, promotion_type: null, campaign: null, pricelist_id: 12 },
  stock: { available: 17, full: null, own: 17, as_of: null },
  markup: { min: -4.2, max: 12.5, worst: -4.2, any_negative: true, reason: 'ok', partial: 1, ads: null },
});
