/**
 * Productos' Auto-recalcular cuotas (S12f2): the switch and the price saves (`recalcularCuotas`) always agree, even
 * when the browser refuses storage, and the switch follows a change made in Productos or Tienda in another tab.
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { recalcularCuotas, setRecalcularCuotasPreference } from '../pricing/priceWrites';
import useRecalcularCuotasAuto from './useRecalcularCuotasAuto';

const KEY = 'recalcularCuotasAuto';
const NO_OWN_SETTING = { recalcular_cuotas_auto: null };

afterEach(() => {
  vi.restoreAllMocks();
  setRecalcularCuotasPreference(true); // a working save clears what the tab kept
  window.localStorage.removeItem(KEY);
});

describe('useRecalcularCuotasAuto', () => {
  it('with storage blocked, the toggle still reaches the saves', () => {
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const { result } = renderHook(() => useRecalcularCuotasAuto());
    expect(result.current.enabled).toBe(true);
    act(() => result.current.toggle());
    expect(result.current.enabled).toBe(false);
    expect(recalcularCuotas(NO_OWN_SETTING)).toBe(false);
  });

  it('when only saving fails (a full storage), the saves follow the switch, not the old stored value', () => {
    window.localStorage.setItem(KEY, 'true');
    vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    const { result } = renderHook(() => useRecalcularCuotasAuto());
    act(() => result.current.toggle());
    expect(window.localStorage.getItem(KEY)).toBe('true'); // the save really failed
    expect(result.current.enabled).toBe(false);
    expect(recalcularCuotas(NO_OWN_SETTING)).toBe(false);
  });

  it('follows a change made in another tab, and the next toggle flips the live value', () => {
    const { result } = renderHook(() => useRecalcularCuotasAuto());
    expect(result.current.enabled).toBe(true);
    act(() => {
      window.localStorage.setItem(KEY, 'false');
      window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: 'false' }));
    });
    expect(result.current.enabled).toBe(false);
    act(() => result.current.toggle());
    expect(result.current.enabled).toBe(true);
    expect(window.localStorage.getItem(KEY)).toBe('true');
  });

  it("the product's own setting still wins over the switch", () => {
    const { result } = renderHook(() => useRecalcularCuotasAuto());
    act(() => result.current.toggle());
    expect(recalcularCuotas({ recalcular_cuotas_auto: true })).toBe(true);
  });
});
