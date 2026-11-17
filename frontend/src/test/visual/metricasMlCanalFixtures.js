/**
 * Métricas board fixtures with `canal=todo` and `canal=fuera`, shaped exactly like contract C3 of
 * `odd/tasks/vpf-metricas-canal-fe.md` (`GET /ml-metricas/board` with the fuera fields). Every name, amount and date
 * is invented (the repo is public): they only follow the approved mockups' layout.
 */
import { BOARD_RESPONSE, BOARD_ROWS } from './metricasMlFixtures';

const PERIOD = { date_from: '2026-10-01', date_to: '2026-10-31', prev_from: '2026-08-31', prev_to: '2026-09-30' };

// One gross amount per day of October: weekends without sales, one high and one low day.
const FUERA_DAYS = [
  3.2, 0, 0, 5.4, 6.6, 7.9, 0, 0, 5.1, 7.4, 8.8, 6.3, 5.2, 0, 0, 10.9, 6.2, 9.5, 7.9, 3.8, 0, 0, 5.4, 4.9, 8.9, 6.8, 7.2, 0,
  0, 6.1, 4.4,
].map((millions) => Math.round(millions * 1_000_000 * 100) / 100);
const ML_DAYS = FUERA_DAYS.map((_, i) => 1_900_000 + ((i * 7919) % 900_000));

const OTHER_KPIS = {
  rows_with_sales: { value: 74, of_total: 90 },
  ageing: { avg_days: 21, up_to_30: 64, from_31_to_60: 11, over_60: 5 },
  units_per_sale: { value: 1.1, delta_pct: 0.4 },
};

export const ULTIMO_PDF = { created_at: '2026-11-16T15:10:00Z', empresa: 'Empresa Norte', vendedor: 'Vendedora Uno' };

export const FUERA_EXTRAS = {
  comprobantes: 152,
  por_tipo: [
    { tipo: 'FC', letra: 'A', cantidad: 96 },
    { tipo: 'FC', letra: 'B', cantidad: 48 },
    { tipo: 'NC', letra: 'A', cantidad: 6 },
    { tipo: 'ND', letra: 'A', cantidad: 2 },
  ],
  recargo_cheque: 412300.5,
  sin_producto: { lineas: 12, monto: 6120400.1 },
  otro_costo: { costo: 'costo', margin: 31850000, markup_pct: 27.4 },
  ultimo_pdf: ULTIMO_PDF,
};

const fueraRow = (key, fields) => ({
  ...BOARD_ROWS[0],
  key: String(key),
  product_item_id: key,
  publications_count: 1,
  units_24h: 0,
  units_3d: 0,
  alerts: [],
  sell_in_out: null,
  ...fields,
});

const SIN_PRODUCTO_ROW = fueraRow(-501, {
  title: 'PC armada de prueba R5 16GB (Manual)',
  sku: null,
  marca: null,
  units: 6,
  units_7d: 2,
  units_15d: 4,
  units_30d: 6,
  gross: 5480200.4,
  total_gauss: null,
  costo: null,
  markup_pct: null,
  markup_prev_pct: null,
  markup_delta_pp: null,
  markup_min_90d: null,
  markup_max_90d: null,
  stock: null,
  ageing_days: null,
  last_sale_at: '2026-10-28T15:30:00Z',
  alerts: ['sin_producto'],
});

export const FUERA_ROWS = [
  fueraRow(7101, {
    title: 'Notebook de prueba 15" R7 16GB',
    sku: '7790000000011',
    marca: 'Marca Uno',
    units: 24,
    units_7d: 4,
    units_15d: 11,
    units_30d: 24,
    gross: 22410300.5,
    total_gauss: 3010300.5,
    costo: 19400000,
    markup_pct: 15.5,
    markup_delta_pp: 0.7,
    stock: 14,
    ageing_days: 0,
    last_sale_at: '2026-10-30T13:00:00Z',
  }),
  fueraRow(7102, {
    title: 'Impresora láser de prueba B/N WiFi',
    sku: '7790000000028',
    marca: 'Marca Dos',
    units: 30,
    units_7d: 9,
    units_15d: 18,
    units_30d: 30,
    gross: 9775400.2,
    total_gauss: 1450400.2,
    costo: 8325000,
    markup_pct: 17.4,
    markup_delta_pp: -0.4,
    stock: 22,
    ageing_days: 0,
    last_sale_at: '2026-10-31T12:15:00Z',
  }),
  SIN_PRODUCTO_ROW,
  fueraRow(7103, {
    title: 'Router de prueba AC1200',
    sku: '7790000000035',
    marca: 'Marca Tres',
    units: 190,
    units_7d: 48,
    units_15d: 101,
    units_30d: 190,
    gross: 4210500.9,
    total_gauss: 781200.9,
    costo: 3429300,
    markup_pct: 22.8,
    markup_delta_pp: 0.9,
    stock: 96,
    ageing_days: 0,
    last_sale_at: '2026-10-31T17:44:00Z',
  }),
];

