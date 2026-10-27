import { COLORES_DISPONIBLES } from '../../utils/productosConstants';

/**
 * The tone of a row of the Publicaciones ML tables (S8): the linked product's color on the chosen team layer paints
 * the row; with none, the global layer's color only hints it, as Productos does. `null` leaves the row alone.
 * The shape is `TableShell`'s `getRowTone`.
 */
const COLOR_BY_ID = new Map(COLORES_DISPONIBLES.filter((c) => c.id).map((c) => [c.id, c]));

function toneOf(marcado, hintGlobal) {
  const own = COLOR_BY_ID.get(marcado);
  if (own) return { background: own.color, text: own.colorTexto, label: `Color: ${own.nombre}` };
  const hint = COLOR_BY_ID.get(hintGlobal);
  if (hint) return { marker: hint.color, label: `Color global: ${hint.nombre}` };
  return null;
}

/** A publication row (`/view/items`). */
export const itemRowTone = (item) => toneOf(item.color_marcado, item.color_hint_global);

/** A row of the Producto / Agrupado trees: its publications and its product nodes carry the color. */
export function treeRowTone(row) {
  if (row.type === 'item') return itemRowTone(row.item);
  if (row.type === 'node' && row.node.kind === 'producto') return toneOf(row.node.colorMarcado, row.node.colorHintGlobal);
  return null;
}
