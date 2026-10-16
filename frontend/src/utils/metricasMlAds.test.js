import { describe, it, expect } from 'vitest';
import { ADS_MODE_HINTS, ADS_MODE_OPTIONS, adsModeNotice, adsRequestParams, originalAmount } from './metricasMlAds';

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

describe('adsRequestParams', () => {
  it('sends nothing at the default position, so the request is exactly the one made without ads', () => {
    expect(adsRequestParams('off')).toEqual({});
    expect(adsRequestParams(undefined)).toEqual({});
  });

  it.each(['mla', 'todo'])('sends the %s position as the API value', (position) => {
    expect(adsRequestParams(position)).toEqual({ publicidad: position });
  });
});

describe('ads toggle positions', () => {
  it('offers off, mla and todo, in that order, each with its own hint', () => {
    expect(ADS_MODE_OPTIONS.map((option) => option.value)).toEqual(['off', 'mla', 'todo']);
    expect(Object.keys(ADS_MODE_HINTS)).toEqual(['off', 'mla', 'todo']);
  });
});
