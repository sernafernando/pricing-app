import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
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

describe('useLazyResource — alwaysRefetch', () => {
  it('refetches on mount even with a warm cache, and still writes to it', async () => {
    const cacheRef = { current: new Map() };
    const fetcher = vi.fn().mockResolvedValue('fresco');

    const first = renderHook(() => useLazyResource(cacheRef, 'k1', fetcher, { alwaysRefetch: true }));
    await waitFor(() => expect(first.result.current.data).toBe('fresco'));
    first.unmount();

    // The cache is still populated — other consumers read it (the promo filter
    // bar derives its types from these entries), so refetching must not mean
    // bypassing it.
    expect(cacheRef.current.get('k1')).toEqual({ status: 'ok', data: 'fresco' });

    renderHook(() => useLazyResource(cacheRef, 'k1', fetcher, { alwaysRefetch: true }));

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  });

  it('keeps serving the cache when the option is absent', async () => {
    const cacheRef = { current: new Map() };
    const fetcher = vi.fn().mockResolvedValue('cacheado');

    const first = renderHook(() => useLazyResource(cacheRef, 'k2', fetcher));
    await waitFor(() => expect(first.result.current.data).toBe('cacheado'));
    first.unmount();

    renderHook(() => useLazyResource(cacheRef, 'k2', fetcher));

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  });
});

describe('useLazyResource — reloadFetcher', () => {
  it('uses the plain fetcher for reload when one is given for mount', async () => {
    const cacheRef = { current: new Map() };
    const onMount = vi.fn().mockResolvedValue('mount');
    const onReload = vi.fn().mockResolvedValue('reload');

    const { result } = renderHook(() =>
      useLazyResource(cacheRef, 'k3', onMount, { alwaysRefetch: true, reloadFetcher: onReload }),
    );
    await waitFor(() => expect(result.current.data).toBe('mount'));
    expect(onReload).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.reload();
    });

    // The mount path may be expensive (it pulls from an external API); reload
    // must not silently repeat that cost.
    expect(onMount).toHaveBeenCalledTimes(1);
    expect(onReload).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe('reload');
  });
});