export const FUERA_BOARD_RESPONSE = {
  ...BOARD_RESPONSE,
  period: PERIOD,
  total: 90,
  with_sales_count: 74,
  refreshed_at: '2026-11-16T15:12:00Z',
  kpis: {
    units: { value: 1240, delta_pct: 6.2, series: FUERA_DAYS.map((v) => Math.round(v / 120000)) },
    gross: { value: 148520300.5, delta_pct: 4.1, series: FUERA_DAYS },
    total_gauss: { value: 24310000, delta_pct: 2.2, series: FUERA_DAYS.map((v) => v * 0.16) },
    markup: { value: 19.8, delta_pp: -0.6, series: FUERA_DAYS.map(() => 19.8) },
    operations: { value: 152, delta_pct: 3.1, series: FUERA_DAYS.map((v) => Math.round(v / 1_000_000)) },
    ticket: { value: 977107.24, delta_pct: 1.2, series: FUERA_DAYS },
    ...OTHER_KPIS,
    venta_desconocida_lineas: 0,
    fuera: FUERA_EXTRAS,
  },
  facets: {
    ...BOARD_RESPONSE.facets,
    alerts: { sin_ventas_30d: 3, ageing_60d: 5, margen_cayendo: 4, sin_producto: 12 },
    stock: { con_stock: 64, sin_stock: 9, sin_dato: 15 },
    ageing: { up_to_30: 64, from_31_to_60: 11, over_60: 5 },
    empresas: ['Empresa Norte', 'Empresa Sur'],
    empresa_documentos: { 'Empresa Norte': 152, 'Empresa Sur': 0 },
    vendedores: ['Vendedora Uno', 'Vendedor Dos', 'Vendedora Tres', 'Vendedor Cuatro', 'Vendedora Cinco'],
    vendedor_documentos: { 'Vendedora Uno': 96, 'Vendedor Dos': 31, 'Vendedora Tres': 14, 'Vendedor Cuatro': 8, 'Vendedora Cinco': 3 },
  },
  rows: FUERA_ROWS,
};

const ML_UNITS = 3412;
const ML_GROSS = 84920450;
const ML_MARGIN = 14120900.1;

export const TODO_ROWS = [
  { ...FUERA_ROWS[0], canal: 'ambos', units: 41, gross: 31880400, total_gauss: 4812900, costo: 27067500 },
  { ...BOARD_ROWS[0], canal: 'ml', costo: 160181992.06 },
  { ...FUERA_ROWS[1], canal: 'fuera' },
  { ...FUERA_ROWS[3], canal: 'ambos', units: 318, gross: 8210500, total_gauss: 1453000, costo: 6757500 },
  { ...SIN_PRODUCTO_ROW, canal: 'fuera' },
];

export const TODO_BOARD_RESPONSE = {
  ...FUERA_BOARD_RESPONSE,
  period: PERIOD,
  total: 471 + 90,
  with_sales_count: 402,
  refreshed_at: new Date(Date.now() - 3 * 60 * 1000).toISOString(),
  kpis: {
    ...BOARD_RESPONSE.kpis,
    units: { value: ML_UNITS + 1240, delta_pct: 9.8, series: BOARD_RESPONSE.kpis.units.series },
    gross: {
      value: ML_GROSS + 148520300.5,
      delta_pct: 6.4,
      series: FUERA_DAYS.map((v, i) => v + ML_DAYS[i]),
      series_por_canal: { ml: ML_DAYS, fuera: FUERA_DAYS },
    },
    total_gauss: { value: ML_MARGIN + 24310000, delta_pct: 1.1, series: BOARD_RESPONSE.kpis.total_gauss.series },
    markup: { value: 20.3, delta_pp: -0.9, series: BOARD_RESPONSE.kpis.markup.series },
    rows_with_sales: { value: 402, of_total: 561 },
    venta_desconocida_lineas: 3,
    fuera: FUERA_EXTRAS,
    por_canal: {
      ml: { units: ML_UNITS, gross: ML_GROSS, margin: ML_MARGIN, markup_pct: 21.6 },
      fuera: { units: 1240, gross: 148520300.5, margin: 24310000, markup_pct: 19.8 },
    },
  },
  facets: {
    ...FUERA_BOARD_RESPONSE.facets,
    alerts: { sin_ventas_30d: 64, ageing_60d: 23, margen_cayendo: 11, sin_producto: 12 },
  },
  rows: TODO_ROWS,
};
