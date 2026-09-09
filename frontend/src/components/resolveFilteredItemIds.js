/**
 * Client-side resolve of the Acciones masivas write-set.
 *
 * Expects already-built `listar` query params (same object as
 * `construirFiltrosParams()`). Adds stable `item_id` ASC order, pages until all
 * `item_id`s are collected, and fail-closes on empty (when filters active),
 * mismatch vs finite `totalProductos`, or page ceiling. Never falls back to the
 * page buffer.
 */

export const RESOLVE_PAGE_SIZE = 500;

/** Params that do not mean "user filters are active". */
const NON_FILTER_LISTAR_KEYS = new Set(['orden_campos', 'orden_direcciones']);

export class ResolveFilteredIdsError extends Error {
  /**
   * @param {string} message
   * @param {'empty' | 'mismatch' | 'api' | 'forbidden'} code
   */
  constructor(message, code) {
    super(message);
    this.name = 'ResolveFilteredIdsError';
    this.code = code;
  }
}

/**
 * Ensure listar params use a stable ORDER BY for safe OFFSET pagination.
 * @param {object} listarParams output of `construirFiltrosParams()` (or equivalent)
 */
export function withStableListarOrder(listarParams = {}) {
  return {
    ...listarParams,
    orden_campos: 'item_id',
    orden_direcciones: 'asc',
  };
}

function listarParamsHaveFilters(listarParams) {
  return Object.keys(listarParams || {}).some((k) => !NON_FILTER_LISTAR_KEYS.has(k));
}

function resolveMaxPages(totalProductos, pageSize) {
  const expected = Number(totalProductos);
  if (Number.isFinite(expected) && expected > 0) {
    return Math.max(2, Math.ceil(expected / pageSize) + 2);
  }
  return 50;
}

/**
 * Page `listar` until all item_ids are collected.
 *
 * @param {object} opts
 * @param {(params: object) => Promise<{ data: { productos?: object[], total?: number } }>} opts.listar
 * @param {object} opts.listarParams already-built filter query (from construirFiltrosParams)
 * @param {number} [opts.totalProductos] expected Total from listing cards
 * @param {number} [opts.pageSize]
 * @returns {Promise<string[]>}
 */
export async function resolveFilteredItemIds({
  listar,
  listarParams = {},
  totalProductos,
  pageSize = RESOLVE_PAGE_SIZE,
}) {
  const filterParams = withStableListarOrder(listarParams);
  const filtersActive = listarParamsHaveFilters(listarParams);
  const idSet = new Set();
  let page = 1;
  let apiTotal = null;
  const maxPages = resolveMaxPages(totalProductos, pageSize);

  try {
    while (page <= maxPages) {
      const res = await listar({ ...filterParams, page, page_size: pageSize });
      const productos = res?.data?.productos ?? [];
      if (typeof res?.data?.total === 'number') apiTotal = res.data.total;

      for (const p of productos) {
        if (p?.item_id != null) idSet.add(p.item_id);
      }

      if (productos.length === 0) break;
      if (apiTotal != null && idSet.size >= apiTotal) break;
      if (productos.length < pageSize) break;
      page += 1;
    }

    if (page > maxPages) {
      throw new ResolveFilteredIdsError(
        'El resolve superó el máximo de páginas permitido; no se aplicará nada',
        'api',
      );
    }
  } catch (err) {
    if (err instanceof ResolveFilteredIdsError) throw err;
    if (err?.response?.status === 403) {
      throw new ResolveFilteredIdsError(
        'No tenés permiso para listar el conjunto filtrado; no se aplicará nada',
        'forbidden',
      );
    }
    throw new ResolveFilteredIdsError(
      'No se pudo resolver el conjunto filtrado de productos',
      'api',
    );
  }

  const ids = [...idSet];

  if (filtersActive && ids.length === 0) {
    throw new ResolveFilteredIdsError(
      'El filtro activo no resolvió productos; no se aplicará nada',
      'empty',
    );
  }

  if (
    totalProductos != null &&
    Number.isFinite(Number(totalProductos)) &&
    ids.length !== Number(totalProductos)
  ) {
    throw new ResolveFilteredIdsError(
      `El conjunto resuelto (${ids.length}) no coincide con el Total (${totalProductos})`,
      'mismatch',
    );
  }

  return ids;
}

export function chunkIds(ids, size) {
  const chunks = [];
  for (let i = 0; i < ids.length; i += size) {
    chunks.push(ids.slice(i, i + size));
  }
  return chunks;
}
