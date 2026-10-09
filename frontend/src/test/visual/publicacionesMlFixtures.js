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
    user_product_id: 'MLAU100001',
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
    user_product_id: 'MLAU100002',
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

export const VARIATIONS_RESPONSE = {
  item_id: 'MLA1100000005',
  can_see_margin: true,
  variations: VARIATIONS,
  ads: { available: false, reason: 'no_data', requested: false, applied: false, date_from: null, date_to: null },
};

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

/**
 * `GET /ml-publications/view/groups` (router `ml_publications_view.py`,
 * `GroupsResponse` / `GroupNodeOut`; P7a). A brand or category key arrives
 * percent-escaped (`%`, `,`); `params` are the node's `/items` filters,
 * ancestors included. `negative_count`, `markup_min` and `markup_max` are the
 * node aggregates of P7b (only with `ver_ganancia`; not built yet when this was
 * written, shaped after the design).
 */
export const makeNode = (overrides) => ({
  kind: 'marca',
  key: 'TP-LINK',
  label: 'TP-LINK',
  count: 90,
  leaf: false,
  params: { marcas: 'TP-LINK' },
  ...overrides,
});

export const groupsResponse = (level, nodes, overrides = {}) => ({
  level,
  path: [],
  nodes,
  total: nodes.length,
  limit: 100,
  offset: 0,
  familias: false,
  ...overrides,
});

export const BRAND_NODES = [
  makeNode({ negative_count: 4, markup_min: -6.5, markup_max: 38.2 }),
  makeNode({ key: 'EPSON', label: 'EPSON', count: 60, params: { marcas: 'EPSON' }, negative_count: 0, markup_min: 8.1, markup_max: 22 }),
  makeNode({ key: 'TP%2CLINK', label: 'TP,LINK', count: 7, params: { marcas: 'TP%2CLINK' }, negative_count: 0, markup_min: null, markup_max: null }),
  makeNode({ key: '__none__', label: 'Sin marca', count: 25, params: { marcas: '__none__' }, negative_count: 0, markup_min: null, markup_max: null }),
];

export const PRODUCT_NODES = [
  makeNode({
    kind: 'producto',
    key: '4101',
    label: 'Router Archer AX55',
    count: 3,
    leaf: true,
    params: { marcas: 'TP-LINK', categorias: 'ROUTERS', subcategorias: '55', producto: '4101' },
    producto_item_id: 4101,
    codigo: 'ARCHER-AX55',
    negative_count: 1,
    markup_min: -6.5,
    markup_max: 30,
  }),
  makeNode({
    kind: 'producto',
    key: '__none__',
    label: 'Sin producto',
    count: 2,
    leaf: true,
    params: { marcas: 'TP-LINK', categorias: 'ROUTERS', subcategorias: '55', sin_producto: 'true' },
    negative_count: 0,
    markup_min: null,
    markup_max: null,
  }),
];

/**
 * `GET /ml-publications/view/items/{item_id}` (router `ml_publications_view.py`,
 * `ItemDetailResponse`; P8a). `item` is every `ml_items` column but the body and
 * its hash; `extra` is the whitelisted part of the body (`view/detail.py`, every
 * key present, `null` when the body lacks it). `replenishment` is `null` when
 * the publication is not Full. `markup_breakdown` exists only with
 * `ml_metricas.ver_ganancia` and may be `null`.
 */
export const REPLENISHMENT_OK = {
  status: 'ok',
  content_missing: null,
  period: '30d',
  units_30d: 42,
  gmv_30d: 4137021.5,
  currency: 'ARS',
  units_7d: 9,
  units_14d: 20,
  units_21d: 31,
  days_out_of_stock_21d: 2,
  shipping_urgency: 'normal',
  total_stock: 20,
  minimum_distributable_stock: 4,
  history_through: '2026-10-05',
  fetched_at: '2026-10-08T08:00:00Z',
};

/** What a Full publication shows before its first replenishment answer: every figure null. */
export const REPLENISHMENT_EMPTY = {
  status: 'never_fetched',
  content_missing: null,
  period: null,
  units_30d: null,
  gmv_30d: null,
  currency: null,
  units_7d: null,
  units_14d: null,
  units_21d: null,
  days_out_of_stock_21d: null,
  shipping_urgency: null,
  total_stock: null,
  minimum_distributable_stock: null,
  history_through: null,
  fetched_at: null,
};

