import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PROMO_TYPES } from '../constants/promoTypes';
import { COLORES_DISPONIBLES } from '../utils/productosConstants';

/**
 * usePublicacionesMLFilters -- URL state of the Publicaciones ML screen
 * (publicaciones-ml-vista P11a, S9.1). Every filter, the sort, the page and
 * the selection live in the query string, so a shared link or a reload shows
 * what the operator was looking at. Same convention as `useVentasMLFilters`:
 * CSV params, deleted (never written empty) when cleared.
 *
 * Two groups of params:
 *  - FILTERS (`FILTER_KEYS`): what the list is made of. Changing one goes back
 *    to page 1 and closes the selection, and asks the backend for fresh facet
 *    counts.
 *  - VIEW state (`pagina`, `sel`, `tab`, `prod`): moves inside the same result set.
 *    `prod` is the product row whose panel is open (`/view/products` `key`, `0` = "Sin producto").
 *    The sort (`orden`, `dir`) and the page size (`limite`) also go back to
 *    page 1 but need no new facets.
 *    `vista` (`producto` = the product rows, `agrupado` = the tree) and `familias` (family nodes in the tree)
 *    choose how the set is shown: they go back to page 1 and close the
 *    selection too, but are not filters (no new facets). So does `agrupar`,
 *    the dimension the tree is grouped by (`AGRUPAR_DIMENSIONS`, default marca).
 */
export const PAGE_SIZE = 50;
// The backend caps `limit` at 100.
export const PAGE_SIZES = [25, 50, 100];

const CSV_KEYS = [
  'estado',
  'estado_excluir',
  'tiendas',
  'marcas',
  'categorias',
  'subcategorias',
  'pms',
  'tipo',
  'vinculo',
  'stock',
  'evento',
  'colores',
];
// Productos' color filter (`?colores=`): its colors and `sin_color`, on the layer on show (`equipo`).
export const COLOR_FILTER_VALUES = [...COLORES_DISPONIBLES.filter((c) => c.id).map((c) => c.id), 'sin_color'];
// `markup_neg` is '1' or '' (a text key, so an inactive toggle reads as empty);
// the three markup params only exist for users with `ml_metricas.ver_ganancia`.
const TEXT_KEYS = ['q', 'familia', 'evento_desde', 'markup_neg', 'markup_min', 'markup_max'];
/**
 * Productos' "Filtros de Presencia", with Productos' URL keys and values (`useProductosFilters`): each one is a
 * single value or '' (no filter). `PRESENCE_PARAMS` is what each value asks the backend, the same params as
 * `GET /productos` (`construirFiltrosParams`).
 */
const PRESENCE_PARAMS = {
  rebate: { con_rebate: { con_rebate: true }, sin_rebate: { con_rebate: false } },
  oferta: { con_oferta: { con_oferta: true }, sin_oferta: { con_oferta: false } },
  webtransf: { con_web_transf: { con_web_transf: true }, sin_web_transf: { con_web_transf: false } },
  tiendanube: {
    con_descuento: { tn_con_descuento: true },
    sin_descuento: { tn_sin_descuento: true },
    no_publicado: { tn_no_publicado: true },
  },
  outofcards: { con_out_of_cards: { out_of_cards: true }, sin_out_of_cards: { out_of_cards: false } },
  precio: { con_precio: { con_precio: true }, sin_precio: { con_precio: false } },
  nuevos: { ultimos_7_dias: { nuevos_ultimos_7_dias: true } },
};
export const PRESENCE_VALUES = Object.fromEntries(
  Object.entries(PRESENCE_PARAMS).map(([key, values]) => [key, Object.keys(values)]),
);
const PRESENCE_KEYS = Object.keys(PRESENCE_PARAMS);
/**
 * Productos' markup filters (`mkclasica` ... with `positivo` / `negativo`), its stored markups of the linked product:
 * a filter of the query (every view, the KPIs and the bulk set apply it), but a margin figure, so they are read from
 * the URL only for a user with `ml_metricas.ver_ganancia` -- the backend refuses them otherwise.
 */
