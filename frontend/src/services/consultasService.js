import api from './api';

/**
 * Fetches the product ranking from the backend.
 *
 * @param {Object} params
 * @param {number} params.page - Page number (1-based)
 * @param {number} params.page_size - Items per page (1-200)
 * @param {Array<{campo: string, dir: string}>} params.sort - Ordered sort list, each entry { campo, dir }
 * @param {string|null} params.marca - Filter by brand
 * @param {string|null} params.categoria - Filter by category
 * @param {string|null} params.pm - Filter by PM username (or 'sin_pm')
 * @param {number[]} params.stor_ids - Depot IDs (default [1])
 * @param {number} params.ventana_dias - Sales window in days: 30|60|90|180
 * @param {boolean} params.incluir_sin_stock - Include products with zero stock (default false)
 * @param {boolean} params.incluir_combos - Include combo/production parents (default false)
 * @returns {Promise<{ items: Object[], total: number, page: number, page_size: number }>}
 */
export async function getRanking(params = {}) {
  const {
    page = 1,
    page_size = 50,
    sort = [{ campo: 'dias_sin_venta', dir: 'desc' }],
    marca = null,
    categoria = null,
    pm = null,
    stor_ids = [1],
    ventana_dias = 90,
    incluir_sin_stock = false,
    incluir_combos = false,
  } = params;

  const queryParams = {
    page,
    page_size,
    ventana_dias,
    stor_ids,
    incluir_sin_stock,
    incluir_combos,
  };

  if (marca) queryParams.marca = marca;
  if (categoria) queryParams.categoria = categoria;
  if (pm) queryParams.pm = pm;

  // Multi-sort: serialize as repeated 'sort=campo:dir' params
  // (FastAPI expects list[str] via repeated query key)
  const sortEntries = sort.map(({ campo, dir }) => `${campo}:${dir}`);

  const response = await api.get('/consultas/ranking', {
    params: { ...queryParams, sort: sortEntries },
    paramsSerializer: (p) => {
      const parts = [];
      for (const [key, value] of Object.entries(p)) {
        if (Array.isArray(value)) {
          value.forEach((v) => parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(v)}`));
        } else {
          parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
        }
      }
      return parts.join('&');
    },
  });

  return response.data;
}

/**
 * Fetches the ranking filter facets (marcas, categorias, pms, depositos).
 * Used to populate dropdowns in RankingFilters.
 *
 * @returns {Promise<{
 *   marcas: string[],
 *   categorias: string[],
 *   pms: string[],
 *   depositos: Array<{id: number, label: string}>
 * }>}
 */
export async function getRankingFacets() {
  const response = await api.get('/consultas/ranking/facets');
  return response.data;
}
