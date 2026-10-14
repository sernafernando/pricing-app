/**
 * Tests for the date range of useVentasMLFilters: Ventas ML opens on the
 * current month (Argentina time) instead of loading every sale, and the URL
 * (`desde`/`hasta`, or `rango=todo`) wins over that default.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { useVentasMLFilters } from './useVentasMLFilters';

function setup(url = '/') {
  return renderHook(() => useVentasMLFilters(), {
    wrapper: ({ children }) => <MemoryRouter initialEntries={[url]}>{children}</MemoryRouter>,
  });
}

// Instants are given in UTC on purpose: Argentina is UTC-3 all year, so the
// same instant is a different calendar day there.
function at(iso) {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(iso));
}

afterEach(() => {
  vi.useRealTimers();
});

describe('default range', () => {
  it('is the current month up to today when the URL carries no date', () => {
    at('2026-10-14T15:00:00Z'); // 12:00 in Argentina
    const { result } = setup('/');
    expect(result.current.dateRange).toEqual({
      desde: '2026-10-01',
      hasta: '2026-10-14',
      filtro: 'mesActual',
    });
  });

  it('on day 1 of the month the range is that single day', () => {
    at('2026-11-01T12:00:00Z');
    const { result } = setup('/');
    expect(result.current.dateRange.desde).toBe('2026-11-01');
    expect(result.current.dateRange.hasta).toBe('2026-11-01');
  });

  it('uses the Argentine calendar day, not UTC: 23:30 on the 31st is still October', () => {
    at('2026-11-01T02:30:00Z'); // 2026-10-31 23:30 in Argentina
    const { result } = setup('/');
    expect(result.current.dateRange).toEqual({
      desde: '2026-10-01',
      hasta: '2026-10-31',
      filtro: 'mesActual',
    });
  });

  it('uses the Argentine day just after UTC midnight: 00:30 UTC on the 1st is still the previous month', () => {
    at('2026-12-01T00:30:00Z'); // 2026-11-30 21:30 in Argentina
    const { result } = setup('/');
    expect(result.current.dateRange.desde).toBe('2026-11-01');
    expect(result.current.dateRange.hasta).toBe('2026-11-30');
  });

  it('does not shift while the page stays open across a month change', () => {
    at('2026-10-31T20:00:00Z');
    const { result, rerender } = setup('/');
    vi.setSystemTime(new Date('2026-11-01T20:00:00Z'));
    rerender();
    expect(result.current.dateRange.desde).toBe('2026-10-01');
  });
});

describe('explicit URL wins', () => {
  it('reads desde/hasta from the URL instead of the default', () => {
    at('2026-10-14T15:00:00Z');
    const { result } = setup('/?desde=2026-08-01&hasta=2026-08-15');
    expect(result.current.dateRange).toEqual({
      desde: '2026-08-01',
      hasta: '2026-08-15',
      filtro: 'custom',
    });
  });

  it('keeps a half-open range as the URL wrote it, without borrowing the default', () => {
    at('2026-10-14T15:00:00Z');
    const { result } = setup('/?desde=2026-08-01');
    expect(result.current.dateRange.desde).toBe('2026-08-01');
    expect(result.current.dateRange.hasta).toBe('');
  });

  it('rango=todo means no date filter at all', () => {
    at('2026-10-14T15:00:00Z');
    const { result } = setup('/?rango=todo');
    expect(result.current.dateRange).toEqual({ desde: '', hasta: '', filtro: null });
  });

  it('ignores a malformed date and falls back to the default', () => {
    at('2026-10-14T15:00:00Z');
    const { result } = setup('/?desde=ayer&hasta=nunca');
    expect(result.current.dateRange.desde).toBe('2026-10-01');
  });
});

describe('impossible dates', () => {
  it('ignores a well-shaped date that does not exist, like 2026-13-45 or 2026-02-30', () => {
    at('2026-10-14T15:00:00Z');
    const { result } = setup('/?desde=2026-13-45&hasta=2026-02-30');
    expect(result.current.dateRange.desde).toBe('2026-10-01');
    expect(result.current.dateRange.hasta).toBe('2026-10-14');
  });
});

describe('setDateRange', () => {
  it('writes the range to the URL so it survives a reload and back/forward', () => {
    at('2026-10-14T15:00:00Z');
    const { result } = setup('/');
    act(() => result.current.setDateRange({ desde: '2026-09-11', hasta: '2026-09-17', filtro: '7d' }));
    expect(result.current.dateRange).toEqual({
      desde: '2026-09-11',
      hasta: '2026-09-17',
      filtro: 'custom',
    });
  });

  it('clearing the range is an explicit "todo", not a fall back to the default month', () => {
    at('2026-10-14T15:00:00Z');
    const { result } = setup('/');
    act(() => result.current.setDateRange({ desde: '', hasta: '', filtro: null }));
    expect(result.current.dateRange).toEqual({ desde: '', hasta: '', filtro: null });
  });

  it('highlights Mes actual again when the chosen range is the current month', () => {
    at('2026-10-14T15:00:00Z');
    const { result } = setup('/?rango=todo');
    act(() => result.current.setDateRange({ desde: '2026-10-01', hasta: '2026-10-14', filtro: 'mesActual' }));
    expect(result.current.dateRange.filtro).toBe('mesActual');
  });
});

describe('clearUrlFilters', () => {
  it('clears search, product filters and the range in a single update', () => {
    at('2026-10-14T15:00:00Z');
    const { result } = setup('/?q=abc&marcas=TP-Link&desde=2026-08-01&hasta=2026-08-15&orden=7');
    act(() => result.current.clearUrlFilters());
    expect(result.current.searchQuery).toBe('');
    expect(result.current.productFilters.marcas).toEqual([]);
    expect(result.current.dateRange).toEqual({ desde: '', hasta: '', filtro: null });
    // The selection is not a filter: it stays.
    expect(result.current.selectedOrderId).toBe(7);
  });
});
