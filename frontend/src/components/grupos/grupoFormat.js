/** One filter row as words: the fields it sets, joined (a row is an AND of them). */
export function resumenFiltro(filtro, subcategorias = {}) {
  const partes = [];
  if (filtro.marca) partes.push(`Marca ${filtro.marca}`);
  if (filtro.categoria) partes.push(`Categoría ${filtro.categoria}`);
  if (filtro.subcategoria_id) partes.push(`Subcategoría ${subcategorias[filtro.subcategoria_id] ?? `#${filtro.subcategoria_id}`}`);
  if (filtro.item_id) partes.push(`Producto ${filtro.producto_descripcion ?? `#${filtro.item_id}`}`);
  return partes.join(' · ') || 'Fila vacía: no alcanza productos';
}

/** `{ id: nombre }` of the subcategories `GET /offset-filtros-opciones` lists. */
export const nombresDeSubcategorias = (opciones) => Object.fromEntries((opciones?.subcategorias ?? []).map((s) => [s.id, s.nombre]));

// The group's filters are the scope of the campaigns using it, and scope is money (tacticals approval S14).
export const NOTA_ALCANCE =
  'Cambiar los filtros de un grupo cambia los productos que alcanzan las campañas de sell out que lo usan: ' +
  'las aprobadas vuelven a pendiente de aprobación y dejan de aplicar hasta que las aprueben de nuevo.';

export const productosTexto = (n) => (n === 1 ? 'Alcanza 1 producto.' : `Alcanza ${(n ?? 0).toLocaleString('es-AR')} productos.`);

/**
 * What a filter change of the group sends back to pending (tacticals approval S14): `{ campanas, offsets }` from
 * `GET /offset-grupos/{id}/aprobadas-afectadas`, as one sentence per kind it has.
 */
export function aPendienteTextos({ campanas = 0, offsets = 0 } = {}) {
  const textos = [];
  if (campanas === 1) textos.push('1 campaña aprobada vuelve a pendiente');
  else if (campanas > 1) textos.push(`${campanas} campañas aprobadas vuelven a pendiente`);
  if (offsets === 1) textos.push('1 offset aprobado vuelve a pendiente');
  else if (offsets > 1) textos.push(`${offsets} offsets aprobados vuelven a pendiente`);
  return textos;
}

export const NOTA_A_PENDIENTE = 'Dejan de aplicar hasta que se aprueben de nuevo.';
