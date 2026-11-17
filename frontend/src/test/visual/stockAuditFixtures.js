/**
 * Invented `GET /ml-publications/view/stock-audit` answers for the Auditoría de stock view's tests and screenshots
 * (auditoria-stock S3-S7, S10). No real product, cost or amount.
 */
import { makeItem } from './publicacionesMlFixtures';

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
      ventas: sales(2, 8, 3200000),
      kind_counts: { cuotas_6: 3 },
      status_counts: { active: 3 },
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
  ventas: sales(5, 25, 450000),
  kind_counts: { clasica: 1, cuotas_3: 1 },
  status_counts: { active: 2 },
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
  ventas: sales(0, 0, 0, { series_units_90d: [], series_markup_90d: [] }),
  kind_counts: {},
  status_counts: {},
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
