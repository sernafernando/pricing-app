/**
 * A bare `YYYY-MM-DD` (how the backend serializes every SQL `Date` column) is
 * parsed by the engine as UTC midnight. In Argentina (UTC-3) that falls on the
 * previous day, so the best-offer column showed "Hasta 30/12" for an offer
 * ending on 2026-12-31.
 *
 * The bug only shows in negative-offset zones, so the zone is pinned here;
 * the first test guards that premise.
 */

import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';

import { parseDateOnly } from './dateUtils';

const DAY_MONTH = { day: '2-digit', month: '2-digit' };

beforeAll(() => {
  vi.stubEnv('TZ', 'America/Argentina/Buenos_Aires');
});

afterAll(() => {
  vi.unstubAllEnvs();
});

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

  it('returns null for empty or unparseable values', () => {
    expect(parseDateOnly(null)).toBeNull();
    expect(parseDateOnly('')).toBeNull();
    expect(parseDateOnly('not-a-date')).toBeNull();
  });
});
