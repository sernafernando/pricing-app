/**
 * Invented `GET /ml-publications/view/stock-audit` answers for the Auditoría de stock view's tests and screenshots
 * (auditoria-stock S3-S7, S10). No real product, cost or amount.
 */
import { makeItem } from './publicacionesMlFixtures';

// `erp + full` is the window's total; `sin_envio` (sales without shipping data) is inside `erp`.
const split = (u7, u30, sin7 = 0, sin30 = 0) => ({
  '7d': { erp: u7 - Math.floor(u7 / 3), full: Math.floor(u7 / 3), sin_envio: sin7 },
  '30d': { erp: u30 - Math.floor(u30 / 3), full: Math.floor(u30 / 3), sin_envio: sin30 },
});

const sales = (u7, u30, gross, extra = {}) => ({
  unidades_7d: u7,
  unidades_30d: u30,
  facturado_30d: gross,
  total_gauss_30d: gross * 0.12,
  markup_30d: 18.4,
  total_gauss_sell_30d: null,
  markup_sell_30d: null,
  series_units_90d: Array.from({ length: 90 }, (_, d) => Math.max(0, Math.round(1 + Math.sin(d / 12) + d / 45))),
  series_markup_90d: Array.from({ length: 90 }, (_, d) => Math.round((18 + 3 * Math.sin(d / 8)) * 10) / 10),
  // Rotación (rotacion S2): the Board's last sale and ageing, coverage and rotation over 12 photographed days
  ultima_venta: '2026-11-16T15:00:00Z',
  ultima_venta_dias: 2,
  ageing_dias: 2,
  // Cobertura, Veces and their ERP / Full figures are not written here: `withRotation` derives them from each row's
  // own stock and sales, as the backend does (PR #2345 review: constants showed the same split on every row).
  stock_promedio_dias: 12,
  // ERP / Full split (auditoria-stock-niveles S3, S4): a third of the sales by Full, the rest by ERP.
  envio: split(u7, u30),
  ...extra,
});

const round1 = (n) => Math.round(n * 10) / 10;
const round2 = (n) => Math.round(n * 100) / 100;

/** `stock_audit.coverage`: days at the 30-day pace; infinite with stock and no sale, unknown with neither. */
function coverageOf(stock, sold) {
  if (sold > 0) return { dias_cobertura: round1((stock * 30) / sold), cobertura_infinita: false };
  return { dias_cobertura: null, cobertura_infinita: stock > 0 };
}

/** `stock_audit._per_stock`: sold over the average stock, unknown when that average is 0. */
const perStock = (sold, average) => (average > 0 ? round2(sold / average) : null);

/** `stock_audit._coverage_out`: one source's figures; sales without stock are 0 days and an infinite rotation. */
function byOrigin(stock, sold, average) {
  return { ...coverageOf(stock, sold), rotacion: perStock(sold, average), rotacion_infinita: sold > 0 && !(average > 0) };
}

/**
 * A row's Rotación figures from its own numbers, as `stock_audit.rotation_out` computes them: the stock is ERP + Full
 * (a variant or pack has no ERP stock of its own), the average stock is `stock_promedio` (the stock now when not
 * given) split between ERP and Full in the stock's proportion, and each source is its stock over its own sales.
 */
function withRotation(row) {
  const ventas = row.ventas;
  const variantes = row.variantes?.map(withRotation);
  if (!ventas) return variantes ? { ...row, variantes } : row;
  // a variant or pack holds no ERP stock of its own (its base does)
  const erp = ['variante', 'pack'].includes(row.tipo) ? 0 : (row.erp?.unidades ?? 0);
  const full = row.full?.unidades ?? 0;
  const stock = erp + full;
  const average = ventas.stock_promedio ?? stock;
  const ratio = stock > 0 ? average / stock : 1;
  const sold = ventas.envio?.['30d'] ?? { erp: ventas.unidades_30d, full: 0 };
  return {
    ...row,
    ...(variantes ? { variantes } : {}),
    ventas: {
      ...ventas,
      stock_actual: stock,
      vendidas_30d: ventas.unidades_30d,
      stock_promedio: average,
      ...coverageOf(stock, ventas.unidades_30d),
      rotacion: perStock(ventas.unidades_30d, average),
      por_origen: {
        erp: byOrigin(erp, sold.erp, erp * ratio),
        full: byOrigin(full, sold.full, full * ratio),
      },
    },
  };
}

