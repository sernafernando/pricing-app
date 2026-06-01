import api from './api';

/**
 * Fetches the product ranking from the backend.
 *
 * @param {Object} params
 * @param {number} params.page - Page number (1-based)
 * @param {number} params.page_size - Items per page (1-200)
 * @param {Array<{columna: string, direccion: string}>} params.sort - Ordered sort list, each entry { columna, direccion } (mirrors Productos.jsx ordenColumnas)
 * @param {string|null} params.marca - Filter by brand
 * @param {string|null} params.categoria - Filter by category
 * @param {string|null} params.pm - Filter by PM username (or 'sin_pm')
 * @param {number[]} params.stor_ids - Depot IDs (default [1])
 * @param {boolean} params.incluir_sin_stock - Include products with zero stock (default false)
 * @param {boolean} params.incluir_combos - Include combo/production parents (default false)
 * @returns {Promise<{ items: Object[], total: number, page: number, page_size: number }>}
 */
export async function getRanking(params = {}) {
  const {
    page = 1,
    page_size = 50,
    sort = [{ columna: 'dias_sin_venta', direccion: 'desc' }],
    marca = null,
    categoria = null,
    pm = null,
    stor_ids = [1],
    incluir_sin_stock = false,
    incluir_combos = false,
    q = null,
  } = params;

  const queryParams = {
    page,
    page_size,
    stor_ids,
    incluir_sin_stock,
    incluir_combos,
  };

  if (marca) queryParams.marca = marca;
  if (categoria) queryParams.categoria = categoria;
  if (pm) queryParams.pm = pm;
  if (q) queryParams.q = q;

  // Multi-sort: parallel comma-separated lists (matches Productos.jsx pattern)
  // Backend: orden_campos=dias_sin_venta,total_stock&orden_direcciones=desc,asc
  if (sort && sort.length > 0) {
    queryParams.orden_campos = sort.map((s) => s.columna).join(',');
    queryParams.orden_direcciones = sort.map((s) => s.direccion).join(',');
  } else {
    queryParams.orden_campos = 'dias_sin_venta';
    queryParams.orden_direcciones = 'desc';
  }

  const response = await api.get('/consultas/ranking', {
    params: queryParams,
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

/**
 * Fetches the ranking resumen (grouped aggregation).
 *
 * @param {Object} params
 * @param {string|null} params.marca
 * @param {string|null} params.categoria
 * @param {string|null} params.pm
 * @param {number[]} params.stor_ids
 * @param {boolean} params.incluir_sin_stock
 * @param {boolean} params.incluir_combos
 * @param {'marca'|'pm'} params.group_by
 * @returns {Promise<{
 *   items: Array<{grupo: string, pm: string|null, num_productos: number, stock_total: number, valor_costo_ars: number|null, valor_costo_usd: number|null, valor_venta: number|null}>,
 *   totales: {grupo: string, num_productos: number, stock_total: number, valor_costo_ars: number|null, valor_costo_usd: number|null, valor_venta: number|null}
 * }>}
 */
export async function getRankingResumen(params = {}) {
  const {
    marca = null,
    categoria = null,
    pm = null,
    stor_ids = [1],
    incluir_sin_stock = false,
    incluir_combos = false,
    group_by = 'marca',
  } = params;

  const queryParams = {
    stor_ids,
    incluir_sin_stock,
    incluir_combos,
    group_by,
  };

  if (marca) queryParams.marca = marca;
  if (categoria) queryParams.categoria = categoria;
  if (pm) queryParams.pm = pm;

  const response = await api.get('/consultas/ranking/resumen', {
    params: queryParams,
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