const MARKUP_SIGN_PARAMS = {
  mkclasica: 'markup_clasica_positivo',
  mkrebate: 'markup_rebate_positivo',
  mkoferta: 'markup_oferta_positivo',
  mkwebtransf: 'markup_web_transf_positivo',
};
const MARKUP_SIGN_KEYS = Object.keys(MARKUP_SIGN_PARAMS);
const MARKUP_SIGNS = ['positivo', 'negativo'];
/** Productos' audit filter: its URL keys (`useProductosFilters`) and the `GET /productos` param each one sends. */
const AUDIT_CSV_PARAMS = { audit_usuarios: 'audit_usuarios', audit_tipos: 'audit_tipos_accion' };
const AUDIT_TEXT_PARAMS = { audit_desde: 'audit_fecha_desde', audit_hasta: 'audit_fecha_hasta' };
const AUDIT_KEYS = [...Object.keys(AUDIT_CSV_PARAMS), ...Object.keys(AUDIT_TEXT_PARAMS)];
/**
 * Productos' promo filter and its "Precios mayoristas" (`useProductosFilters`): `promo_tipos` (csv of
 * `PROMO_TYPES`), `promo_estado` ('' = disponible) and `pxq` ('con_pxq' or ''). Sent as `GET /productos` sends them
 * (`construirFiltrosParams`): the types with their state, else the state alone as the legacy booleans.
 */
const PROMO_TYPE_VALUES = PROMO_TYPES.map(({ type }) => type);
export const PROMO_STATES = ['aplicada', 'sin_aplicar'];
const PROMO_KEYS = ['promo_tipos', 'promo_estado', 'pxq'];
export const FILTER_KEYS = [...TEXT_KEYS, ...CSV_KEYS, ...PRESENCE_KEYS, ...MARKUP_SIGN_KEYS, ...AUDIT_KEYS, ...PROMO_KEYS];

// `producto` = one row per product, opening into its publications (`/view/products`).
const VISTAS = ['publicacion', 'producto', 'agrupado'];
// The dimensions `GET /ml-publications/view/groups` takes, the default first; the picker offers exactly these.
// They are Métricas ML's five, in its order (`DIMENSION_OPTIONS`).
export const AGRUPAR_DIMENSIONS = ['marca', 'categoria', 'subcategoria', 'tienda', 'pm'];
// How the result is shown, not what it is made of: kept by "Limpiar filtros".
const SHAPE_KEYS = ['vista', 'familias', 'agrupar'];
// The team whose color layer paints the rows ('' = the global layer, as in Productos): how the rows are looked at,
// so it neither resets the page nor goes away with "Limpiar filtros".
const LAYER_KEY = 'equipo';
// Which of Productos' price columns show (S11): Normal (clásica, rebate, oferta, web), Cuotas or PVP. Like the
// layer, how the rows are looked at: no request, no page reset, kept by "Limpiar filtros".
export const PRICE_MODES = ['normal', 'cuotas', 'pvp'];
const MODE_KEY = 'modo';
const KEPT_ON_RESET = [...SHAPE_KEYS, LAYER_KEY, MODE_KEY];
const DIRECTIONS = ['asc', 'desc'];
const SORT_KEYS = ['orden', 'dir', 'limite'];
const VIEW_KEYS = ['pagina', 'sel', 'tab', 'prod'];

/**
 * The sorts of the list. A column sort's key IS the backend's `orden`; `DEFAULT_DIRECTION` mirrors the backend's
 * default per sort. The Métricas ML sorts rank the whole filtered set by Métricas' figures and are the backend's
 * too: `ml_metricas.ver` for all of them, `ml_metricas.ver_ganancia` also for the margin ones (403 otherwise).
 */
export const DEFAULT_DIRECTION = {
  actividad: 'desc',
  titulo: 'asc',
  precio: 'asc',
  stock_propio: 'desc',
  stock_full: 'desc',
  stock_erp: 'desc',
  // The linked product's, as Productos sorts them: A to Z, the cheapest first.
  codigo: 'asc',
  marca: 'asc',
  costo: 'asc',
  // Worst variation first: the most negative markup on top.
  markup: 'asc',
  // Métricas' figures: highest first, as Métricas orders them.
  unidades_7d: 'desc',
  unidades_30d: 'desc',
  markup_30d: 'desc',
  facturado_30d: 'desc',
  total_gauss_30d: 'desc',
};

const SALES_SORTS = new Set(['unidades_7d', 'unidades_30d', 'facturado_30d', 'markup_30d', 'total_gauss_30d']);
const MARGIN_SORTS = new Set(['markup', 'markup_30d', 'total_gauss_30d', 'costo']);

/** Métricas' default (Facturado 30D) for who sees the sales; the activity otherwise. */
export const defaultSortFor = ({ canSeeSales = false } = {}) => (canSeeSales ? 'facturado_30d' : 'actividad');