const money = (unidades, usd, rate = 1450) => ({ unidades, usd, ars: usd == null ? null : usd * rate });

export const AUDIT_NOTEBOOK = withRotation({
  key: 'p9001',
  product_item_id: 9001,
  tipo: 'producto',
  codigo: 'NB-DEMO-14',
  descripcion: 'Notebook Demo 14 i5 8GB 512GB',
  marca: 'DEMO',
  costo: 420,
  moneda_costo: 'USD',
  erp: money(30, 12600),
  full: money(20, 8400),
  total: money(50, 21000),
  publications_count: 2,
  publicacion_activa: true,
  promo_aplicada: true,
  params: { item_ids: '9001' },
  ventas: sales(6, 24, 9600000),
  kind_counts: { clasica: 2, cuotas_6: 3 },
  status_counts: { active: 4, paused: 1 },
  promo_counts: { con: 2, sin: 3 },
  markup_actual: { min: 16.9, max: 19.2 },
  markup_siso: { min: 21.4, max: 24.8 },
  variantes: [
    {
      key: 'v9002',
      product_item_id: 9002,
      tipo: 'variante',
      codigo: 'NB-DEMO-14-16GB',
      descripcion: 'Notebook Demo 14 i5 16GB 512GB',
      cantidad: 1,
      costo: 455,
      moneda_costo: 'USD',
      full: money(12, 5460),
      full_unidades_base: 12,
      publications_count: 3,
      params: { item_ids: '9002' },
      ventas: sales(2, 8, 3200000, { stock_promedio: 12 }),
      kind_counts: { cuotas_6: 3 },
      status_counts: { active: 3 },
      promo_counts: { con: 1, sin: 2 },
      markup_actual: { min: 18.1, max: 18.3 },
    },
  ],
});

export const AUDIT_CARTRIDGE = withRotation({
  key: 'p9101',
  product_item_id: 9101,
  tipo: 'producto',
  codigo: 'CART-DEMO-01',
  descripcion: 'Cartucho Demo 01 negro',
  marca: 'DEMO',
  costo: 9000,
  moneda_costo: 'ARS',
  erp: money(80, 496.55),
  full: money(50, 310.34),
  total: money(130, 806.9),
  publications_count: 1,
  publicacion_activa: true,
  promo_aplicada: false,
  params: { item_ids: '9101' },
  // its own sales (1 in 7 days, 7 in 30) plus its pack's in base units (4 and 18 packs of 2), as the backend adds
  // them; two sales of the week without shipping data, counted in ERP (auditoria-stock-niveles S3)
  ventas: sales(9, 43, 970000, { ultima_venta: '2026-10-20T12:00:00Z', ultima_venta_dias: 29, ageing_dias: 29, stock_promedio: 131.6, envio: split(9, 43, 2, 0) }),
  kind_counts: { clasica: 1, cuotas_3: 1 },
  status_counts: { active: 2 },
  promo_counts: { con: 0, sin: 2 },
  markup_actual: { min: -2.4, max: 30 },
  variantes: [
    {
      key: 'v9102',
      product_item_id: 9102,
      tipo: 'pack',
      codigo: 'CART-DEMO-01-X2',
      descripcion: 'Cartucho Demo 01 negro x2',
      cantidad: 2,
      costo: 18000,
      moneda_costo: 'ARS',
      full: money(25, 310.34),
      full_unidades_base: 50,
      publications_count: 1,
      params: { item_ids: '9102' },
      ventas: sales(4, 18, 520000),
      kind_counts: { clasica: 1 },
      status_counts: { active: 1 },
      promo_counts: { con: 0, sin: 1 },
      markup_actual: { min: 28, max: 28 },
    },
  ],
});

