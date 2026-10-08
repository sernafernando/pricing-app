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
const TEXT_KEYS = ['q', 'familia', 'evento_desde'];
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
  const vista = params.get('vista');
  filters.vista = VISTAS.includes(vista) ? vista : 'publicacion';
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
 */
export function buildItemsParams(filters, pageSize = filters.limite ?? PAGE_SIZE) {
  const params = {};
  const q = filters.q.trim();
  if (q) params.q = q;
  for (const key of ['familia', 'evento_desde', 'orden', 'dir']) {
    if (filters[key]) params[key] = filters[key];
  }
  for (const key of CSV_KEYS) {
    const values = key === 'tiendas' ? filters[key].map((v) => (v === 'sin_tienda' ? 'none' : v)) : filters[key];
    if (values.length > 0) params[key] = values.join(',');
  }
  params.limit = pageSize;
  params.offset = (filters.pagina - 1) * pageSize;
  return params;
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
        const touchesList = changed.some((key) => FILTER_KEYS.includes(key) || SORT_KEYS.includes(key) || key === 'vista');
        if (touchesList) {
          for (const key of VIEW_KEYS) if (!changed.includes(key)) next.delete(key);
        }
        return next;
      });
    },
    [setSearchParams],
  );

  const resetFilters = useCallback(() => setSearchParams(new URLSearchParams()), [setSearchParams]);

  return { filters, filterKey, setFilters, resetFilters };
}

export default usePublicacionesMLFilters;
