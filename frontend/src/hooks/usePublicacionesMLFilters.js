import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

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
 *  - VIEW state (`pagina`, `sel`, `tab`): moves inside the same result set.
 *    The sort (`orden`, `dir`) and the page size (`limite`) also go back to
 *    page 1 but need no new facets.
 *    `vista` (`agrupado` = the tree) and `familias` (family nodes in the tree)
 *    choose how the set is shown: they go back to page 1 and close the
 *    selection too, but are not filters (no new facets).
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
];
// `markup_neg` is '1' or '' (a text key, so an inactive toggle reads as empty);
// the three markup params only exist for users with `ml_metricas.ver_ganancia`.
const TEXT_KEYS = ['q', 'familia', 'evento_desde', 'markup_neg', 'markup_min', 'markup_max'];
export const FILTER_KEYS = [...TEXT_KEYS, ...CSV_KEYS];

const VISTAS = ['publicacion', 'agrupado'];
const DIRECTIONS = ['asc', 'desc'];
const SORT_KEYS = ['orden', 'dir', 'limite'];
const VIEW_KEYS = ['pagina', 'sel', 'tab'];

const csv = (value) => (value ? value.split(',').filter(Boolean) : []);

function readFilters(params) {
  const filters = {};
  for (const key of TEXT_KEYS) filters[key] = params.get(key) ?? '';
  for (const key of CSV_KEYS) filters[key] = csv(params.get(key));
  // One reading for the switch and the request: only `1` / `true` mean on.
  filters.markup_neg = ['1', 'true'].includes(params.get('markup_neg')) ? '1' : '';
  const vista = params.get('vista');
  filters.vista = VISTAS.includes(vista) ? vista : 'publicacion';
  // The tree's family nodes: '1' or '' (a toggle, off by default).
  filters.familias = ['1', 'true'].includes(params.get('familias')) ? '1' : '';
  filters.orden = params.get('orden') ?? '';
  const dir = params.get('dir');
  filters.dir = DIRECTIONS.includes(dir) ? dir : '';
  const pagina = Number.parseInt(params.get('pagina'), 10);
  filters.pagina = Number.isInteger(pagina) && pagina >= 1 ? pagina : 1;
  const limite = Number.parseInt(params.get('limite'), 10);
  filters.limite = PAGE_SIZES.includes(limite) ? limite : PAGE_SIZE;
  filters.sel = params.get('sel') ?? '';
  filters.tab = params.get('tab') ?? '';
  return filters;
}

const isEmpty = (value) => value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0);

/**
 * The `GET /ml-publications/view/items` query for these filters. The URL keeps
 * the store chips' vocabulary (`sin_tienda`); the backend's is `none`.
 * `vista`, `sel`, `tab` and `pagina` never reach the backend as such.
 *
 * The markup filters and the markup sort are sent only with `canSeeMargin`
 * (`ml_metricas.ver_ganancia`): the backend refuses them with a 403 otherwise,
 * and a link shared by someone who has the permission must still open the list
 * for someone who has not.
 */
export function buildItemsParams(filters, pageSize = filters.limite ?? PAGE_SIZE, { canSeeMargin = false } = {}) {
  const params = {};
  const q = filters.q.trim();
  if (q) params.q = q;
  for (const key of ['familia', 'evento_desde']) {
    if (filters[key]) params[key] = filters[key];
  }
  if (canSeeMargin || filters.orden !== 'markup') {
    for (const key of ['orden', 'dir']) {
      if (filters[key]) params[key] = filters[key];
    }
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
    const values = key === 'tiendas' ? filters[key].map((v) => (v === 'sin_tienda' ? 'none' : v)) : filters[key];
    if (values.length > 0) params[key] = values.join(',');
  }
  params.limit = pageSize;
  params.offset = (filters.pagina - 1) * pageSize;
  return params;
}

const MARKUP_KEYS = ['markup_neg', 'markup_min', 'markup_max'];

/** True when a markup filter narrows the list. The list applies it after the query, so the KPIs cannot. */
export const hasMarkupFilter = (filters) => MARKUP_KEYS.some((key) => filters[key] !== '');

/**
 * The `GET /ml-publications/view/kpis` query: the list's filters plus the strip's own `periodo`. No paging, no
 * sort, and never the markup filters (the backend computes the strip before them): the strip says so instead.
 */
export function buildKpiParams(filters, periodo) {
  const { orden, dir, limit, offset, ...params } = buildItemsParams(filters, 1, { canSeeMargin: false });
  void orden, dir, limit, offset;
  return { ...params, periodo };
}

export function usePublicacionesMLFilters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);

  // Stable while only the page / sort / selection change: the page compares
  // it to know when the facet counts must be asked for again.
  const filterKey = useMemo(
    () => JSON.stringify(FILTER_KEYS.map((key) => filters[key])),
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
        const touchesList = changed.some((key) => FILTER_KEYS.includes(key) || SORT_KEYS.includes(key) || key === 'vista' || key === 'familias');
        if (touchesList) {
          for (const key of VIEW_KEYS) if (!changed.includes(key)) next.delete(key);
        }
        return next;
      });
    },
    [setSearchParams],
  );

  // Clears the filters, the sort and the page; the view (`vista`, `familias`) is how the operator looks at
  // the result, not a filter, so it stays.
  const resetFilters = useCallback(
    () =>
      setSearchParams((prev) => {
        const next = new URLSearchParams();
        for (const key of ['vista', 'familias']) if (prev.has(key)) next.set(key, prev.get(key));
        return next;
      }),
    [setSearchParams],
  );

  return { filters, filterKey, setFilters, resetFilters };
}

export default usePublicacionesMLFilters;
