import { describe, it, expect } from 'vitest';
import { CATALOG_STATES, catalogTooltip } from './catalogStatus';

// The tooltip Productos wrote inline before it shared this one: same text for every price it could render.
const productosBefore = (p) =>
  p.catalog_status === 'winning' && p.catalog_winner_price
    ? `Ganando a $${p.catalog_winner_price.toFixed(2)}`
    : p.catalog_status === 'competing' && p.catalog_price_to_win
      ? `Precio para ganar: $${p.catalog_price_to_win.toFixed(2)}`
      : p.catalog_status === 'sharing_first_place' && p.catalog_winner_price
        ? `Empatando a $${p.catalog_winner_price.toFixed(2)}`
        : '';

describe('catalogTooltip', () => {
  const cases = ['winning', 'competing', 'sharing_first_place', 'listed'].flatMap((status) =>
    [12345.5, 900, 0.5, 0, null, undefined].map((value) => ({
      catalog_status: status,
      catalog_winner_price: value,
      catalog_price_to_win: value,
    })),
  );

  it.each(cases)("reads as Productos' tooltip did: %o", (product) => {
    expect(catalogTooltip(product) ?? '').toBe(productosBefore(product));
  });

  it('a price that is not a number has no tooltip, where Productos used to break', () => {
    expect(catalogTooltip({ catalog_status: 'winning', catalog_winner_price: 'n/a' })).toBeUndefined();
  });
});

describe('CATALOG_STATES', () => {
  // Productos' badge before it shared the table: mark and tone per status, a neutral badge for any other.
  const markBefore = (status) =>
    status === 'winning' ? '🏆' : status === 'sharing_first_place' ? '🤝' : status === 'competing' ? '!' : '';
  const toneBefore = (status) =>
    status === 'winning'
      ? 'var(--success)'
      : status === 'sharing_first_place'
        ? 'var(--info)'
        : status === 'competing'
          ? 'var(--warning)'
          : 'var(--text-tertiary)';

  it.each(['winning', 'sharing_first_place', 'competing', 'listed'])("keeps Productos' mark and tone: %s", (status) => {
    expect(CATALOG_STATES[status]?.mark ?? '').toBe(markBefore(status));
    expect(CATALOG_STATES[status]?.tone ?? 'var(--text-tertiary)').toBe(toneBefore(status));
  });
});
