import api from './api';

/**
 * Fetches the product ranking from the backend.
 *
 * @param {Object} params
 * @param {number} params.page - Page number (1-based)
 * @param {number} params.page_size - Items per page (1-200)
 * @param {string} params.sort_by - Column to sort by
 * @param {string} params.sort_dir - Sort direction: 'asc' | 'desc'
 * @param {string|null} params.marca - Filter by brand
 * @param {string|null} params.categoria - Filter by category
 * @param {string|null} params.pm - Filter by PM username (or 'sin_pm')
 * @param {number[]} params.stor_ids - Depot IDs (default [1])
 * @param {number} params.ventana_dias - Sales window in days: 30|60|90|180
 * @returns {Promise<{ items: Object[], total: number, page: number, page_size: number }>}
 */
export async function getRanking(params = {}) {
  const {
    page = 1,
    page_size = 50,
    sort_by = 'dias_sin_venta',
    sort_dir = 'desc',
    marca = null,
    categoria = null,
    pm = null,
    stor_ids = [1],
    ventana_dias = 90,
  } = params;

  const queryParams = {
    page,
    page_size,
    sort_by,
    sort_dir,
    ventana_dias,
    stor_ids,
  };

  if (marca) queryParams.marca = marca;
  if (categoria) queryParams.categoria = categoria;
  if (pm) queryParams.pm = pm;

  const response = await api.get('/consultas/ranking', {
    params: queryParams,
    // axios serializes arrays as repeated keys by default, which FastAPI expects
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
