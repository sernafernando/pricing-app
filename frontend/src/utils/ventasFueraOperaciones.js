/**
 * Helpers of the PDF operations list (ODD `vpf-operaciones`, page `VentasFueraOperaciones`): the query of
 * GET /ventas-fuera-pdf/operaciones/listado, the facets it returns and the shape a PDF line takes to open the
 * reused ModalEditarCosto.
 */

/** Costo D = Precio Costo × 1,065, the backend's COSTO_D_FACTOR (ventas_fuera_pdf/ventas.py); change both together. */
export const COSTO_D_FACTOR = 1.065;

export const PAGE_SIZE = 50;

/** Why a line has no product, as the listado and /sin-producto/resumen name it. */
export const CAUSAS_SIN_PRODUCTO = {
  sin_codigo_manual: 'Artículo manual, sin código',
  sin_codigo: 'Sin código en el PDF',
  codigo_no_encontrado: 'Código que no está en el catálogo',
};

/** How the line got its product (`item_origen`); the code match is the normal case and says nothing. */
export const ORIGEN_PRODUCTO = {
  prefijo: 'Por el inicio del artículo',
  mapeo: 'Producto recordado',
  manual: 'Producto asignado a mano',
};

export const ORDENES = [
  { value: 'fecha_desc', label: 'Más nuevas primero' },
  { value: 'fecha_asc', label: 'Más viejas primero' },
  { value: 'importe_desc', label: 'Mayor importe' },
  { value: 'markup_asc', label: 'Menor markup' },
];

/**
 * The listado query: dates, cost basis, page, size and sort always; each filter only when set. `empresas` and
 * `vendedores` are lists (sent as repeated params).
 */
export function buildListadoParams({
  desde,
  hasta,
  empresa = '',
  vendedor = '',
  q = '',
  tipo = '',
  sinProducto = false,
  revisar = false,
  costo = 'costo_d',
  page = 1,
  pageSize = PAGE_SIZE,
  sort = 'fecha_desc',
}) {
  const params = { desde, hasta };
  if (empresa) params.empresas = [empresa];
  if (vendedor) params.vendedores = [vendedor];
  if (q.trim()) params.q = q.trim();
  if (tipo) params.tipo = tipo;
  if (sinProducto) params.sin_producto = true;
  if (revisar) params.revisar = true;
  return { ...params, costo, page, page_size: pageSize, sort };
}

/** A facet list as FacetChips takes it. Accepts `[{valor, cantidad}]`, plain names, or a `{name: count}` map. */
export function facetas(raw) {
  if (!raw) return { options: [], counts: {} };
  if (!Array.isArray(raw)) return { options: Object.keys(raw), counts: { ...raw } };
  const options = [];
  const counts = {};
  for (const item of raw) {
    const valor = typeof item === 'string' ? item : (item.valor ?? item.value ?? item.nombre);
    if (valor === null || valor === undefined) continue;
    options.push(valor);
    counts[valor] = typeof item === 'string' ? undefined : (item.cantidad ?? item.count);
  }
  return { options, counts };
}

/**
 * A PDF line in the fields ModalEditarCosto reads. `costo_unitario` (the value the modal starts from) is the unit
 * Precio Costo, so saving it unchanged with the optional % at 0 (owner L4) keeps today's Costo D; `costo_pesos_sin_iva` is the line's
 * current Costo D.
 */
export function lineaParaModalCosto(linea, operacion) {
  const cantidad = Number(linea.cantidad) || 0;
  const divisor = cantidad || 1;
  const precio = Number(linea.precio) || 0;
  const precioCosto = Number(linea.precio_costo) || 0;
  return {
    codigo_item: linea.codigo,
    fecha: operacion.fecha,
    descripcion: linea.articulo,
    cantidad: linea.cantidad,
    precio_unitario_sin_iva: precio / divisor,
    precio_final_sin_iva: precio,
    costo_unitario: precioCosto / divisor,
    costo_pesos_sin_iva: Math.round(precioCosto * COSTO_D_FACTOR * 100) / 100,
  };
}
