import { useState, useEffect, useCallback, useRef } from 'react';

/**
 * Lazy fetch-once-on-first-need with an external cache.
 *
 * `cacheRef` is a `useRef(new Map())` owned by the caller (typically one level
 * above the conditionally-mounted consumer) so data survives unmount/remount
 * (e.g. collapse -> re-expand) without re-fetching.
 *
 * @param {import('react').MutableRefObject<Map>} cacheRef
 * @param {string|number} key - cache key (e.g. item_id, mla)
 * @param {(key: any) => Promise<any>} fetcher - resolves to the raw data to store
 * @param {{alwaysRefetch?: boolean}} [options] - `alwaysRefetch` refetches on
 *   every mount even with a warm cache, while STILL writing results into it.
 *   Bypassing the cache entirely is not equivalent: other consumers read these
 *   entries (the promo filter bar derives its types from them), so a panel
 *   that must always show fresh state has to keep populating it.
 *   `reloadFetcher` is used by `reload()` instead of `fetcher`, for when the
 *   mount path is expensive — e.g. it pulls from an external API — and a
 *   reload must not silently repeat that cost.
 * @returns {{ data: any, loading: boolean, error: any, reload: () => void }}
 */
export function useLazyResource(cacheRef, key, fetcher, { alwaysRefetch = false, reloadFetcher } = {}) {
  const cached = cacheRef.current.get(key);

  const [data, setData] = useState(cached?.status === 'ok' ? cached.data : null);
  const [error, setError] = useState(cached?.status === 'error' ? cached.error : null);
  const [loading, setLoading] = useState(alwaysRefetch || !cached);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const reloadFetcherRef = useRef(reloadFetcher);
  reloadFetcherRef.current = reloadFetcher;

  const load = useCallback((isStale = () => false, useReloadFetcher = false) => {
    setLoading(true);
    setError(null);
    const activeFetcher =
      useReloadFetcher && reloadFetcherRef.current ? reloadFetcherRef.current : fetcherRef.current;
    return Promise.resolve(activeFetcher(key))
      .then((result) => {
        if (isStale()) return;
        cacheRef.current.set(key, { status: 'ok', data: result });
        setData(result);
        setError(null);
        setLoading(false);
      })
      .catch((err) => {
        if (isStale()) return;
        cacheRef.current.set(key, { status: 'error', error: err });
        setError(err);
        setLoading(false);
      });
  }, [cacheRef, key]);

  useEffect(() => {
    let ignore = false;
    const entry = alwaysRefetch ? undefined : cacheRef.current.get(key);
    if (entry) {
      // Cache hit: skip fetch, sync local state to cached entry.
      setData(entry.status === 'ok' ? entry.data : null);
      setError(entry.status === 'error' ? entry.error : null);
      setLoading(false);
      return () => {
        ignore = true;
      };
    }
    load(() => ignore);
    return () => {
      ignore = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, alwaysRefetch]);

  const reload = useCallback(() => load(() => false, true), [load]);

  return { data, loading, error, reload };
}

export default useLazyResource;