export const FRESHNESS = [
  { resource: 'items', state: 'ok', fetched_at: '2026-10-08T09:30:00Z', last_checked_at: '2026-10-08T09:45:00Z', http_status: 200 },
  { resource: 'stock', state: 'ok', fetched_at: '2026-10-08T09:30:00Z', last_checked_at: '2026-10-08T09:45:00Z', http_status: 200 },
  { resource: 'replenishment', state: 'ok', fetched_at: '2026-10-08T08:00:00Z', last_checked_at: '2026-10-08T09:00:00Z', http_status: 200 },
];

export const MARKUP_BREAKDOWN = {
  variation_id: null,
  price: 98500.5,
  price_source: 'sale_price',
  pricelist_id: 12,
  installments: 6,
  comision_pct: 13.5,
  comision_total: 13297.57,
  costo_envio: 4200,
  envio_source: 'erp',
  limpio: 81002.93,
  costo_ars: 64000,
  markup: 26.5,
};

/** Every `ml_items` column the detail returns (the body and its hash are not among them). */
export const ITEM_COLUMNS = {
  item_id: 'MLA1100000001',
  site_id: 'MLA',
  seller_id: 123456789,
  title: 'Router TP-Link Archer AX55 Wi-Fi 6 Dual Band 3000 Mbps',
  brand: 'TP-Link',
  family_name: 'Archer AX55',
  family_id: 7001,
  category_id: 'MLA1648',
  domain_id: 'MLA-ROUTERS',
  user_product_id: null,
  catalog_product_id: 'MLA19000001',
  catalog_listing: false,
  official_store_id: 471846,
  status: 'active',
  sub_status: [],
  tags: ['good_quality_picture', 'immediate_payment'],
  listing_type_id: 'gold_pro',
  buying_mode: 'buy_it_now',
  condition: 'new',
  currency_id: 'ARS',
  seller_custom_field: 'ARCHER-AX55',
  seller_sku: 'AX55-SKU',
  price: 98500.5,
  base_price: 112000,
  original_price: null,
  available_quantity: 34,
  sold_quantity: 120,
  initial_quantity: 200,
  permalink: 'https://articulo.mercadolibre.com.ar/MLA-1100000001-router-tp-link-archer-ax55-_JM',
  thumbnail: null,
  health: 0.87,
  inventory_id: 'ABCD1234',
  parent_item_id: null,
  shipping_mode: 'me2',
  logistic_type: 'fulfillment',
  free_shipping: true,
  start_time: '2026-03-02T13:00:00Z',
  stop_time: '2046-03-02T13:00:00Z',
  end_time: null,
  expiration_time: null,
  date_created: '2026-03-02T13:00:00Z',
  ml_last_updated: '2026-10-08T09:00:00Z',
  http_status: 200,
  last_error: null,
};

/** The whitelisted body: warranty, shipping, sale terms, attributes, pictures, ... */
export const EXTRA_FIELDS = {
  warranty: 'Garantía del vendedor: 6 meses',
  listing_source: '',
  automatic_relist: false,
  accepts_mercadopago: true,
  international_delivery_mode: 'none',
  video_id: null,
  thumbnail_id: '987654-MLA',
  differential_pricing: null,
  channels: ['marketplace', 'mshops'],
  deal_ids: ['MLA12345'],
  shipping: { mode: 'me2', local_pick_up: false, store_pick_up: false, tags: ['self_service_in'] },
  sale_terms: [
    { id: 'WARRANTY_TIME', name: 'Tiempo de garantía', value_name: '6 meses' },
    { id: 'INSTALLMENTS_CAMPAIGN', name: 'Cuotas', value_name: '6x_campaign' },
  ],
  attributes: [
    { id: 'BRAND', name: 'Marca', value_name: 'TP-Link' },
    { id: 'MODEL', name: 'Modelo', value_name: 'Archer AX55' },
  ],
  item_relations: [{ id: 'MLA1100000009', variation_id: null, stock_relation: 1 }],
  pictures: [
    { id: '111-MLA', secure_url: 'https://http2.mlstatic.com/D_111-O.jpg', size: '500x500', max_size: '1200x1200' },
    { id: '222-MLA', secure_url: 'https://http2.mlstatic.com/D_222-O.jpg', size: '500x500', max_size: '1200x1200' },
  ],
};

/** The link of one unit (`variation_id` 0 is the item level). */
export const ITEM_LINK = {
  variation_id: 0,
  state: 'auto',
  source: 'sku',
  match_status: 'linked',
  producto_item_id: 4101,
  codigo: 'ARCHER-AX55',
  descripcion: 'Router Archer AX55',
  marca: 'TP-LINK',
  matched_sku: 'AX55-SKU',
  sku_field: 'seller_sku',
  suggested_producto_item_id: null,
  suggestion_status: null,
  linked_at: '2026-09-01T10:00:00Z',
  note: null,
};

