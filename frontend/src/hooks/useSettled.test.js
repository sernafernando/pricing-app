import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useSettled } from './useSettled';

const run = (initial) =>
  renderHook(({ value, keyOf, immediate }) => useSettled(value, keyOf, 250, immediate), { initialProps: initial });

describe('useSettled (pubml-lentitud S2)', () => {
  afterEach(() => vi.useRealTimers());

  it('answers the live value while immediate, and right after it (nothing was asked yet)', () => {
    vi.useFakeTimers();
    const { result, rerender } = run({ value: { estado: '' }, keyOf: 'a', immediate: true });
    expect(result.current).toEqual({ value: { estado: '' }, key: 'a' });
    rerender({ value: { estado: 'paused' }, keyOf: 'b', immediate: false }); // the preset lands as the layer settles
    expect(result.current).toEqual({ value: { estado: 'paused' }, key: 'b' });
  });

  it('keeps the asked value while a new key is still changing, and settles 250 ms after the last one', () => {
    vi.useFakeTimers();
    const { result, rerender } = run({ value: { v: 1 }, keyOf: 'a', immediate: false });
    act(() => vi.advanceTimersByTime(300));
    rerender({ value: { v: 2 }, keyOf: 'b', immediate: false });
    expect(result.current.key).toBe('a');
    act(() => vi.advanceTimersByTime(200));
    rerender({ value: { v: 3 }, keyOf: 'c', immediate: false });
    act(() => vi.advanceTimersByTime(200));
    expect(result.current).toEqual({ value: { v: 1 }, key: 'a' }); // 'b' never asked
    act(() => vi.advanceTimersByTime(60));
    expect(result.current).toEqual({ value: { v: 3 }, key: 'c' });
  });

  it('a change of the same key (page, sort) is answered at once', () => {
    vi.useFakeTimers();
    const { result, rerender } = run({ value: { pagina: 1 }, keyOf: 'a', immediate: false });
    act(() => vi.advanceTimersByTime(300));
    rerender({ value: { pagina: 2 }, keyOf: 'a', immediate: false });
    expect(result.current).toEqual({ value: { pagina: 2 }, key: 'a' });
  });

  it('going back to the asked key while settling answers it at once', () => {
    vi.useFakeTimers();
    const { result, rerender } = run({ value: { v: 1 }, keyOf: 'a', immediate: false });
    act(() => vi.advanceTimersByTime(300));
    rerender({ value: { v: 2 }, keyOf: 'b', immediate: false });
    rerender({ value: { v: 1 }, keyOf: 'a', immediate: false });
    expect(result.current).toEqual({ value: { v: 1 }, key: 'a' });
  });
});