const mayAsk = (orden, { canSeeSales = false, canSeeMargin = false }) =>
  (!SALES_SORTS.has(orden) || canSeeSales) && (!MARGIN_SORTS.has(orden) || canSeeMargin);

/**
 * The sort the list really applies: the URL's when the user may ask for it, else the default -- a link shared by
 * someone with more permissions still opens the list. Its direction is the URL's only with the URL's sort.
 */
export function effectiveSort(filters, permissions = {}) {
  const asked = filters.orden && mayAsk(filters.orden, permissions) ? filters.orden : '';
  const key = asked || defaultSortFor(permissions);
  return { key, dir: (asked && filters.dir) || DEFAULT_DIRECTION[key] || 'desc' };
}

/**
 * The sorts of the Producto view (`/view/products` `orden`): Métricas ML's figures of a product and its name. A sort
 * of the publication list the products have no figure for (price, stock...) is not one of them.
 */
export const PRODUCT_SORTS = ['titulo', 'unidades_7d', 'unidades_30d', 'markup_30d', 'facturado_30d', 'total_gauss_30d'];

/**
 * The sort the Producto view really applies: the URL's when the products can be sorted by it and the user may ask
 * for it, else Métricas' default (Facturado 30D) for who sees the sales and the name otherwise.
 */
export function effectiveProductSort(filters, permissions = {}) {
  const asked = PRODUCT_SORTS.includes(filters.orden) && mayAsk(filters.orden, permissions) ? filters.orden : '';
  const key = asked || (permissions.canSeeSales ? 'facturado_30d' : 'titulo');
  return { key, dir: (asked && filters.dir) || DEFAULT_DIRECTION[key] || 'desc' };
}

const csv = (value) => (value ? value.split(',').filter(Boolean) : []);

// The old "Sin stock ML" chip (`sin_stock`, ML's available, a sum) left the screen with the summed column: a saved
// or shared link that still carries it opens with the closest chip of today, "Sin stock propio", active.
const LEGACY_STOCK = { sin_stock: 'propio_sin_stock' };

function currentStockValues(values) {
  return [...new Set(values.map((value) => LEGACY_STOCK[value] ?? value))];
}

function readFilters(params, { canSeeMargin = false } = {}) {
  const filters = {};
  for (const key of TEXT_KEYS) filters[key] = params.get(key) ?? '';
  for (const key of CSV_KEYS) filters[key] = csv(params.get(key));
  filters.stock = currentStockValues(filters.stock);
  filters.colores = filters.colores.filter((value) => COLOR_FILTER_VALUES.includes(value));
  for (const key of PRESENCE_KEYS) {
    const value = params.get(key);
    filters[key] = PRESENCE_VALUES[key].includes(value) ? value : '';
  }
  for (const key of MARKUP_SIGN_KEYS) {
    const value = params.get(key);
    filters[key] = canSeeMargin && MARKUP_SIGNS.includes(value) ? value : '';
  }
  for (const key of Object.keys(AUDIT_CSV_PARAMS)) filters[key] = csv(params.get(key));
  for (const key of Object.keys(AUDIT_TEXT_PARAMS)) filters[key] = params.get(key) ?? '';
  filters.promo_tipos = csv(params.get('promo_tipos')).filter((type) => PROMO_TYPE_VALUES.includes(type));
  filters.promo_estado = PROMO_STATES.includes(params.get('promo_estado')) ? params.get('promo_estado') : '';
  filters.pxq = params.get('pxq') === 'con_pxq' ? 'con_pxq' : '';
  // One reading for the switch and the request: only `1` / `true` mean on.
  filters.markup_neg = ['1', 'true'].includes(params.get('markup_neg')) ? '1' : '';
  const vista = params.get('vista');
  filters.vista = VISTAS.includes(vista) ? vista : 'publicacion';
  // The tree's family nodes: '1' or '' (a toggle, off by default).
  filters.familias = ['1', 'true'].includes(params.get('familias')) ? '1' : '';
  const agrupar = params.get('agrupar');
  filters.agrupar = AGRUPAR_DIMENSIONS.includes(agrupar) ? agrupar : AGRUPAR_DIMENSIONS[0];
  filters.orden = params.get('orden') ?? '';
  const dir = params.get('dir');
  filters.dir = DIRECTIONS.includes(dir) ? dir : '';
  const pagina = Number.parseInt(params.get('pagina'), 10);
  filters.pagina = Number.isInteger(pagina) && pagina >= 1 ? pagina : 1;
  const limite = Number.parseInt(params.get('limite'), 10);
  filters.limite = PAGE_SIZES.includes(limite) ? limite : PAGE_SIZE;
  filters.sel = params.get('sel') ?? '';
  filters.tab = params.get('tab') ?? '';
  filters.prod = params.get('prod') ?? '';
  filters.equipo = params.get(LAYER_KEY) ?? '';
  const modo = params.get(MODE_KEY);
  filters.modo = PRICE_MODES.includes(modo) ? modo : PRICE_MODES[0];
  return filters;
}

