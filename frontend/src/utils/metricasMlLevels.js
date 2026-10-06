/**
 * The levels of the Métricas ML "Agrupado" tree (ODD `metricas-ml-agrupado-anidado`),
 * mirrored from `backend/app/services/ml_daily_metrics/groups.py` (`HIERARCHIES`).
 * The server says what each row is (`level`, `child_level`); these tables only
 * name things and draw the first column's header before any row arrives.
 */

/** The levels under each dimension, top first, the products last. */
export const DIMENSION_LEVELS = {
  categoria: ['categoria', 'subcategoria', 'product'],
  subcategoria: ['subcategoria_categoria', 'product'],
  marca: ['marca', 'categoria', 'subcategoria', 'product'],
  pm: ['pm', 'marca', 'categoria', 'subcategoria', 'product'],
  tienda: ['tienda', 'marca', 'categoria', 'subcategoria', 'product'],
};

/** What a level is called, as a row's tag and in the first column's header. */
export const LEVEL_LABELS = {
  marca: 'Marca',
  categoria: 'Categoría',
  subcategoria: 'Subcategoría',
  // "<subcategoría> · <categoría>": the row's title already carries the categoría.
  subcategoria_categoria: 'Subcategoría',
  tienda: 'Tienda',
  pm: 'PM',
  product: 'Producto',
};

/** The plural of a level and "all of them", for the notes under an open node. */
export const LEVEL_NOUNS = {
  marca: { plural: 'marcas', all: 'las marcas' },
  categoria: { plural: 'categorías', all: 'las categorías' },
  subcategoria: { plural: 'subcategorías', all: 'las subcategorías' },
  subcategoria_categoria: { plural: 'subcategorías', all: 'las subcategorías' },
  tienda: { plural: 'tiendas', all: 'las tiendas' },
  pm: { plural: 'PMs', all: 'los PMs' },
  product: { plural: 'productos', all: 'los productos' },
};

/** "Marca › Categoría › Subcategoría › Producto": the header of the first column. */
export function chainHeader(dimension) {
  const levels = DIMENSION_LEVELS[dimension];
  return levels ? levels.map((level) => LEVEL_LABELS[level]).join(' › ') : 'Grupo';
}

/** A node's identity: the keys of its ancestors and its own. The same key under
 * two parents is two nodes, and the same string is the backend's `path` param. */
export function nodeId(path) {
  return JSON.stringify(path);
}
