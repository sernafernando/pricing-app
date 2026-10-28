import { businessToday, calcularRangoPreset } from './dateRangePresets';
import { DIMENSION_OPTIONS } from './metricasMlLevels';

/**
 * The Métricas ML view in the query string (metricas-ml-tablero U1, audit B3): a reload keeps it, and a filtered
 * view can be bookmarked or shared. Same convention as `usePublicacionesMLFilters`: CSV params, a param that holds
 * its default is never written. This module owns the view's defaults (`defaultView`).
 *
 * `readMetricasUrl` returns the whole view: the default where the URL says nothing or says something invalid. The
 * closed sets (period, compare, grouping, dimension, sort, the publication/alert/stock/ageing chips) and the ids
 * are checked, and an unknown value is dropped; the free text (search, brand and category names, the store chip)
 * goes as written -- the board answers for those. A preset period (`periodo=7d`) is read relative to today, so a
 * saved link keeps meaning "the last 7 days"; a custom one carries its dates (`periodo=custom&desde=&hasta=`).
 * The view modes (Publicidad, Costos TP), the page and the open rows stay out of it.
 */

export const DEFAULT_PRESET = 'mesActual';
const PRESETS = new Set(['hoy', 'ayer', '3d', '7d', '14d', '30d', 'mesActual', '3m']);
const GROUP_BY = new Set(['product', 'publication', 'group']);
const COMPARE = new Set(['periodo_anterior', 'anio_anterior']);
const DIMENSIONS = new Set(DIMENSION_OPTIONS.map((option) => option.value));
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

// State key -> URL param and the values the board knows, for the chip lists.
// The board's sets (`board.PUB_STATUSES`, `PUB_TYPES`, `STOCK_BUCKETS`, `AGEING_BUCKETS`, `ALERTS`).
const PUB_STATUS = ['active', 'paused', 'closed', 'under_review'];
const PUB_TYPE = ['clasica', 'premium', 'catalogo', 'full'];
const STOCK = ['con_stock', 'sin_stock', 'sin_dato'];
const AGEING = ['up_to_30', 'from_31_to_60', 'over_60'];
const LISTS = {
  pubStatus: ['estado', PUB_STATUS],
  pubType: ['tipo', PUB_TYPE],
  pubStatusExclude: ['estado_excluir', PUB_STATUS],
  pubTypeExclude: ['tipo_excluir', PUB_TYPE],
  alerts: ['alertas', ['sin_ventas_30d', 'ageing_60d', 'margen_cayendo']],
  stock: ['stock', STOCK],
  stockExclude: ['stock_excluir', STOCK],
  ageing: ['ageing', AGEING],
  ageingExclude: ['ageing_excluir', AGEING],
};
// `productFilters` key -> whether its values are ids (numbers) rather than names.
const PRODUCT_LISTS = { marcas: false, categorias: false, subcategorias: true, pms: true };

// Every param this module reads or writes: the others in the URL are not its to touch.
const OWN_PARAMS = [
  'periodo',
  'desde',
  'hasta',
  'comparar',
  'agrupar',
  'dimension',
  'q',
  'tienda',
  'solo_ventas',
  'orden',
  'dir',
  ...Object.keys(PRODUCT_LISTS),
  ...Object.values(LISTS).map(([param]) => param),
];

/** The view with nothing chosen: the current month, by product, every filter off, by gross. */
export function defaultView(today = businessToday()) {
  return {
    range: { ...calcularRangoPreset(DEFAULT_PRESET, today), filtro: DEFAULT_PRESET },
    compararCon: 'periodo_anterior',
    groupBy: 'product',
    dimension: 'marca',
    searchQuery: '',
    productFilters: { marcas: [], categorias: [], subcategorias: [], pms: [] },
    storeFilter: '',
    ...Object.fromEntries(Object.keys(LISTS).map((key) => [key, []])),
    soloConVentas: true,
    sort: { key: 'gross', desc: true },
  };
}

const csv = (params, key) => (params.get(key) || '').split(',').filter(Boolean);

// A real calendar day: `2026-02-30` matches the pattern but is no date.
function isDate(value) {
  if (!ISO_DATE.test(value || '')) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value);
}

function readRange(params, today) {
  const periodo = params.get('periodo');
  if (periodo === 'custom') {
    const desde = params.get('desde');
    const hasta = params.get('hasta');
    if (!isDate(desde) || !isDate(hasta) || desde > hasta) return undefined;
    return { desde, hasta, filtro: 'custom' };
  }
  if (!PRESETS.has(periodo)) return undefined;
  return { ...calcularRangoPreset(periodo, today), filtro: periodo };
}

export function readMetricasUrl(params, { sortKeys, today = businessToday() }) {
  const view = defaultView(today);
  const range = readRange(params, today);
  if (range) view.range = range;
  if (COMPARE.has(params.get('comparar'))) view.compararCon = params.get('comparar');
  if (GROUP_BY.has(params.get('agrupar'))) view.groupBy = params.get('agrupar');
  if (DIMENSIONS.has(params.get('dimension'))) view.dimension = params.get('dimension');
  if (params.get('q')) view.searchQuery = params.get('q');
  if (params.get('tienda')) view.storeFilter = params.get('tienda');
  if (params.get('solo_ventas') === '0') view.soloConVentas = false;

  for (const [key, ids] of Object.entries(PRODUCT_LISTS)) {
    const values = csv(params, key);
    view.productFilters[key] = ids ? values.map(Number).filter(Number.isInteger) : values;
  }
  for (const [key, [param, known]] of Object.entries(LISTS)) {
    view[key] = csv(params, param).filter((value) => known.includes(value));
  }

  const orden = params.get('orden');
  const dir = params.get('dir');
  if (sortKeys.has(orden) && (dir === 'asc' || dir === 'desc')) view.sort = { key: orden, desc: dir === 'desc' };
  return view;
}

/** `current` with the view's params rewritten: what is at its default goes, a param of someone else stays. */
export function writeMetricasUrl(view, current = new URLSearchParams()) {
  const params = new URLSearchParams(current);
  OWN_PARAMS.forEach((param) => params.delete(param));
  const defaults = defaultView();
  const { range } = view;
  if (range.filtro === 'custom') {
    params.set('periodo', 'custom');
    params.set('desde', range.desde);
    params.set('hasta', range.hasta);
  } else if (range.filtro !== DEFAULT_PRESET) {
    params.set('periodo', range.filtro);
  }
  if (view.compararCon !== defaults.compararCon) params.set('comparar', view.compararCon);
  if (view.groupBy !== defaults.groupBy) params.set('agrupar', view.groupBy);
  if (view.dimension !== defaults.dimension) params.set('dimension', view.dimension);
  if (view.searchQuery) params.set('q', view.searchQuery);
  for (const key of Object.keys(PRODUCT_LISTS)) {
    if (view.productFilters[key]?.length) params.set(key, view.productFilters[key].join(','));
  }
  if (view.storeFilter) params.set('tienda', view.storeFilter);
  for (const [key, [param]] of Object.entries(LISTS)) {
    if (view[key].length) params.set(param, view[key].join(','));
  }
  if (!view.soloConVentas) params.set('solo_ventas', '0');
  if (view.sort.key !== defaults.sort.key || view.sort.desc !== defaults.sort.desc) {
    params.set('orden', view.sort.key);
    params.set('dir', view.sort.desc ? 'desc' : 'asc');
  }
  return params;
}