export const AUDIT_ORPHAN = withRotation({
  key: 'p9201',
  product_item_id: 9201,
  tipo: 'pc',
  codigo: 'PC-DEMO-R5',
  descripcion: 'PC Demo Ryzen 5 16GB',
  marca: 'DEMO',
  costo: 610,
  moneda_costo: 'USD',
  erp: money(4, 2440),
  full: money(0, 0),
  total: money(4, 2440),
  publications_count: 0,
  publicacion_activa: false,
  promo_aplicada: false,
  params: { item_ids: '9201' },
  // in stock and never sold: no last sale, infinite coverage, rotation 0
  ventas: sales(0, 0, 0, {
    series_units_90d: [],
    series_markup_90d: [],
    ultima_venta: null,
    ultima_venta_dias: null,
    ageing_dias: null,
    stock_promedio: 4,
  }),
  kind_counts: {},
  status_counts: {},
  promo_counts: { con: 0, sin: 0 },
  markup_actual: null,
  variantes: [],
});

export function stockAuditResponse(rows = [AUDIT_NOTEBOOK, AUDIT_CARTRIDGE, AUDIT_ORPHAN], extra = {}) {
  return {
    rows,
    total: rows.length,
    limit: 50,
    offset: 0,
    orden: 'valor_total',
    dir: 'desc',
    can_see_sales: true,
    can_see_margin: true,
    tipo_cambio: 1450,
    tipo_cambio_fecha: '2026-11-17',
    // as the backend: the KPIs of any level add its top-level rows
    kpis: {
      ...summedStock(rows),
      productos: rows.reduce((acc, r) => acc + (r.productos ?? 1), 0),
      productos_sin_publicacion_activa: 1,
      valor_sin_publicacion_activa: money(4, 2440),
      productos_con_promo_aplicada: 1,
      productos_sin_promo_aplicada: 2,
    },
    ...extra,
  };
}

const itemMetrics = (u7, u30, gross, markup) => ({
  units_7d: u7,
  units_30d: u30,
  series_units_90d: Array.from({ length: 90 }, (_, d) => Math.max(0, Math.round(Math.sin(d / 10) + d / 60))),
  gross_30d: gross,
  last_sale_at: '2026-11-14T13:00:00Z',
  ageing_days: 2,
  total_gauss_30d: gross * 0.12,
  markup_30d: markup,
  markup_delta_pp: 0.4,
  series_markup_90d: Array.from({ length: 90 }, (_, d) => Math.round((markup + 2 * Math.sin(d / 9)) * 10) / 10),
  // `/items?desglose_envio=true`: one sale by Full in 7 days, three in 30, one of them without shipping data.
  envio: { '7d': { erp: u7 - 1, full: 1, sin_envio: 0 }, '30d': { erp: u30 - 3, full: 3, sin_envio: 1 } },
});

/** The notebook's own publications (`/items` with its `params`). */
export const AUDIT_NOTEBOOK_ITEMS = {
  items: [
    makeItem({ item_id: 'MLA1900000001', title: 'Notebook Demo 14 i5 8GB 512GB', promo_aplicada: true, listing_kind: 'cuotas_6', stock: { available: 42, full: 12, own: 30, as_of: null }, metrics: itemMetrics(4, 15, 6000000, 19.2) }),
    makeItem({ item_id: 'MLA1900000002', title: 'Notebook Demo 14 i5 8GB 512GB 12 cuotas', listing_kind: 'clasica', stock: { available: 38, full: 8, own: 30, as_of: null }, metrics: itemMetrics(2, 9, 3600000, 17.5) }),
  ],
  total: 2,
  limit: 100,
  offset: 0,
};

/** The cartridge's own publication and its pack's (`/items` with each `params`). */
export const AUDIT_CARTRIDGE_ITEMS = {
  items: [
    makeItem({ item_id: 'MLA1900000101', title: 'Cartucho Demo 01 negro original', listing_kind: 'clasica', promo_aplicada: true, stock: { available: 130, full: 50, own: 80, as_of: null }, metrics: itemMetrics(5, 25, 450000, 30) }),
  ],
  total: 1,
  limit: 100,
  offset: 0,
};
export const AUDIT_PACK_ITEMS = {
  items: [
    makeItem({ item_id: 'MLA1900000102', title: 'Pack x2 Cartucho Demo 01 negro', listing_kind: 'clasica', stock: { available: 25, full: 25, own: 0, as_of: null }, metrics: itemMetrics(4, 18, 520000, 28) }),
  ],
  total: 1,
  limit: 100,
  offset: 0,
};

