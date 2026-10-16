/**
 * A bare `YYYY-MM-DD` (how the backend serializes every SQL `Date` column) is
 * parsed by the engine as UTC midnight. In Argentina (UTC-3) that falls on the
 * previous day, so the best-offer column showed "Hasta 30/12" for an offer
 * ending on 2026-12-31.
 *
 * The bug only shows in negative-offset zones, so the unit project pins TZ
 * (vite.config.js);
 * the first test guards that premise.
 */

import { describe, it, expect } from 'vitest';

import { formatDateOnly, parseDateOnly } from './dateUtils';

const DAY_MONTH = { day: '2-digit', month: '2-digit' };

describe('test environment premise', () => {
  it('runs in a zone where native parsing shifts the day back', () => {
    expect(new Date('2026-12-31').toLocaleDateString('es-AR', DAY_MONTH)).toBe('30/12');
  });
});

describe('parseDateOnly', () => {
  it('keeps the calendar day of a bare YYYY-MM-DD', () => {
    expect(parseDateOnly('2026-12-31').toLocaleDateString('es-AR', DAY_MONTH)).toBe('31/12');
  });

  it('keeps the calendar day on the first of the month', () => {
    const date = parseDateOnly('2026-03-01');
    expect([date.getFullYear(), date.getMonth(), date.getDate()]).toEqual([2026, 2, 1]);
  });

  it('parses values that carry a time as-is', () => {
    const value = '2026-12-31T10:00:00';
    expect(parseDateOnly(value).getTime()).toBe(new Date(value).getTime());
  });

  it('accepts a leap day in a leap year', () => {
    const date = parseDateOnly('2028-02-29');
    expect([date.getFullYear(), date.getMonth(), date.getDate()]).toEqual([2028, 1, 29]);
  });

  it.each(['2026-02-30', '2027-02-29', '2026-04-31', '2026-13-01', '2026-00-10', '2026-01-00'])(
    'returns null for the impossible calendar date %s instead of rolling over',
    (value) => {
      expect(parseDateOnly(value)).toBeNull();
    },
  );

  it('keeps years 0000-0099 literal instead of mapping them to 1900-1999', () => {
    const date = parseDateOnly('0099-12-31');
    expect([date.getFullYear(), date.getMonth(), date.getDate()]).toEqual([99, 11, 31]);
  });

  it('returns null for empty or unparseable values', () => {
    expect(parseDateOnly(null)).toBeNull();
    expect(parseDateOnly('')).toBeNull();
    expect(parseDateOnly('not-a-date')).toBeNull();
  });
});

describe('formatDateOnly', () => {
  it('formats a bare YYYY-MM-DD on its calendar day with es-AR defaults', () => {
    expect(formatDateOnly('2026-12-31')).toBe('31/12/2026');
  });

  it('passes the format options through', () => {
    expect(formatDateOnly('2026-12-31', DAY_MONTH)).toBe('31/12');
  });

  it.each([null, undefined, '', 'not-a-date', '2026-02-30'])("returns '-' for %s", (value) => {
    expect(formatDateOnly(value)).toBe('-');
  });
});
