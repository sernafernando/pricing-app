/**
 * Productos' stat cards (S12d4): what each card counts and what its click filters (`aplicarFiltroStat`): the card's
 * own filter, with every other filter a card sets cleared, and the rest of the screen's filters kept.
 */
import { describe, expect, it } from 'vitest';
import { STAT_FILTER_KEYS, isStatActive, statCardGroups, statUpdates } from './statCards';

const NO_STAT_FILTER = Object.fromEntries(STAT_FILTER_KEYS.map((key) => [key, key === 'stock' ? [] : '']));
const filters = (overrides = {}) => ({ ...NO_STAT_FILTER, marcas: ['TP-Link'], q: 'router', ...overrides });
const item = (groups, label) => groups.flatMap((group) => group.items).find((entry) => entry.label === label);

describe('statUpdates', () => {
  it("sets the card's filter and clears every other filter a card sets", () => {
    expect(statUpdates({ stock: ['erp_con_stock'], precio: 'sin_precio' })).toEqual({
      ...Object.fromEntries(STAT_FILTER_KEYS.map((key) => [key, ''])),
      stock: ['erp_con_stock'],
      precio: 'sin_precio',
    });
  });

  it('touches only the filters the cards own, so the search, brands and the rest stay', () => {
    expect(Object.keys(statUpdates({ oferta: 'con_oferta' })).sort()).toEqual([...STAT_FILTER_KEYS].sort());
    expect(STAT_FILTER_KEYS).not.toContain('q');
    expect(STAT_FILTER_KEYS).not.toContain('marcas');
  });
});

describe('statCardGroups', () => {
  const stats = {
    total: 40,
    con_stock: 30,
    con_precio: 35,
    con_stock_sin_precio: 3,
    nuevos: 5,
    nuevos_sin_precio: 2,
    oferta_sin_rebate: 4,
    markup_negativo_clasica: 6,
    markup_negativo_rebate: 1,
    markup_negativo_oferta: 0,
    markup_negativo_web: 2,
  };

  it("has Productos' cards, labels and filters", () => {
    const groups = statCardGroups(stats, { canSeeMargin: true });
    expect(groups.map((group) => group.label)).toEqual([
      'Total Productos',
      'Stock & Precio',
      'Nuevos (7 días)',
      'Oferta sin Rebate',
      'Markup Negativo',
    ]);
    expect(item(groups, 'Stock sin $')).toMatchObject({ value: 3, filter: { stock: ['erp_con_stock'], precio: 'sin_precio' } });
    expect(item(groups, 'Con Precio')).toMatchObject({ value: 35, filter: { precio: 'con_precio' } });
    expect(groups[2].items.map((entry) => [entry.label, entry.value])).toEqual([
      ['Total', 5],
      ['Sin Precio', 2],
    ]);
    expect(groups[2].items[1].filter).toEqual({ nuevos: 'ultimos_7_dias', precio: 'sin_precio' });
    expect(groups[3].items[0]).toMatchObject({ value: 4, filter: { oferta: 'con_oferta', rebate: 'sin_rebate' } });
    expect(groups[4].items.map((entry) => [entry.label, entry.value, entry.filter])).toEqual([
      ['Clásica', 6, { mkclasica: 'negativo' }],
      ['Rebate', 1, { mkrebate: 'negativo' }],
      ['Oferta', 0, { mkoferta: 'negativo' }],
      ['Web', 2, { mkwebtransf: 'negativo' }],
    ]);
  });

  it('Total clears the filters instead of setting one', () => {
    expect(statCardGroups(stats, {})[0].items[0]).toMatchObject({ value: 40, reset: true });
  });

  it('without the margin there is no markup card', () => {
    expect(statCardGroups(stats, { canSeeMargin: false }).map((group) => group.label)).not.toContain('Markup Negativo');
  });

  it('with no answer yet every figure is unknown, never 0', () => {
    expect(item(statCardGroups(null, {}), 'Con Stock').value).toBeNull();
  });
});

describe('isStatActive', () => {
  it("is on when the screen's card filters are exactly the card's", () => {
    const card = { stock: ['erp_con_stock'], precio: 'sin_precio' };
    expect(isStatActive(filters({ stock: ['erp_con_stock'], precio: 'sin_precio' }), card)).toBe(true);
    expect(isStatActive(filters({ stock: ['erp_con_stock'] }), card)).toBe(false);
    // another card filter on top: not this card any more
    expect(isStatActive(filters({ stock: ['erp_con_stock'], precio: 'sin_precio', rebate: 'con_rebate' }), card)).toBe(false);
    // a second stock value: not this card either
    expect(isStatActive(filters({ stock: ['erp_con_stock', 'full_sin_stock'], precio: 'sin_precio' }), card)).toBe(false);
  });
});