// The Marca > Categoría levels (auditoria-stock-niveles S1, S2): every group is DERIVED from the rows under it, as
// the backend adds them (owner 2026-11-18: a hand-written category showed twice its products' Full).
const addMoney = (parts) => ({
  unidades: parts.reduce((acc, m) => acc + m.unidades, 0),
  usd: round2(parts.reduce((acc, m) => acc + (m.usd ?? 0), 0)),
  ars: round2(parts.reduce((acc, m) => acc + (m.ars ?? 0), 0)),
});

/** The stock parts (erp, full, total) of `rows` added (costed values only, the KPI rule). */
function summedStock(rows) {
  return Object.fromEntries(['erp', 'full', 'total'].map((part) => [part, addMoney(rows.map((r) => r[part]))]));
}

const addEnvio = (rows) =>
  Object.fromEntries(
    ['7d', '30d'].map((w) => [
      w,
      Object.fromEntries(['erp', 'full', 'sin_envio'].map((k) => [k, rows.reduce((acc, r) => acc + (r.ventas?.envio?.[w]?.[k] ?? 0), 0)])),
    ]),
  );

const isGroup = (row) => row.tipo === 'marca' || row.tipo === 'categoria';

/** A group row over `children` (products, or a brand's categories): stock, counts and sales added. */
function groupOf(fields, children) {
  return withRotation(groupFields(fields, children));
}

function groupFields(fields, children) {
  const u7 = children.reduce((acc, r) => acc + (r.ventas?.unidades_7d ?? 0), 0);
  const u30 = children.reduce((acc, r) => acc + (r.ventas?.unidades_30d ?? 0), 0);
  const gross = children.reduce((acc, r) => acc + (r.ventas?.facturado_30d ?? 0), 0);
  const productosSinCosto = children.reduce((acc, r) => acc + (isGroup(r) ? r.productos_sin_costo : r.sin_costo ? 1 : 0), 0);
  return {
    productos: children.reduce((acc, r) => acc + (isGroup(r) ? r.productos : 1), 0),
    productos_sin_costo: productosSinCosto,
    sin_costo: productosSinCosto > 0,
    ...summedStock(children),
    publications_count: children.reduce((acc, r) => acc + (r.publications_count ?? 0), 0),
    publicacion_activa: children.some((r) => r.publicacion_activa),
    promo_aplicada: children.some((r) => r.promo_aplicada),
    promo_counts: {
      con: children.reduce((acc, r) => acc + (r.promo_counts?.con ?? 0), 0),
      sin: children.reduce((acc, r) => acc + (r.promo_counts?.sin ?? 0), 0),
    },
    kind_counts: { clasica: 3, cuotas_6: 3 },
    status_counts: { active: 6, paused: 1 },
    markup_actual: { min: -2.4, max: 30 },
    ventas: sales(u7, u30, gross, {
      envio: addEnvio(children),
      stock_promedio: children.reduce((acc, r) => acc + (r.ventas?.stock_promedio ?? 0), 0),
    }),
    ...fields,
  };
}

/** The no-brand, no-category product: a cable sold a little, never by Full, and without cost (its values unknown). */
export const AUDIT_CABLE = withRotation({
  ...AUDIT_ORPHAN,
  key: 'p9301',
  product_item_id: 9301,
  tipo: 'producto',
  codigo: 'CABLE-DEMO-1M',
  descripcion: 'Cable Demo USB-C 1m',
  marca: null,
  costo: null,
  sin_costo: true,
  erp: money(2, null),
  full: money(0, 0),
  total: money(2, null),
  publications_count: 1,
  publicacion_activa: true,
  params: { item_ids: '9301' },
  promo_counts: { con: 0, sin: 1 },
  ventas: sales(0, 3, 90000, { envio: { '7d': { erp: 0, full: 0, sin_envio: 0 }, '30d': { erp: 3, full: 0, sin_envio: 0 } } }),
});

const PRODUCTS_BY_CATEGORY = {
  NOTEBOOKS: [AUDIT_NOTEBOOK],
  INSUMOS: [AUDIT_CARTRIDGE, AUDIT_ORPHAN],
  __none__: [AUDIT_CABLE],
};

