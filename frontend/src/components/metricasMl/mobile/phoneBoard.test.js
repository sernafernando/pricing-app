import { describe, it, expect } from 'vitest';
import { activeFilterChips, formatCompactMoney, phoneSortOptions } from './phoneBoard';

const NO_FILTERS = {
  groupBy: 'product',
  storeLabel: null,
  stock: [],
  stockExclude: [],
  ageing: [],
  ageingExclude: [],
  alerts: [],
  soloConVentas: true,
  pubStatus: [],
  pubStatusExclude: [],
  pubType: [],
  pubTypeExclude: [],
  productFilters: { marcas: [], categorias: [], subcategorias: [], pms: [] },
};

describe('formatCompactMoney', () => {
  it('reads millions with one decimal, like the design ("$ 312,4 M")', () => {
    expect(formatCompactMoney(312_400_000)).toBe('$ 312,4 M');
    expect(formatCompactMoney(9_249_000)).toBe('$ 9,2 M');
  });

  it('keeps smaller amounts whole, and the minus BEFORE the sign (as formatSignedMoney)', () => {
    expect(formatCompactMoney(710_400)).toBe('$ 710.400');
    expect(formatCompactMoney(-710_400)).toBe('-$ 710.400');
    expect(formatCompactMoney(-1_250_000)).toBe('-$ 1,3 M');
  });

  it('shows a dash for an unknown amount, never $ 0', () => {
    expect(formatCompactMoney(null)).toBe('—');
    expect(formatCompactMoney(undefined)).toBe('—');
  });
});

describe('activeFilterChips', () => {
  it('always names the grouping, and counts no filter when none is set', () => {
    const { chips, count } = activeFilterChips(NO_FILTERS);
    expect(chips).toEqual(['Agrupar: Producto']);
    expect(count).toBe(0);
  });

  it('lists the store, stock, ageing, alerts and product filters, as in the design', () => {
    const { chips, count } = activeFilterChips({
      ...NO_FILTERS,
      storeLabel: 'Gauss',
      stock: ['con_stock'],
      ageingExclude: ['over_60'],
      alerts: ['sin_ventas_30d'],
      productFilters: { marcas: ['Epson', 'HP'], categorias: [], subcategorias: [], pms: [] },
    });
    expect(chips).toEqual([
      'Agrupar: Producto',
      'Tienda: Gauss',
      'Con stock',
      'Sin Más de 60 d',
      'Sin ventas 30d',
      'Marcas (2)',
    ]);
    expect(count).toBe(5);
  });

  it('counts a grouping other than Producto, and "Solo con ventas" turned off', () => {
    const { chips, count } = activeFilterChips({ ...NO_FILTERS, groupBy: 'publication', soloConVentas: false });
    expect(chips).toEqual(['Agrupar: Publicación', 'Con y sin ventas']);
    expect(count).toBe(2);
  });

  it('names publication status and type filters', () => {
    const { chips } = activeFilterChips({ ...NO_FILTERS, pubStatus: ['active'], pubTypeExclude: ['full'] });
    expect(chips).toEqual(['Agrupar: Producto', 'Activa', 'Sin Full']);
  });
});

describe('phoneSortOptions', () => {
  it('offers only sorts the viewer may use: no margin sorts without the profit view', () => {
    const keys = phoneSortOptions({ canSeeMargin: false, tpOn: false, tpSolo: false }).map((o) => o.value);
    expect(keys).toEqual(['gross', 'units', 'stock', 'ageing', 'last_sale', 'title']);
  });

  it('adds Markup and Total Gauss with the profit view, and Total TP only with the TP costs', () => {
    expect(phoneSortOptions({ canSeeMargin: true, tpOn: false, tpSolo: false }).map((o) => o.value)).toEqual([
      'gross',
      'units',
      'markup',
      'total_gauss',
      'stock',
      'ageing',
      'last_sale',
      'title',
    ]);
    expect(phoneSortOptions({ canSeeMargin: true, tpOn: true, tpSolo: true }).map((o) => o.value)).toEqual([
      'gross',
      'units',
      'markup',
      'total_tp',
      'stock',
      'ageing',
      'last_sale',
      'title',
    ]);
  });
});
