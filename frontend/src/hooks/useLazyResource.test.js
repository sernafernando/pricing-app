import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useRef } from 'react';
import { useLazyResource } from './useLazyResource';

function setup() {
  const cacheRef = { current: new Map() };
  return cacheRef;
}

describe('useLazyResource', () => {
  it('fetches once on mount and exposes loading then data', async () => {
    const cacheRef = setup();
    const fetcher = vi.fn().mockResolvedValue({ foo: 'bar' });

    const { result } = renderHook(() => useLazyResource(cacheRef, 'k1', fetcher));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith('k1');
    expect(result.current.data).toEqual({ foo: 'bar' });
    expect(result.current.error).toBeNull();
  });

  it('cache hit skips the fetcher on remount with same key', async () => {
    const cacheRef = setup();
    const fetcher = vi.fn().mockResolvedValue({ foo: 'bar' });

    const { result, unmount } = renderHook(() => useLazyResource(cacheRef, 'k1', fetcher));
    await waitFor(() => expect(result.current.loading).toBe(false));
    unmount();

    const { result: result2 } = renderHook(() => useLazyResource(cacheRef, 'k1', fetcher));
    // Cache hit should synchronously produce loading=false eventually without a second fetch call
    await waitFor(() => expect(result2.current.loading).toBe(false));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result2.current.data).toEqual({ foo: 'bar' });
  });

  it('error path sets error and clears loading', async () => {
    const cacheRef = setup();
    const err = new Error('boom');
    const fetcher = vi.fn().mockRejectedValue(err);

    const { result } = renderHook(() => useLazyResource(cacheRef, 'k1', fetcher));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe(err);
    expect(result.current.data).toBeNull();
  });

  it('reload() re-fetches and overwrites the cache', async () => {
    const cacheRef = setup();
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ v: 1 })
      .mockResolvedValueOnce({ v: 2 });

    const { result } = renderHook(() => useLazyResource(cacheRef, 'k1', fetcher));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual({ v: 1 });

    await act(async () => {
      await result.current.reload();
    });

    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(result.current.data).toEqual({ v: 2 });
    expect(cacheRef.current.get('k1')).toEqual({ status: 'ok', data: { v: 2 } });
  });

  it('ignores a stale response when key changes before the prior fetch resolves', async () => {
    const cacheRef = setup();
    let resolveA;
    const fetcher = vi.fn((key) => {
      if (key === 'a') {
        return new Promise((resolve) => {
          resolveA = resolve;
        });
      }
      return Promise.resolve({ key: 'b' });
    });

    const { result, rerender } = renderHook(
      ({ key }) => useLazyResource(cacheRef, key, fetcher),
      { initialProps: { key: 'a' } }
    );

    rerender({ key: 'b' });
    await waitFor(() => expect(result.current.data).toEqual({ key: 'b' }));

    await act(async () => {
      resolveA({ key: 'a' });
      await Promise.resolve();
    });

    expect(result.current.data).toEqual({ key: 'b' });
  });

  it('does not update state after unmount when the fetch resolves late', async () => {
    const cacheRef = setup();
    let resolveIt;
    const fetcher = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveIt = resolve;
        })
    );
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { unmount } = renderHook(() => useLazyResource(cacheRef, 'k1', fetcher));
    unmount();

    await act(async () => {
      resolveIt({ foo: 'bar' });
      await Promise.resolve();
    });

    const actWarnings = consoleError.mock.calls.filter((call) =>
      String(call[0]).includes('not wrapped in act')
    );
    expect(actWarnings.length).toBe(0);
    consoleError.mockRestore();
  });
});