export const AUDIT_CATEGORY_NOTEBOOKS = groupOf(
  { key: 'marca:DEMO|categoria:NOTEBOOKS', tipo: 'categoria', grupo: { marca: 'DEMO', categoria: 'NOTEBOOKS' }, descripcion: 'NOTEBOOKS' },
  PRODUCTS_BY_CATEGORY.NOTEBOOKS,
);

export const AUDIT_CATEGORY_SUPPLIES = groupOf(
  { key: 'marca:DEMO|categoria:INSUMOS', tipo: 'categoria', grupo: { marca: 'DEMO', categoria: 'INSUMOS' }, descripcion: 'INSUMOS' },
  PRODUCTS_BY_CATEGORY.INSUMOS,
);

export const AUDIT_BRAND_DEMO = groupOf(
  {
    key: 'marca:DEMO',
    tipo: 'marca',
    grupo: { marca: 'DEMO', categoria: null },
    descripcion: 'DEMO',
    categorias: [AUDIT_CATEGORY_NOTEBOOKS, AUDIT_CATEGORY_SUPPLIES],
  },
  [AUDIT_CATEGORY_NOTEBOOKS, AUDIT_CATEGORY_SUPPLIES],
);

const AUDIT_CATEGORY_NONE = groupOf(
  { key: 'marca:__none__|categoria:__none__', tipo: 'categoria', grupo: { marca: '__none__', categoria: '__none__' }, descripcion: 'Sin categoría' },
  PRODUCTS_BY_CATEGORY.__none__,
);

export const AUDIT_BRAND_NONE = groupOf(
  { key: 'marca:__none__', tipo: 'marca', grupo: { marca: '__none__', categoria: null }, descripcion: 'Sin marca', categorias: [AUDIT_CATEGORY_NONE] },
  [AUDIT_CATEGORY_NONE],
);

/** `GET /view/stock-audit` by its `nivel` and drill: the brands, the categories (inline in a brand, or across brands
 * at `nivel=categoria`), and a category's products. */
export function stockAuditLevelResponse(params = {}) {
  // A drill names its brand and category as their rows show them (the backend's `grupo_nombres`).
  const drilled = (response) =>
    params.grupo_marca || params.grupo_categoria
      ? {
          ...response,
          grupo_nombres: {
            marca: params.grupo_marca === 'DEMO' ? 'Demo' : null,
            categoria: params.grupo_categoria ? `${params.grupo_categoria[0]}${params.grupo_categoria.slice(1).toLowerCase()}` : null,
          },
        }
      : response;
  if (params.nivel === 'marca') return stockAuditResponse([AUDIT_BRAND_DEMO, AUDIT_BRAND_NONE]);
  if (params.nivel === 'categoria') {
    // As the backend: across brands a category is its own key; inside a drilled brand it names that brand.
    const categories = params.grupo_marca === 'DEMO'
      ? [AUDIT_CATEGORY_NOTEBOOKS, AUDIT_CATEGORY_SUPPLIES]
      : [AUDIT_CATEGORY_NOTEBOOKS, AUDIT_CATEGORY_SUPPLIES, AUDIT_CATEGORY_NONE];
    const rows = categories.map((c) => ({
      ...c,
      key: params.grupo_marca ? `marca:${params.grupo_marca}|categoria:${c.grupo.categoria}` : `categoria:${c.grupo.categoria}`,
      grupo: { marca: params.grupo_marca ?? null, categoria: c.grupo.categoria },
    }));
    return drilled(stockAuditResponse(rows));
  }
  if (params.grupo_categoria) return drilled(stockAuditResponse(PRODUCTS_BY_CATEGORY[params.grupo_categoria] ?? []));
  if (params.grupo_marca === '__none__') return drilled(stockAuditResponse(PRODUCTS_BY_CATEGORY.__none__));
  if (params.grupo_marca === 'DEMO') return drilled(stockAuditResponse([AUDIT_NOTEBOOK, AUDIT_CARTRIDGE, AUDIT_ORPHAN]));
  // every product, so the KPIs are the same on every level (S2: KPI cards unchanged)
  return drilled(stockAuditResponse([AUDIT_NOTEBOOK, AUDIT_CARTRIDGE, AUDIT_ORPHAN, AUDIT_CABLE]));
}
