import { describe, it, expect } from 'vitest';
import { resolvePromoName } from './resolvePromoName';

describe('resolvePromoName', () => {
  it('returns the top-level name when present', () => {
    expect(resolvePromoName({ name: '2x1' })).toBe('2x1');
  });

  it('falls back to payload.name when the top-level name is absent', () => {
    expect(resolvePromoName({ name: null, payload: { name: 'PREMIUM JULIO' } })).toBe('PREMIUM JULIO');
  });

  it('falls back to payload.name when the top-level name is an empty string', () => {
    expect(resolvePromoName({ name: '', payload: { name: 'PREMIUM JULIO' } })).toBe('PREMIUM JULIO');
  });

  it('returns null (not promotion_type/promotion_id) when genuinely unnamed', () => {
    // Deliberate: the filter universe stops at name/payload.name so a promo
    // with no real name always groups under the "(sin nombre)" sentinel,
    // regardless of what a caller may separately show as a display fallback.
    expect(resolvePromoName({ name: null, payload: {}, promotion_type: 'DEAL', promotion_id: 'X' })).toBeNull();
  });

  it('normalizes a missing payload to null', () => {
    expect(resolvePromoName({ name: null })).toBeNull();
  });
});
