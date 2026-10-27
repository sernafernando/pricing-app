/**
 * rowColor (S8): the tone of a row of the Publicaciones ML tables from the linked product's color, read on the
 * chosen team layer -- the layer's own color paints the row, the global one only hints it, as in Productos.
 */
import { describe, it, expect } from 'vitest';
import { itemRowTone, treeRowTone } from './rowColor';
import { readProduct } from './useProductRows';

describe('itemRowTone', () => {
  it("paints the row with the layer's color", () => {
    expect(itemRowTone({ color_marcado: 'rojo' })).toEqual({
      background: 'var(--product-urgent-bg)',
      text: 'var(--product-urgent-text)',
      label: 'Color: Urgente',
    });
  });

  it("hints the global color when the layer has none, and the layer's color wins over it", () => {
    expect(itemRowTone({ color_hint_global: 'azul' })).toEqual({ marker: 'var(--product-info-bg)', label: 'Color global: Info' });
    expect(itemRowTone({ color_marcado: 'verde', color_hint_global: 'azul' })).toMatchObject({ background: 'var(--product-ok-bg)' });
  });

  it('leaves alone a row with no color or an unknown one', () => {
    expect(itemRowTone({})).toBeNull();
    expect(itemRowTone({ color_marcado: 'fucsia' })).toBeNull();
  });
});

describe('treeRowTone', () => {
  it('tones the publication rows and the product nodes, never the other levels nor the branch states', () => {
    expect(treeRowTone({ type: 'item', item: { color_marcado: 'rojo' } })).toMatchObject({ background: 'var(--product-urgent-bg)' });
    const product = readProduct({ key: '77', product_item_id: 77, color_marcado: 'gris' });
    expect(treeRowTone({ type: 'node', node: product })).toMatchObject({ background: 'var(--product-inactive-bg)' });
    expect(treeRowTone({ type: 'node', node: { kind: 'marca', colorMarcado: 'rojo' } })).toBeNull();
    expect(treeRowTone({ type: 'more' })).toBeNull();
  });
});
