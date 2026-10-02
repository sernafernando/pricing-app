import { describe, it, expect } from 'vitest';
import {
  formatUnits,
  formatPct,
  formatDeltaPp,
  formatDeltaPct,
  deltaTone,
  ageingTone,
  formatAgeing,
  publicationDescriptor,
  weeklySums,
  formatLastSale,
} from './metricasMlFormat';

describe('metricasMlFormat', () => {
  it('formats units and percentages the es-AR way', () => {
    expect(formatUnits(3412)).toBe('3.412');
    expect(formatUnits(null)).toBe('—');
    expect(formatPct(21.6)).toBe('21,6%');
    expect(formatPct(-8.4)).toBe('-8,4%');
    expect(formatPct(null)).toBe('—');
  });

  it('formats deltas with arrow and sign, never a fake zero', () => {
    expect(formatDeltaPp(2.1)).toBe('▲ +2,1 pp');
    expect(formatDeltaPp(-1.5)).toBe('▼ -1,5 pp');
    expect(formatDeltaPp(0)).toBe('– 0,0 pp');
    expect(formatDeltaPp(null)).toBe('—');
    expect(formatDeltaPct(12.4)).toBe('▲ +12,4%');
    expect(formatDeltaPct(-2.3)).toBe('▼ -2,3%');
  });

  it('tones a delta by direction', () => {
    expect(deltaTone(1)).toBe('up');
    expect(deltaTone(-1)).toBe('down');
    expect(deltaTone(0)).toBe('flat');
    expect(deltaTone(null)).toBe(null);
  });

  it('tones ageing at 30 and 60 days', () => {
    expect(ageingTone(1)).toBe('good');
    expect(ageingTone(30)).toBe('good');
    expect(ageingTone(45)).toBe('low');
    expect(ageingTone(61)).toBe('negative');
    expect(ageingTone(null)).toBe(null);
    expect(formatAgeing(18)).toBe('18 d');
    expect(formatAgeing(null)).toBe('—');
  });

  it('describes a publication: type · Full · status', () => {
    expect(
      publicationDescriptor({ listing_type: 'clasica', is_full: true, is_catalog: false, status: 'active' }),
    ).toBe('Clásica · Full · Activa');
    expect(
      publicationDescriptor({ listing_type: 'premium', is_full: false, is_catalog: true, status: 'paused' }),
    ).toBe('Premium · Catálogo · Pausada');
    expect(publicationDescriptor({ listing_type: null, status: null })).toBe('Sin estado');
  });

  it('sums a daily series into weeks ending on the last day', () => {
    expect(weeklySums([1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2])).toEqual([7, 14]);
    expect(weeklySums([5, 1, 1, 1, 1, 1, 1, 1])).toEqual([5, 7]);
  });

  it('formats the last sale as dd/mm hh:mm in Buenos Aires plus a relative day', () => {
    const now = new Date('2026-09-30T18:00:00Z');
    expect(formatLastSale('2026-09-29T21:40:00Z', now)).toEqual({ when: '29/09 18:40', ago: 'hace 1 día' });
    expect(formatLastSale('2026-09-30T13:00:00Z', now)).toEqual({ when: '30/09 10:00', ago: 'hoy' });
    expect(formatLastSale(null, now)).toEqual({ when: '—', ago: 'sin ventas' });
  });
});
