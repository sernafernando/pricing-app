import { businessToday, calcularRangoPreset } from './dateRangePresets';
import { DIMENSION_OPTIONS } from './metricasMlLevels';

/**
 * The Métricas ML filters in the query string (metricas-ml-tablero U1, audit B3): a reload keeps the view, and a
 * filtered view can be bookmarked or shared. Same convention as `usePublicacionesMLFilters`: CSV params, a param
 * that holds its default is never written.
 *
 * `readMetricasUrl` returns only what the URL sets AND is valid (the page keeps its defaults for the rest); an
 * unknown value is dropped, never sent to the board. A preset period (`periodo=7d`) is read relative to today, so
 * a saved link keeps meaning "the last 7 days"; a custom one carries its dates (`periodo=custom&desde=&hasta=`).
 * The view modes (Publicidad, Costos TP), the page and the open rows stay out of it.
 */

const DEFAULT_PRESET = 'mesActual';
const PRESETS = new Set(['hoy', 'ayer', '3d', '7d', '14d', '30d', 'mesActual', '3m']);
const GROUP_BY = new Set(['product', 'publication', 'group']);
const COMPARE = new Set(['periodo_anterior', 'anio_anterior']);
const DIMENSIONS = new Set(DIMENSION_OPTIONS.map((option) => option.value));
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

// State key -> URL param, for the lists of strings.
const LISTS = {
  pubStatus: 'estado',
  pubType: 'tipo',
  pubStatusExclude: 'estado_excluir',
  pubTypeExclude: 'tipo_excluir',
  alerts: 'alertas',
  stock: 'stock',
  stockExclude: 'stock_excluir',
  ageing: 'ageing',
  ageingExclude: 'ageing_excluir',
};
// `productFilters` key -> whether its values are ids (numbers) rather than names.
const PRODUCT_LISTS = { marcas: false, categorias: false, subcategorias: true, pms: true };

const csv = (params, key) => (params.get(key) || '').split(',').filter(Boolean);

function readRange(params, today) {
  const periodo = params.get('periodo');
  if (periodo === 'custom') {
    const desde = params.get('desde');
    const hasta = params.get('hasta');
    if (!ISO_DATE.test(desde || '') || !ISO_DATE.test(hasta || '') || desde > hasta) return undefined;
    return { desde, hasta, filtro: 'custom' };
  }
  if (!PRESETS.has(periodo)) return undefined;
  return { ...calcularRangoPreset(periodo, today), filtro: periodo };
}

export function readMetricasUrl(params, { sortKeys, today = businessToday() }) {
  const state = {};
  const range = readRange(params, today);
  if (range) state.range = range;
  if (COMPARE.has(params.get('comparar'))) state.compararCon = params.get('comparar');
  if (GROUP_BY.has(params.get('agrupar'))) state.groupBy = params.get('agrupar');
  if (DIMENSIONS.has(params.get('dimension'))) state.dimension = params.get('dimension');
  if (params.get('q')) state.searchQuery = params.get('q');
  if (params.get('tienda')) state.storeFilter = params.get('tienda');
  if (params.get('solo_ventas') === '0') state.soloConVentas = false;

  state.productFilters = {};
  for (const [key, ids] of Object.entries(PRODUCT_LISTS)) {
    const values = csv(params, key);
    state.productFilters[key] = ids ? values.map(Number).filter(Number.isInteger) : values;
  }
  for (const [key, param] of Object.entries(LISTS)) {
    const values = csv(params, param);
    if (values.length) state[key] = values;
  }

  const orden = params.get('orden');
  const dir = params.get('dir');
  if (sortKeys.has(orden) && (dir === 'asc' || dir === 'desc')) state.sort = { key: orden, desc: dir === 'desc' };
  return state;
}

export function writeMetricasUrl(state) {
  const params = new URLSearchParams();
  const { range } = state;
  if (range.filtro === 'custom') {
    params.set('periodo', 'custom');
    params.set('desde', range.desde);
    params.set('hasta', range.hasta);
  } else if (range.filtro !== DEFAULT_PRESET) {
    params.set('periodo', range.filtro);
  }
  if (state.compararCon !== 'periodo_anterior') params.set('comparar', state.compararCon);
  if (state.groupBy !== 'product') params.set('agrupar', state.groupBy);
  if (state.dimension !== 'marca') params.set('dimension', state.dimension);
  if (state.searchQuery) params.set('q', state.searchQuery);
  for (const key of Object.keys(PRODUCT_LISTS)) {
    if (state.productFilters[key].length) params.set(key, state.productFilters[key].join(','));
  }
  if (state.storeFilter) params.set('tienda', state.storeFilter);
  for (const [key, param] of Object.entries(LISTS)) {
    if (state[key].length) params.set(param, state[key].join(','));
  }
  if (!state.soloConVentas) params.set('solo_ventas', '0');
  if (state.sort.key !== 'gross' || !state.sort.desc) {
    params.set('orden', state.sort.key);
    params.set('dir', state.sort.desc ? 'desc' : 'asc');
  }
  return params;
}
