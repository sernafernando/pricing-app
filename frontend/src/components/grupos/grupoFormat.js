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

export const NOTA_ALCANCE =
  'Cambiar un grupo cambia los productos que alcanzan las campañas de sell out que lo usan: se recalculan solas.';

export const productosTexto = (n) => (n === 1 ? 'Alcanza 1 producto.' : `Alcanza ${(n ?? 0).toLocaleString('es-AR')} productos.`);
