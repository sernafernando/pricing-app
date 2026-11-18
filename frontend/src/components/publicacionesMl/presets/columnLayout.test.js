/**
 * The column layout's merge rules (pubml-columnas-presets S1, S2): a saved order never hides a column nor breaks a
 * group, whatever the server kept.
 */
import { describe, it, expect } from 'vitest';
import { columnBlocks, mergeOrder, resolveOrder, resolveVisibility } from './columnLayout';

const COLUMNS = [
  { key: 'titulo' },
  { key: 'tipo' },
  { key: 'precio' },
  { key: 'unidades_7d', group: 'Ventas' },
  { key: 'unidades_30d', group: 'Ventas' },
  { key: 'stock_erp', group: 'Stock' },
  { key: 'stock_full', group: 'Stock' },
  { key: 'codigo' },
];

describe('mergeOrder', () => {
  it('follows the saved order and puts an id the save does not know right after its default predecessor', () => {
    expect(mergeOrder(['a', 'b', 'c', 'd'], ['c', 'a'])).toEqual(['c', 'd', 'a', 'b']);
    expect(mergeOrder(['a', 'b', 'c'], [])).toEqual(['a', 'b', 'c']);
    expect(mergeOrder(['a', 'b', 'c'], ['zz', 'c', 'b'])).toEqual(['a', 'c', 'b']);
  });
});

describe('columnBlocks', () => {
  it('a group is one block, an ungrouped column its own, and the first column none', () => {
    expect(columnBlocks(COLUMNS).map((block) => block.keys)).toEqual([
      ['tipo'],
      ['precio'],
      ['unidades_7d', 'unidades_30d'],
      ['stock_erp', 'stock_full'],
      ['codigo'],
    ]);
  });
});

describe('resolveOrder', () => {
  it('with nothing saved, is the default order', () => {
    expect(resolveOrder(COLUMNS, null)).toEqual(COLUMNS.map((column) => column.key));
  });

  it('keeps the first column first and every group together, whatever the saved order says', () => {
    expect(resolveOrder(COLUMNS, ['stock_full', 'unidades_7d', 'titulo', 'stock_erp', 'precio', 'unidades_30d'])).toEqual([
      'titulo',
      // Tipo and Código are not in the save: each goes right after the block it follows by default.
      'tipo',
      'stock_full',
      'stock_erp',
      'codigo',
      'unidades_7d',
      'unidades_30d',
      'precio',
    ]);
  });

  it('ignores unknown or removed keys and inserts new columns at their default position', () => {
    expect(resolveOrder(COLUMNS, ['ya_no_existe', 'codigo', 'precio', 'tipo'])).toEqual([
      'titulo',
      'codigo',
      'precio',
      'unidades_7d',
      'unidades_30d',
      'stock_erp',
      'stock_full',
      'tipo',
    ]);
  });

  it('ignores a saved order that is not a list of names', () => {
    expect(resolveOrder(COLUMNS, 'roto')).toEqual(COLUMNS.map((column) => column.key));
    expect(resolveOrder(COLUMNS, [3, null, { key: 'tipo' }, 'codigo'])).toEqual(COLUMNS.map((column) => column.key));
  });
});

describe('resolveVisibility', () => {
  it('a saved choice wins over the default, an unknown key is ignored and the first column always shows', () => {
    expect(resolveVisibility(COLUMNS, { codigo: false }, { codigo: true, tipo: false, titulo: false, fantasma: true, precio: 'si' })).toEqual({
      titulo: true,
      tipo: false,
      precio: true,
      unidades_7d: true,
      unidades_30d: true,
      stock_erp: true,
      stock_full: true,
      codigo: true,
    });
  });
});
