import { describe, it, expect } from 'vitest';
import { DIMENSION_LEVELS, LEVEL_LABELS, LEVEL_NOUNS, chainHeader, nodeId } from './metricasMlLevels';

describe('the levels of the "Agrupado" tree', () => {
  it('mirrors the confirmed hierarchy of each dimension', () => {
    expect(DIMENSION_LEVELS).toEqual({
      categoria: ['categoria', 'subcategoria', 'product'],
      subcategoria: ['subcategoria_categoria', 'product'],
      marca: ['marca', 'categoria', 'subcategoria', 'product'],
      pm: ['pm', 'marca', 'categoria', 'subcategoria', 'product'],
      tienda: ['tienda', 'marca', 'categoria', 'subcategoria', 'product'],
    });
  });

  it('names and pluralises every level of every dimension', () => {
    for (const level of Object.values(DIMENSION_LEVELS).flat()) {
      expect(LEVEL_LABELS[level], level).toBeTruthy();
      expect(LEVEL_NOUNS[level].plural, level).toBeTruthy();
      expect(LEVEL_NOUNS[level].all, level).toBeTruthy();
    }
  });

  it('writes the chain as the first column header', () => {
    expect(chainHeader('marca')).toBe('Marca › Categoría › Subcategoría › Producto');
    expect(chainHeader('subcategoria')).toBe('Subcategoría › Producto');
    expect(chainHeader('inventada')).toBe('Grupo');
  });

  it('identifies a node by the path of keys, so one key under two parents is two nodes', () => {
    expect(nodeId(['EPSON', '10'])).toBe('["EPSON","10"]');
    expect(nodeId(['EPSON', '10'])).not.toBe(nodeId(['HP', '10']));
    expect(nodeId(['a"b', 'c,d'])).toBe('["a\\"b","c,d"]');
  });
});
