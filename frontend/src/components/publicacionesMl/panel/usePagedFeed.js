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
 */
export function usePagedFeed(fetchPage, itemId, listKey) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState(LOADING);
  const [owner, setOwner] = useState(null);
  // Bumped by every first-page request: older answers are ignored.
  const generation = useRef(0);
  const fetchRef = useRef(fetchPage);
  fetchRef.current = fetchPage;

  useEffect(() => {
    const mine = ++generation.current;
    setState(LOADING);
    setOwner(itemId);
    fetchRef
      .current(itemId, {})
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
  }, [itemId, listKey, attempt]);

  const loadMore = useCallback(() => {
    const mine = generation.current;
    setState((current) => {
      if (current.status !== 'ready' || current.nextCursor == null || current.more === 'loading') return current;
      const cursor = current.nextCursor;
      fetchRef
        .current(itemId, { cursor })
        .then((response) => {
          if (generation.current !== mine) return;
          const { [listKey]: items = [], next_cursor: nextCursor = null } = response.data ?? {};
          setState((now) => ({ ...now, items: [...now.items, ...items], nextCursor, more: 'idle' }));
        })
        .catch(() => {
          if (generation.current === mine) setState((now) => ({ ...now, more: 'error' }));
        });
      return { ...current, more: 'loading' };
    });
  }, [itemId, listKey]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  // The first render for a new publication still holds the old one's state.
  if (owner !== itemId) return { ...LOADING, loadMore, reload };
  return { ...state, loadMore, reload };
}
