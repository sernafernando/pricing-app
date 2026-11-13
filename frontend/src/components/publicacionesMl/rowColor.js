import { COLORES_DISPONIBLES } from '../../utils/productosConstants';

/**
 * The tone of a row of the Publicaciones ML tables (S8): the linked product's color on the chosen team layer paints
 * the row; with none, the global layer's color only hints it, as Productos does. `null` leaves the row alone.
 * The shape is `TableShell`'s `getRowTone`.
 *
 * `overlay` (see `useColorOverlay`) holds what was painted since the rows loaded, by product id: a field it has
 * (`marcado`, `hintGlobal`; null = cleared) wins over the row's own. A publication may also be painted on its own
 * (seleccion-por-publicacion S3): its own color wins over its product's, and `ownOverlay` (by MLA) holds the own colors
 * painted since, a null one falling back to the product's.
 *
 * `globalReference` false (the user turned the global reference off on this team layer, pubml-capa-default S3) drops
 * the global layer's hint: a row the team has not painted shows nothing.
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

// The row fields of each layer's color: the shown one, and its two parts on a row painted on its own.
const LAYER_FIELDS = {
  marcado: { shown: 'color_marcado', own: 'color_propio', product: 'color_producto' },
  hintGlobal: { shown: 'color_hint_global', own: 'color_hint_global_propio', product: 'color_hint_global_producto' },
};

// One layer's color of a publication row: its own (overlay first), otherwise its product's (overlay first). On a row
// not painted on its own, the shown color is its product's.
function layerColor(item, field, painted, ownPainted) {
  const { shown, own, product } = LAYER_FIELDS[field];
  const ownColor = ownPainted && field in ownPainted ? ownPainted[field] : (item[own] ?? null);
  if (ownColor) return ownColor;
  if (painted && field in painted) return painted[field];
  return (item[own] != null ? item[product] : item[shown]) ?? null;
}

/** A publication row (`/view/items`). */
export function itemRowTone(item, overlay, ownOverlay, globalReference = true) {
  const productId = item.link?.producto_item_id;
  const painted = productId != null ? overlay?.get(String(productId)) : undefined;
  const ownPainted = item.item_id != null ? ownOverlay?.get(String(item.item_id)) : undefined;
  return toneOf(
    layerColor(item, 'marcado', painted, ownPainted),
    globalReference ? layerColor(item, 'hintGlobal', painted, ownPainted) : null,
  );
}

/** A row of the Producto / Agrupado trees: its publications and its product nodes carry the color. */
export function treeRowTone(row, overlay, ownOverlay, globalReference = true) {
  if (row.type === 'item') return itemRowTone(row.item, overlay, ownOverlay, globalReference);
  if (row.type === 'node' && row.node.kind === 'producto') {
    const tone = toneOver(overlay, row.node.productoItemId, row.node.colorMarcado, row.node.colorHintGlobal);
    return !globalReference && tone?.marker ? null : tone;
  }
  return null;
}
