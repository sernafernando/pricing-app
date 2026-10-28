import { useEffect, useState } from 'react';

/**
 * One read of the Publicaciones ML view for `params` (`read(params, { signal })`, a stable API function), asked
 * again only when they change (or on `reload`). A request that is no longer the latest is aborted, and the last good
 * answer stays while the next one loads.
 */
export function useViewRead(read, params, enabled) {
  const [state, setState] = useState({ data: null, loading: enabled, error: null });
  const [reloadToken, setReloadToken] = useState(0);
  const key = JSON.stringify(params);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    setState((current) => ({ ...current, loading: true, error: null }));
    read(JSON.parse(key), { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) setState({ data: response.data, loading: false, error: null });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState((current) => ({ ...current, loading: false, error }));
      });
    return () => controller.abort();
  }, [read, key, enabled, reloadToken]);

  return { ...state, reload: () => setReloadToken((token) => token + 1) };
}

export default useViewRead;
