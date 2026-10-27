import { COLORES_DISPONIBLES } from '../../utils/productosConstants';

/**
 * The tone of a row of the Publicaciones ML tables (S8): the linked product's color on the chosen team layer paints
 * the row; with none, the global layer's color only hints it, as Productos does. `null` leaves the row alone.
 * The shape is `TableShell`'s `getRowTone`.
 *
 * `overlay` (see `useColorOverlay`) holds what was painted since the rows loaded, by product id: a field it has
 * (`marcado`, `hintGlobal`; null = cleared) wins over the row's own.
 */
const COLOR_BY_ID = new Map(COLORES_DISPONIBLES.filter((c) => c.id).map((c) => [c.id, c]));

function toneOf(marcado, hintGlobal) {
  const own = COLOR_BY_ID.get(marcado);
  if (own) return { background: own.color, text: own.colorTexto, label: `Color: ${own.nombre}` };
  const hint = COLOR_BY_ID.get(hintGlobal);
  if (hint) return { marker: hint.color, label: `Color global: ${hint.nombre}` };
  return null;
}

function toneOver(overlay, productId, marcado, hintGlobal) {
  const painted = productId != null ? overlay?.get(String(productId)) : undefined;
  if (!painted) return toneOf(marcado, hintGlobal);
  return toneOf('marcado' in painted ? painted.marcado : marcado, 'hintGlobal' in painted ? painted.hintGlobal : hintGlobal);
}

/** A publication row (`/view/items`). */
export const itemRowTone = (item, overlay) =>
  toneOver(overlay, item.link?.producto_item_id, item.color_marcado, item.color_hint_global);

/** A row of the Producto / Agrupado trees: its publications and its product nodes carry the color. */
export function treeRowTone(row, overlay) {
  if (row.type === 'item') return itemRowTone(row.item, overlay);
  if (row.type === 'node' && row.node.kind === 'producto') {
    return toneOver(overlay, row.node.productoItemId, row.node.colorMarcado, row.node.colorHintGlobal);
  }
  return null;
}
