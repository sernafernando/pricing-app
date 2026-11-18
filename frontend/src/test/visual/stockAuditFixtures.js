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
  dias_cobertura: 60,
  cobertura_infinita: false,
  rotacion: 0.48,
  stock_promedio: 50,
  stock_promedio_dias: 12,
  // ERP / Full split (auditoria-stock-niveles S3, S4): a third of the sales by Full, the rest by ERP.
  envio: split(u7, u30),
  por_origen: {
    erp: { dias_cobertura: 75, cobertura_infinita: false, rotacion: 0.4 },
    full: { dias_cobertura: 40, cobertura_infinita: false, rotacion: 0.75 },
  },
  ...extra,
});

const money = (unidades, usd, rate = 1450) => ({ unidades, usd, ars: usd == null ? null : usd * rate });

export const AUDIT_NOTEBOOK = {
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
      ventas: sales(2, 8, 3200000, { dias_cobertura: 45, rotacion: 0.67, stock_promedio: 12 }),
      kind_counts: { cuotas_6: 3 },
      status_counts: { active: 3 },
      promo_counts: { con: 1, sin: 2 },
      markup_actual: { min: 18.1, max: 18.3 },
    },
  ],
};

export const AUDIT_CARTRIDGE = {
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
  ventas: sales(5, 25, 450000, { ultima_venta: '2026-10-20T12:00:00Z', ultima_venta_dias: 29, ageing_dias: 29, dias_cobertura: 156, rotacion: 0.19, stock_promedio: 131.6 }),
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
};

export const AUDIT_ORPHAN = {
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
    dias_cobertura: null,
    cobertura_infinita: true,
    rotacion: 0,
    stock_promedio: 4,
    por_origen: {
      erp: { dias_cobertura: null, cobertura_infinita: true, rotacion: 0 },
      full: { dias_cobertura: null, cobertura_infinita: false, rotacion: null },
    },
  }),
  kind_counts: {},
  status_counts: {},
  promo_counts: { con: 0, sin: 0 },
  markup_actual: null,
  variantes: [],
};

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
    kpis: {
      erp: money(114, 15536.55),
      full: money(70, 8710.34),
      total: money(184, 24246.9),
      productos: 3,
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

// The Marca > Categoría levels (auditoria-stock-niveles S1, S2): group rows over the products above.
const group = (fields) => ({
  productos_sin_costo: 0,
  sin_costo: false,
  publicacion_activa: true,
  promo_aplicada: true,
  kind_counts: { clasica: 3, cuotas_6: 3 },
  status_counts: { active: 6, paused: 1 },
  markup_actual: { min: -2.4, max: 30 },
  ...fields,
});

export const AUDIT_CATEGORY_NOTEBOOKS = group({
  key: 'marca:DEMO|categoria:NOTEBOOKS',
  tipo: 'categoria',
  grupo: { marca: 'DEMO', categoria: 'NOTEBOOKS' },
  descripcion: 'NOTEBOOKS',
  productos: 1,
  erp: money(30, 12600),
  full: money(32, 13860),
  total: money(62, 26460),
  publications_count: 5,
  promo_counts: { con: 3, sin: 5 },
  ventas: sales(8, 32, 12800000),
});

// One product without cost: its stock is left out of the values, which still show the costed part (KPI rule).
export const AUDIT_CATEGORY_SUPPLIES = group({
  key: 'marca:DEMO|categoria:INSUMOS',
  tipo: 'categoria',
  grupo: { marca: 'DEMO', categoria: 'INSUMOS' },
  descripcion: 'INSUMOS',
  productos: 2,
  productos_sin_costo: 1,
  sin_costo: true,
  erp: money(84, 2936.55),
  full: money(100, 620.68),
  total: money(184, 3557.23),
  publications_count: 2,
  promo_counts: { con: 0, sin: 3 },
  ventas: sales(9, 43, 970000, { dias_cobertura: 128, rotacion: 0.23 }),
});

export const AUDIT_BRAND_DEMO = group({
  key: 'marca:DEMO',
  tipo: 'marca',
  grupo: { marca: 'DEMO', categoria: null },
  descripcion: 'DEMO',
  productos: 3,
  productos_sin_costo: 1,
  sin_costo: true,
  erp: money(114, 15536.55),
  full: money(132, 14480.68),
  total: money(246, 30017.23),
  publications_count: 7,
  promo_counts: { con: 3, sin: 8 },
  // two sales of the week without shipping data, counted in ERP
  ventas: sales(17, 75, 13770000, { envio: split(17, 75, 2, 0) }),
  categorias: [AUDIT_CATEGORY_NOTEBOOKS, AUDIT_CATEGORY_SUPPLIES],
});

export const AUDIT_BRAND_NONE = group({
  key: 'marca:__none__',
  tipo: 'marca',
  grupo: { marca: '__none__', categoria: null },
  descripcion: 'Sin marca',
  productos: 1,
  erp: money(2, 180),
  full: money(0, 0),
  total: money(2, 180),
  publications_count: 1,
  promo_counts: { con: 0, sin: 1 },
  ventas: sales(0, 3, 90000),
  categorias: [
    group({
      key: 'marca:__none__|categoria:__none__',
      tipo: 'categoria',
      grupo: { marca: '__none__', categoria: '__none__' },
      descripcion: 'Sin categoría',
      productos: 1,
      erp: money(2, 180),
      full: money(0, 0),
      total: money(2, 180),
      publications_count: 1,
      promo_counts: { con: 0, sin: 1 },
      ventas: sales(0, 3, 90000),
    }),
  ],
});

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
    const rows = [AUDIT_CATEGORY_NOTEBOOKS, AUDIT_CATEGORY_SUPPLIES].map((c) => ({
      ...c,
      key: params.grupo_marca ? `marca:${params.grupo_marca}|categoria:${c.grupo.categoria}` : `categoria:${c.grupo.categoria}`,
      grupo: { marca: params.grupo_marca ?? null, categoria: c.grupo.categoria },
    }));
    return drilled(stockAuditResponse(rows));
  }
  if (params.grupo_categoria === 'NOTEBOOKS') return drilled(stockAuditResponse([AUDIT_NOTEBOOK]));
  if (params.grupo_categoria === 'INSUMOS') return drilled(stockAuditResponse([AUDIT_CARTRIDGE, AUDIT_ORPHAN]));
  return drilled(stockAuditResponse());
}
