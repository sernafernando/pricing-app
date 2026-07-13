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
 * @returns {{ data: any, loading: boolean, error: any, reload: () => void }}
 */
export function useLazyResource(cacheRef, key, fetcher) {
  const cached = cacheRef.current.get(key);

  const [data, setData] = useState(cached?.status === 'ok' ? cached.data : null);
  const [error, setError] = useState(cached?.status === 'error' ? cached.error : null);
  const [loading, setLoading] = useState(!cached);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback((isStale = () => false) => {
    setLoading(true);
    setError(null);
    return Promise.resolve(fetcherRef.current(key))
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
    const entry = cacheRef.current.get(key);
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
  }, [key]);

  const reload = useCallback(() => {
    load();
  }, [load]);

  return { data, loading, error, reload };
}

export default useLazyResource;