export const makeDetail = (overrides = {}) => ({
  row: ITEMS[0],
  item: ITEM_COLUMNS,
  extra: EXTRA_FIELDS,
  sub_status: [],
  tags: ['good_quality_picture', 'immediate_payment'],
  health: 0.87,
  condition: 'new',
  date_created: '2026-03-02T13:00:00Z',
  ml_last_updated: '2026-10-08T09:00:00Z',
  fetched_at: '2026-10-08T09:30:00Z',
  stock_locations: [
    { type: 'meli_facility', quantity: 20 },
    { type: 'selling_address', quantity: 14 },
  ],
  stock_as_of: '2026-10-08T09:30:00Z',
  replenishment: REPLENISHMENT_OK,
  links: [ITEM_LINK],
  product: null,
  freshness: FRESHNESS,
  can_resync: false,
  ...overrides,
});

export const DETAIL_RESPONSE = makeDetail();

/** The same detail for a caller with `ml_metricas.ver_ganancia`: markup breakdown and product cost. */
export const DETAIL_RESPONSE_MARGIN = makeDetail({
  markup_breakdown: MARKUP_BREAKDOWN,
  can_resync: true,
});

/**
 * `GET /ml-publications/view/items/{id}/events` (router `EventsResponse` /
 * `EventOut`; P8b). `label` is the backend's Spanish label; the tab labels from
 * the type on its own. Values are the stored JSON: a price is a number, a
 * status a string.
 */
export const makeEvent = (overrides = {}) => ({
  id: 9001,
  event_type: 'price_changed',
  label: 'Cambio de precio',
  observed_at: '2026-10-08T09:30:00Z',
  promotion_type: null,
  price_kind: 'standard',
  old_value: 55882.0,
  new_value: 56382.0,
  ...overrides,
});

export const EVENTS = [
  makeEvent(),
  makeEvent({
    id: 9000,
    event_type: 'status_paused',
    label: 'Publicación pausada',
    observed_at: '2026-10-07T18:00:00Z',
    price_kind: null,
    old_value: 'active',
    new_value: 'paused',
  }),
  makeEvent({
    id: 8999,
    event_type: 'promotion_price_changed',
    label: 'Cambio de precio de la promoción',
    observed_at: '2026-10-06T12:00:00Z',
    promotion_type: 'DEAL',
    price_kind: 'promotion',
    old_value: 49900.0,
    new_value: 47900.0,
  }),
];

export const EVENTS_RESPONSE = { enabled: true, events: EVENTS, next_cursor: null };

/** The events flag off: nothing is written, so the list is empty (never invented). */
export const EVENTS_DISABLED_RESPONSE = { enabled: false, events: [], next_cursor: null };

/**
 * `GET /ml-publications/view/items/{id}/history` (router `HistoryResponse` /
 * `HistoryEntryOut`; P8b). A business line carries `label_key` and the Spanish
 * `label`; a technical one has both null. `old`/`new` are null on the side that
 * does not exist.
 */
export const HISTORY_ENTRIES = [
  {
    id: 7003,
    observed_at: '2026-10-08T09:30:00Z',
    resource_type: 'item',
    kind: 'change',
    business: [
      { path: 'price', label_key: 'price', label: 'Precio', old: 55882.0, new: 56382.0 },
      { path: 'status', label_key: 'status', label: 'Estado', old: 'active', new: 'paused' },
    ],
    technical: [{ path: 'last_updated', label_key: null, label: null, old: '2026-10-07T10:00:00.000Z', new: '2026-10-08T09:29:00.000Z' }],
  },
  {
    id: 7002,
    observed_at: '2026-10-07T18:00:00Z',
    resource_type: 'stock',
    kind: 'change',
    business: [{ path: 'locations[meli_facility].quantity', label_key: 'stock_location', label: 'Stock por ubicación', old: 24, new: 20 }],
    technical: [],
  },
  {
    id: 7001,
    observed_at: '2026-10-06T08:00:00Z',
    resource_type: 'replenishment',
    kind: 'change',
    business: [],
    technical: [{ path: 'units_30d', label_key: null, label: null, old: 40, new: 42 }],
  },
];

export const HISTORY_RESPONSE = { entries: HISTORY_ENTRIES, next_cursor: null };