const isEmpty = (value) => value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0);

/**
 * The `GET /ml-publications/view/items` query for these filters. The URL keeps
 * the store chips' vocabulary (`sin_tienda`); the backend's is `none`.
 * `vista`, `sel`, `tab`, `prod` and `pagina` never reach the backend as such.
 *
 * The markup filters and the margin sorts are sent only with `canSeeMargin`
 * (`ml_metricas.ver_ganancia`), the Métricas sorts only with `canSeeSales`
 * (`ml_metricas.ver`): the backend refuses them with a 403 otherwise, and a
 * link shared by someone who has the permission must still open the list for
 * someone who has not (with the default sort, see `effectiveSort`).
 */
export function buildItemsParams(
  filters,
  pageSize = filters.limite ?? PAGE_SIZE,
  { canSeeMargin = false, canSeeSales = false } = {},
) {
  const params = {};
  const q = filters.q.trim();
  if (q) params.q = q;
  for (const key of ['familia', 'evento_desde']) {
    if (filters[key]) params[key] = filters[key];
  }
  if (filters.orden && mayAsk(filters.orden, { canSeeMargin, canSeeSales })) {
    params.orden = filters.orden;
    if (filters.dir) params.dir = filters.dir;
  } else if (canSeeSales) {
    // Métricas' default sort has to be asked for: the backend's own default is the activity. Its direction too,
    // so the request says what the header shows instead of leaning on the backend's default.
    params.orden = defaultSortFor({ canSeeSales });
    params.dir = DEFAULT_DIRECTION[params.orden];
  }
  if (canSeeMargin) {
    if (filters.markup_neg) params.markup_neg = true;
    for (const key of ['markup_min', 'markup_max']) {
      // The operator may type a decimal comma; the backend reads a point.
      const bound = filters[key].trim().replace(',', '.');
      if (bound) params[key] = bound;
    }
  }
  for (const key of CSV_KEYS) {
    // A filter set built before `colores` existed (a caller's own object) has no such key: nothing to send.
    const raw = filters[key] ?? [];
    const values = key === 'tiendas' ? raw.map((v) => (v === 'sin_tienda' ? 'none' : v)) : raw;
    if (values.length > 0) params[key] = values.join(',');
  }
  for (const key of PRESENCE_KEYS) {
    if (filters[key]) Object.assign(params, PRESENCE_PARAMS[key][filters[key]]);
  }
  for (const key of MARKUP_SIGN_KEYS) {
    if (filters[key]) params[MARKUP_SIGN_PARAMS[key]] = filters[key] === 'positivo';
  }
  for (const [key, param] of Object.entries(AUDIT_CSV_PARAMS)) {
    if (filters[key]?.length > 0) params[param] = filters[key].join(',');
  }
  for (const [key, param] of Object.entries(AUDIT_TEXT_PARAMS)) {
    if (filters[key]) params[param] = filters[key];
  }
  if (filters.promo_tipos?.length > 0) {
    params.promo_tipos = filters.promo_tipos.join(',');
    params.promo_estado = filters.promo_estado || 'disponible';
  } else if (filters.promo_estado === 'aplicada') {
    params.con_promo_aplicada = true;
  } else if (filters.promo_estado === 'sin_aplicar') {
    params.con_promo_sin_aplicar = true;
  }
  if (filters.pxq === 'con_pxq') params.con_pxq = true;
  if (filters.equipo) params.equipo_id = filters.equipo;
  params.limit = pageSize;
  params.offset = (filters.pagina - 1) * pageSize;
  return params;
}

/**
 * The `GET /ml-publications/view/products` query: the list's filters, the Producto view's own sort and the page.
 * Never the markup filters: `/products` does not apply them (its figures are Métricas', over the whole selection).
 */
