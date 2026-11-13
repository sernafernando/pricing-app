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

describe('the local overlay (paints and SSE events since the rows loaded)', () => {
  const overlay = new Map([
    ['77', { marcado: 'verde' }],
    ['78', { marcado: null }],
    ['79', { hintGlobal: 'gris' }],
  ]);

  it("wins over the row's own data, a cleared color included, matched by the linked product", () => {
    expect(itemRowTone({ link: { producto_item_id: 77 }, color_marcado: 'rojo' }, overlay)).toMatchObject({ background: 'var(--product-ok-bg)' });
    expect(itemRowTone({ link: { producto_item_id: 78 }, color_marcado: 'rojo' }, overlay)).toBeNull();
    expect(itemRowTone({ link: { producto_item_id: 79 } }, overlay)).toMatchObject({ marker: 'var(--product-inactive-bg)' });
    expect(itemRowTone({ link: null, color_marcado: 'rojo' }, overlay)).toMatchObject({ background: 'var(--product-urgent-bg)' });
  });

  it('reaches the product nodes of the trees too', () => {
    const product = readProduct({ key: '77', product_item_id: 77, color_marcado: 'gris' });
    expect(treeRowTone({ type: 'node', node: product }, overlay)).toMatchObject({ background: 'var(--product-ok-bg)' });
  });
});

describe("a publication's own color (seleccion-por-publicacion S3)", () => {
  // MLA4 is painted azul on its own; its product 77 is rojo.
  const own = { item_id: 'MLA4', link: { producto_item_id: 77 }, color_marcado: 'azul', color_propio: 'azul', color_producto: 'rojo' };

  it('shows its own color, and keeps it when its product is repainted', () => {
    expect(itemRowTone(own)).toMatchObject({ background: 'var(--product-info-bg)' });
    expect(itemRowTone(own, new Map([['77', { marcado: 'verde' }]]))).toMatchObject({ background: 'var(--product-info-bg)' });
  });

  it("unpainted on its own, it falls back to its product's color, repainted or not", () => {
    const unpainted = new Map([['MLA4', { marcado: null }]]);
    expect(itemRowTone(own, undefined, unpainted)).toMatchObject({ background: 'var(--product-urgent-bg)' });
    expect(itemRowTone(own, new Map([['77', { marcado: 'verde' }]]), unpainted)).toMatchObject({ background: 'var(--product-ok-bg)' });
  });

  it('painted on its own since the rows loaded, its color wins over its product, whose sibling keeps the product', () => {
    const sibling = { item_id: 'MLA1', link: { producto_item_id: 77 }, color_marcado: 'rojo' };
    const painted = new Map([['MLA1', { marcado: 'gris' }]]);
    expect(itemRowTone(sibling, undefined, painted)).toMatchObject({ background: 'var(--product-inactive-bg)' });
    expect(itemRowTone({ ...sibling, item_id: 'MLA9' }, undefined, painted)).toMatchObject({ background: 'var(--product-urgent-bg)' });
  });

  it('on a team layer its own global color hints it, and its product shows through once unpainted', () => {
    const hinted = {
      item_id: 'MLA4',
      link: { producto_item_id: 77 },
      color_hint_global: 'gris',
      color_hint_global_propio: 'gris',
      color_hint_global_producto: 'rojo',
    };
    expect(itemRowTone(hinted)).toMatchObject({ marker: 'var(--product-inactive-bg)' });
    expect(itemRowTone(hinted, undefined, new Map([['MLA4', { hintGlobal: null }]]))).toMatchObject({
      marker: 'var(--product-urgent-bg)',
    });
  });

  it('a row whose own color comes as null shows its product color', () => {
    const unpainted = { item_id: 'MLA5', link: { producto_item_id: 77 }, color_marcado: 'rojo', color_propio: null, color_producto: null };
    expect(itemRowTone(unpainted)).toMatchObject({ background: 'var(--product-urgent-bg)' });
  });

  it('reaches the publications of the trees too', () => {
    expect(treeRowTone({ type: 'item', item: own }, undefined, new Map([['MLA4', { marcado: null }]]))).toMatchObject({
      background: 'var(--product-urgent-bg)',
    });
  });
});

describe('the global reference turned off on the layer (pubml-capa-default S3)', () => {
  const product = { type: 'node', node: { kind: 'producto', productoItemId: 4101, colorMarcado: null, colorHintGlobal: 'azul' } };

  it('drops the global marker, on the list and the trees, the overlay too', () => {
    expect(itemRowTone({ color_hint_global: 'azul' }, undefined, undefined, false)).toBeNull();
    expect(treeRowTone(product, undefined, undefined, false)).toBeNull();
    expect(treeRowTone(product, new Map([['4101', { hintGlobal: 'rojo' }]]), undefined, false)).toBeNull();
  });

  it("keeps the layer's own color", () => {
    expect(itemRowTone({ color_marcado: 'verde', color_hint_global: 'azul' }, undefined, undefined, false)).toMatchObject({
      background: 'var(--product-ok-bg)',
    });
    expect(treeRowTone({ ...product, node: { ...product.node, colorMarcado: 'rojo' } }, undefined, undefined, false)).toMatchObject({
      background: 'var(--product-urgent-bg)',
    });
  });
});
