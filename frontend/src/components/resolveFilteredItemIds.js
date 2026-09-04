/**
 * Client-side resolve of the Acciones masivas write-set.
 *
 * Maps `filtrosActivos` (same shape as Calcular Web / Export) to `productosAPI.listar`
 * query params (same keys as `construirFiltrosParams`), pages until all `item_id`s
 * are collected, and fail-closes when filters are active but the resolve is empty
 * or mismatches `totalProductos`. Never falls back to the page buffer.
 */

export const RESOLVE_PAGE_SIZE = 500;

export class ResolveFilteredIdsError extends Error {
  /**
   * @param {string} message
   * @param {'empty' | 'mismatch' | 'api'} code
   */
  constructor(message, code) {
    super(message);
    this.name = 'ResolveFilteredIdsError';
    this.code = code;
  }
}

/**
 * Convert modal `filtrosActivos` into listar query params.
 * Param names match `useProductosFilters.construirFiltrosParams` (e.g. `tn_*`).
 */
export function buildListarParamsFromFiltros(filtrosActivos = {}) {
  const params = {};
  if (filtrosActivos.search) params.search = filtrosActivos.search;
  if (filtrosActivos.con_stock === true) params.con_stock = true;
  if (filtrosActivos.con_stock === false) params.con_stock = false;
  if (filtrosActivos.con_precio === true) params.con_precio = true;
  if (filtrosActivos.con_precio === false) params.con_precio = false;
  if (filtrosActivos.marcas?.length > 0) params.marcas = filtrosActivos.marcas.join(',');
  if (filtrosActivos.subcategorias?.length > 0) {
    params.subcategorias = filtrosActivos.subcategorias.join(',');
  }
  if (filtrosActivos.audit_usuarios?.length > 0) {
    params.audit_usuarios = filtrosActivos.audit_usuarios.join(',');
  }
  if (filtrosActivos.audit_tipos_accion?.length > 0) {
    params.audit_tipos_accion = filtrosActivos.audit_tipos_accion.join(',');
  }
  if (filtrosActivos.audit_fecha_desde) params.audit_fecha_desde = filtrosActivos.audit_fecha_desde;
  if (filtrosActivos.audit_fecha_hasta) params.audit_fecha_hasta = filtrosActivos.audit_fecha_hasta;
  if (filtrosActivos.filtroRebate === 'con_rebate') params.con_rebate = true;
  if (filtrosActivos.filtroRebate === 'sin_rebate') params.con_rebate = false;
  if (filtrosActivos.filtroOferta === 'con_oferta') params.con_oferta = true;
  if (filtrosActivos.filtroOferta === 'sin_oferta') params.con_oferta = false;
  if (filtrosActivos.filtroWebTransf === 'con_web_transf') params.con_web_transf = true;
  if (filtrosActivos.filtroWebTransf === 'sin_web_transf') params.con_web_transf = false;
  if (filtrosActivos.filtroTiendaNube === 'con_descuento') params.tn_con_descuento = true;
  if (filtrosActivos.filtroTiendaNube === 'sin_descuento') params.tn_sin_descuento = true;
  if (filtrosActivos.filtroTiendaNube === 'no_publicado') params.tn_no_publicado = true;
  if (filtrosActivos.filtroMarkupClasica === 'positivo') params.markup_clasica_positivo = true;
  if (filtrosActivos.filtroMarkupClasica === 'negativo') params.markup_clasica_positivo = false;
  if (filtrosActivos.filtroMarkupRebate === 'positivo') params.markup_rebate_positivo = true;
  if (filtrosActivos.filtroMarkupRebate === 'negativo') params.markup_rebate_positivo = false;
  if (filtrosActivos.filtroMarkupOferta === 'positivo') params.markup_oferta_positivo = true;
  if (filtrosActivos.filtroMarkupOferta === 'negativo') params.markup_oferta_positivo = false;
  if (filtrosActivos.filtroMarkupWebTransf === 'positivo') params.markup_web_transf_positivo = true;
  if (filtrosActivos.filtroMarkupWebTransf === 'negativo') params.markup_web_transf_positivo = false;
  if (filtrosActivos.filtroOutOfCards === 'con_out_of_cards') params.out_of_cards = true;
  if (filtrosActivos.filtroOutOfCards === 'sin_out_of_cards') params.out_of_cards = false;
  if (filtrosActivos.filtroMLA === 'con_mla') params.con_mla = true;
  if (filtrosActivos.filtroMLA === 'sin_mla') params.con_mla = false;
  if (filtrosActivos.filtroEstadoMLA === 'activa') params.estado_mla = 'activa';
  if (filtrosActivos.filtroEstadoMLA === 'pausada') params.estado_mla = 'pausada';
  if (filtrosActivos.filtroNuevos === 'ultimos_7_dias') params.nuevos_ultimos_7_dias = true;
  if (filtrosActivos.filtroTiendaOficial) params.tienda_oficial = filtrosActivos.filtroTiendaOficial;
  if (filtrosActivos.coloresSeleccionados?.length > 0) {
    params.colores = filtrosActivos.coloresSeleccionados.join(',');
  }
  if (filtrosActivos.equipoActivoId) params.equipo_id = filtrosActivos.equipoActivoId;
  if (filtrosActivos.pmsSeleccionados?.length > 0) {
    params.pms = filtrosActivos.pmsSeleccionados.join(',');
  }
  if (filtrosActivos.filtroPxq === 'con_pxq') params.con_pxq = true;
  if (filtrosActivos.promo_tipos) {
    params.promo_tipos = filtrosActivos.promo_tipos;
    if (filtrosActivos.promo_estado) params.promo_estado = filtrosActivos.promo_estado;
  }
  if (filtrosActivos.con_promo_aplicada) params.con_promo_aplicada = true;
  if (filtrosActivos.con_promo_sin_aplicar) params.con_promo_sin_aplicar = true;
  return params;
}

export function hasActiveFilters(filtrosActivos) {
  return Object.keys(buildListarParamsFromFiltros(filtrosActivos)).length > 0;
}

/**
 * Page filtered `listar` until all item_ids are collected.
 *
 * @param {object} opts
 * @param {(params: object) => Promise<{ data: { productos?: object[], total?: number } }>} opts.listar
 * @param {object} opts.filtrosActivos
 * @param {number} [opts.totalProductos] expected Total from listing cards
 * @param {number} [opts.pageSize]
 * @returns {Promise<string[]>}
 */
export async function resolveFilteredItemIds({
  listar,
  filtrosActivos,
  totalProductos,
  pageSize = RESOLVE_PAGE_SIZE,
}) {
  const filterParams = buildListarParamsFromFiltros(filtrosActivos);
  const filtersActive = Object.keys(filterParams).length > 0;
  const ids = [];
  let page = 1;
  let apiTotal = null;

  try {
    while (true) {
      const res = await listar({ ...filterParams, page, page_size: pageSize });
      const productos = res?.data?.productos ?? [];
      if (typeof res?.data?.total === 'number') apiTotal = res.data.total;

      for (const p of productos) {
        if (p?.item_id != null) ids.push(p.item_id);
      }

      if (productos.length === 0) break;
      if (apiTotal != null && ids.length >= apiTotal) break;
      if (productos.length < pageSize) break;
      page += 1;
    }
  } catch (err) {
    if (err instanceof ResolveFilteredIdsError) throw err;
    throw new ResolveFilteredIdsError(
      'No se pudo resolver el conjunto filtrado de productos',
      'api',
    );
  }

  if (filtersActive) {
    if (ids.length === 0) {
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
