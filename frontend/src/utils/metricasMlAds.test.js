import { describe, it, expect } from 'vitest';
import { adsModeNotice, originalAmount } from './metricasMlAds';

describe('adsModeNotice', () => {
  it('says nothing while the applied position is the requested one', () => {
    expect(adsModeNotice({ requested: 'mla', applied: 'mla' })).toBeNull();
    expect(adsModeNotice({ requested: 'todo', applied: 'todo' })).toBeNull();
  });

  it('explains a "todo" that the view could only apply as "mla"', () => {
    expect(adsModeNotice({ requested: 'todo', applied: 'mla' })).toEqual({
      message: 'Con filtros solo se restan los Ads de publicaciones',
      chip: 'Aplicado: Ads de publicaciones',
    });
  });

  it('says nothing without an ads block (the toggle is off)', () => {
    expect(adsModeNotice(null)).toBeNull();
  });
});

describe('originalAmount', () => {
  it('adds back what was subtracted, rounded to the cent', () => {
    expect(originalAmount(44131773.32, 17516239.51)).toBe(61648012.83);
  });

  it('is null when there is no adjusted value to undo', () => {
    expect(originalAmount(null, 100)).toBeNull();
  });
});