export function buildProductsParams(filters, pageSize = filters.limite ?? PAGE_SIZE, permissions = {}) {
  const { orden, dir, ...params } = buildItemsParams(filters, pageSize, { canSeeMargin: false });
  void orden, dir;
  const sort = effectiveProductSort(filters, permissions);
  return { ...params, orden: sort.key, dir: sort.dir };
}

/**
 * The CSV export's query for the current view: exactly what its list asks (`/items` for Publicación, `/products` for
 * Producto, with the same permissions), without the page -- the file holds every row of the list, in its order.
 */
export function buildExportParams(filters, permissions = {}) {
  const build = filters.vista === 'producto' ? buildProductsParams : buildItemsParams;
  const { limit, offset, ...params } = build(filters, undefined, permissions);
  void limit, offset;
  return withLayerOnlyForColors(params);
}

const MARKUP_KEYS = ['markup_neg', 'markup_min', 'markup_max'];

/**
 * The strip, the bulk set and the export show no row color, so they never ask the layer -- unless the color filter
 * is on: then the layer says which products it keeps, and they must count the very products the list shows.
 */
function withLayerOnlyForColors(params) {
  if (params.colores) return params;
  const { equipo_id, ...rest } = params;
  void equipo_id;
  return rest;
}

/** True when a markup filter narrows the list. The list applies it after the query, so the KPIs cannot. */
export const hasMarkupFilter = (filters) => MARKUP_KEYS.some((key) => filters[key] !== '');

/**
 * The `GET /ml-publications/view/kpis` query: the list's filters plus the strip's own `periodo`. No paging, no
 * sort, and never the markup filters (the backend computes the strip before them): the strip says so instead.
 */
export function buildKpiParams(filters, periodo) {
  const { orden, dir, limit, offset, ...params } = withLayerOnlyForColors(
    buildItemsParams(filters, 1, { canSeeMargin: false }),
  );
  void orden, dir, limit, offset;
  // The Producto view's rows ask mejor oferta of the product (any of its publications); its strip asks it the same
  // way, so the strip counts the publications the rows hold.
  if (filters.vista === 'producto' && filters.oferta) params.oferta_por_producto = true;
  return { ...params, periodo };
}

/**
 * The `GET /ml-publications/view/product-ids` query: the products a bulk pricing action acts on are the linked
 * products of the publications these filters select, asked exactly as the KPI strip asks its publications (the
 * list's filters, mejor oferta of the product in the Producto view), with no sort nor paging. The markup filters are
 * left to the caller: `BulkActions` adds them exactly as `/items` gets them, only where the list applies them.
 */
export function buildProductIdsParams(filters) {
  const { periodo, ...params } = buildKpiParams(filters);
  void periodo;
  return params;
}

export function usePublicacionesMLFilters({ canSeeMargin = false } = {}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => readFilters(searchParams, { canSeeMargin }), [searchParams, canSeeMargin]);

  // Stable while only the page / sort / selection change: the page compares
  // it to know when the facet counts must be asked for again.
  // With a color filter on, the layer chooses the colored products, so it is part of the set.
  const filterKey = useMemo(
    () => JSON.stringify([...FILTER_KEYS.map((key) => filters[key]), filters.colores?.length ? filters.equipo : '']),
    [filters],
  );

  const setFilters = useCallback(
    (updates) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(updates)) {
          if (isEmpty(value)) next.delete(key);
          else next.set(key, Array.isArray(value) ? value.join(',') : String(value));
        }
        const changed = Object.keys(updates);
        const touchesList = changed.some((key) => FILTER_KEYS.includes(key) || SORT_KEYS.includes(key) || SHAPE_KEYS.includes(key));
        if (touchesList) {
          for (const key of VIEW_KEYS) if (!changed.includes(key)) next.delete(key);
        }
        return next;
      });
    },
    [setSearchParams],
  );

  // Clears the filters, the sort and the page; the view (`vista`, `familias`, `agrupar`) and the color layer are how
  // the operator looks at the result, not filters, so they stay.
  const resetFilters = useCallback(
    () =>
      setSearchParams((prev) => {
        const next = new URLSearchParams();
        for (const key of KEPT_ON_RESET) if (prev.has(key)) next.set(key, prev.get(key));
        return next;
      }),
    [setSearchParams],
  );

  return { filters, filterKey, setFilters, resetFilters };
}

export default usePublicacionesMLFilters;
