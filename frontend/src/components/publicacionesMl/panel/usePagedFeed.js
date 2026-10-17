import { useCallback, useEffect, useRef, useState } from 'react';

const LOADING = { status: 'loading', items: [], meta: null, nextCursor: null, error: null, more: 'idle' };

/**
 * A newest-first feed read a page at a time with an opaque cursor (the Eventos
 * and Historial tabs).
 *
 * `fetchPage(itemId, params)` resolves to the response body; `listKey` names the
 * list inside it (`events`, `entries`). The first page is requested without a
 * cursor; `loadMore` asks for the next one with the previous `next_cursor` and
 * appends it. A failed next page keeps what is already shown (`more: 'error'`)
 * and is retried by calling `loadMore` again.
 *
 * Every request starts from "loading" for its publication, and an answer that
 * arrives after the selection moved on, or after a newer request, is dropped.
 * `meta` is the rest of the first page (`enabled`, ...); `reload` re-asks.
 *
 * `query` (optional, e.g. `{ tecnicos: true }`) goes with every request; a
 * different query starts the feed over from its first page.
 */
export function usePagedFeed(fetchPage, itemId, listKey, query) {
  // Compared by value, so a literal object from the caller does not refetch on every render.
  const queryKey = JSON.stringify(query ?? {});
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState(LOADING);
  const [owner, setOwner] = useState(null);
  // Bumped by every first-page request: older answers are ignored.
  const generation = useRef(0);
  const fetchRef = useRef(fetchPage);
  // Refs are written in effects, never while rendering. Declared first so the fetch effect below sees the latest.
  useEffect(() => {
    fetchRef.current = fetchPage;
  }, [fetchPage]);

  useEffect(() => {
    const mine = ++generation.current;
    setState(LOADING);
    setOwner(`${itemId}|${queryKey}`);
    fetchRef
      .current(itemId, JSON.parse(queryKey))
      .then((response) => {
        if (generation.current !== mine) return;
        const { [listKey]: items = [], next_cursor: nextCursor = null, ...meta } = response.data ?? {};
        setState({ status: 'ready', items, meta, nextCursor, error: null, more: 'idle' });
      })
      .catch((error) => {
        if (generation.current === mine) setState({ ...LOADING, status: 'error', error });
      });
    return () => {
      generation.current += 1;
    };
  }, [itemId, listKey, queryKey, attempt]);

  // The latest state, readable from `loadMore` without running a request inside a state updater.
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const loadMore = useCallback(() => {
    const current = stateRef.current;
    if (current.status !== 'ready' || current.nextCursor == null || current.more === 'loading') return;
    const mine = generation.current;
    setState((now) => ({ ...now, more: 'loading' }));
    // A second click before the re-render must not ask for the same page twice.
    stateRef.current = { ...current, more: 'loading' };
    fetchRef
      .current(itemId, { ...JSON.parse(queryKey), cursor: current.nextCursor })
      .then((response) => {
        if (generation.current !== mine) return;
        const { [listKey]: items = [], next_cursor: nextCursor = null } = response.data ?? {};
        setState((now) => ({ ...now, items: [...now.items, ...items], nextCursor, more: 'idle' }));
      })
      .catch(() => {
        if (generation.current === mine) setState((now) => ({ ...now, more: 'error' }));
      });
  }, [itemId, listKey, queryKey]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  // The first render for a new publication (or query) still holds the old one's state.
  if (owner !== `${itemId}|${queryKey}`) return { ...LOADING, loadMore, reload };
  return { ...state, loadMore, reload };
}
