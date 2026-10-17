import { describe, expect, it } from 'vitest';
import { activeProductChips, fromPanelValue, toPanelValue } from './productFilters';

const filters = (overrides = {}) => ({ marcas: [], categorias: [], subcategorias: [], pms: [], ...overrides });

describe('toPanelValue', () => {
  it('decodes the brand and category keys and reads the ids as numbers', () => {
    expect(toPanelValue(filters({ marcas: ['TP%2CLINK', 'GAUSS'], categorias: ['A%25B'], subcategorias: ['12'], pms: ['7'] }))).toEqual({
      marcas: ['TP,LINK', 'GAUSS'],
      categorias: ['A%B'],
      subcategorias: [12],
      pms: [7],
    });
  });

  it('keeps a non-numeric subcategory token (the "none" bucket) as it came', () => {
    expect(toPanelValue(filters({ subcategorias: ['__none__'] })).subcategorias).toEqual(['__none__']);
  });
});

describe('fromPanelValue', () => {
  it('encodes a brand or category holding a comma so it stays ONE value of the csv param', () => {
    expect(fromPanelValue({ marcas: ['TP,LINK'], categorias: ['A%B'], subcategorias: [12], pms: [7] })).toEqual({
      marcas: ['TP%2CLINK'],
      categorias: ['A%25B'],
      subcategorias: ['12'],
      pms: ['7'],
    });
  });

  it('round-trips with toPanelValue', () => {
    const url = filters({ marcas: ['TP%2CLINK'], categorias: ['REDES'], subcategorias: ['3'], pms: ['9'] });
    expect(fromPanelValue(toPanelValue(url))).toEqual(url);
  });
});

describe('activeProductChips', () => {
  const options = {
    subcategorias: [{ nombre: 'Redes', subcategorias: [{ id: 12, nombre: 'Routers' }] }],
    pms: [{ id: 7, nombre: 'Ana' }],
  };

  it('names each active value, with the subcategory and PM names from the options', () => {
    const chips = activeProductChips(
      filters({ marcas: ['TP%2CLINK'], categorias: ['REDES'], subcategorias: ['12'], pms: ['7'] }),
      options,
    );
    expect(chips.map((chip) => chip.label)).toEqual(['Marca: TP,LINK', 'Categoría: REDES', 'Subcategoría: Routers', 'PM: Ana']);
  });

  it('falls back on the id when the name is not on hand', () => {
    const chips = activeProductChips(filters({ subcategorias: ['40'], pms: ['8'] }), options);
    expect(chips.map((chip) => chip.label)).toEqual(['Subcategoría #40', 'PM #8']);
  });

  it('says how to remove each one: the URL key and the list without that value', () => {
    const chips = activeProductChips(filters({ marcas: ['A', 'B'] }), {});
    expect(chips[0].remove).toEqual({ marcas: ['B'] });
    expect(chips[1].remove).toEqual({ marcas: ['A'] });
  });

  it('gives a value repeated in the URL one chip, whose removal drops that value', () => {
    const chips = activeProductChips(filters({ marcas: ['A', 'A', 'B'] }), {});
    expect(chips.map((chip) => chip.id)).toEqual(['marcas:A', 'marcas:B']);
    expect(chips[0].remove).toEqual({ marcas: ['B'] });
  });

  it('names the "none" bucket as the grouped view does, not by its sentinel', () => {
    const chips = activeProductChips(filters({ marcas: ['__none__'], categorias: ['__none__'], subcategorias: ['__none__'] }), options);
    expect(chips.map((chip) => chip.label)).toEqual(['Marca: Sin marca', 'Categoría: Sin categoría', 'Subcategoría: Sin subcategoría']);
  });

  it('is empty without product filters', () => {
    expect(activeProductChips(filters(), options)).toEqual([]);
  });
});
