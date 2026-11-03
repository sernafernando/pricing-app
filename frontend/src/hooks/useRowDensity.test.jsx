import { describe, it, expect, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import useRowDensity from './useRowDensity';

const KEY = 'test.filas-finas';

describe('useRowDensity', () => {
  beforeEach(() => localStorage.clear());

  it('starts with the current density (not dense) when nothing is stored', () => {
    const { result } = renderHook(() => useRowDensity(KEY));
    expect(result.current.dense).toBe(false);
  });

  it('flips the density both ways', () => {
    const { result } = renderHook(() => useRowDensity(KEY));
    act(() => result.current.toggleDense());
    expect(result.current.dense).toBe(true);
    act(() => result.current.toggleDense());
    expect(result.current.dense).toBe(false);
  });

  it('keeps the choice across a reload, per screen key', () => {
    const first = renderHook(() => useRowDensity(KEY));
    act(() => first.result.current.toggleDense());
    first.unmount();
    expect(renderHook(() => useRowDensity(KEY)).result.current.dense).toBe(true);
    expect(renderHook(() => useRowDensity('other.screen')).result.current.dense).toBe(false);
  });

  it.each(['not json', '"yes"', '1', '{}'])('falls back to the current density on a stored %s', (stored) => {
    localStorage.setItem(KEY, stored);
    expect(renderHook(() => useRowDensity(KEY)).result.current.dense).toBe(false);
  });
});
