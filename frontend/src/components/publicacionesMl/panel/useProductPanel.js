import { useCallback, useEffect, useRef, useState } from 'react';
import { publicacionesMlAPI } from '../../../services/api';
import { buildProductsParams } from '../../../hooks/usePublicacionesMLFilters';
import { buildLeafParams, leafScope } from '../groupNodes';
import { readProduct } from '../useProductRows';

/**
 * The data of the product panel of Publicaciones ML: one product row of the Producto view (`productKey` is its
 * `/view/products` `key`, the URL's `prod`) under the page's filters.
 *
 * The summary is that very row, asked to `/view/products` with the list's params plus the product (`producto`, or
 * `sin_producto` for the "Sin producto" row) and one row from the start. Its publications are what opening the row
 * asks (`useProductRows`): `/view/items` with the row's `params` over the user's (`buildLeafParams`), 100 at a time.
 * A product the filters leave out has no summary and no publications.
 *
 * Productos' two escapes of its panel: "ver todos" (`showAll`) lists the publications with only the row's `params`,
 * without the user's filters, and "Ver eliminadas" (`toggleDeleted`) adds the deleted ones of that scope after its
 * live ones (the backend hides them unless `estado` has `gone`). Each count is the `total` of a `limit: 1` request:
 * `hiddenCount` is what "ver todos" adds (deleted ones only while they are shown), `deletedCount` what "Ver
 * eliminadas" adds, `onlyDeleted` that the scope has nothing but deleted ones.
 *
 * A new product or a new filter set starts over with both escapes off, and an answer to a request of the previous
 * one (or, for the list, of the previous escapes) is dropped.
 */
export const NO_PRODUCT_KEY = '0';

const NO_ESCAPES = { verTodos: false, showDeleted: false };
// `null` = not known (yet, or its request failed): nothing is offered on it.
const NO_COUNTS = { allLive: null, allGone: null, filteredGone: null };
const IDLE = {
  summary: null,
  items: [],
  liveTotal: null,
  goneTotal: 0,
  status: 'idle',
  error: null,
  escapes: NO_ESCAPES,
  counts: NO_COUNTS,
};

/** The `/view/products` query of one product row: the list's filters, that product, its only row. */
export function buildSummaryParams(filters, productKey) {
  const product = productKey === NO_PRODUCT_KEY ? { sin_producto: true } : { producto: productKey };
  return { ...buildProductsParams(filters, 1), ...product, limit: 1, offset: 0 };
}

/** Pages are by offset: a publication that moved between two requests stays once. */
function appendPage(rows, page) {
  const seen = new Set(rows.map((row) => row.item_id));
  return [...rows, ...page.filter((row) => !seen.has(row.item_id))];
}

/**
 * The counts behind the escapes, each the `total` of one `limit: 1` request; one request per distinct query (under
 * only an `estado` filter the deleted ones with and without the filters are the same query). Without a filter the
 * scope without filters is the list's own: only its deleted ones are asked.
 */
function countRequests(filters, summary) {
  const asked = new Map();
  const total = (options) => {
    const params = buildLeafParams(filters, summary, 0, { ...options, limit: 1 });
    const key = JSON.stringify(params);
    if (!asked.has(key)) asked.set(key, publicacionesMlAPI.items(params).then((response) => response.data?.total ?? 0));
    return asked.get(key);
  };
  const { filtered, listsDeleted } = leafScope(filters);
  const filteredGone = listsDeleted ? Promise.resolve(0) : total({ onlyDeleted: true });
  if (!filtered) return { filteredGone, allGone: filteredGone };
  return { filteredGone, allLive: total({ unfiltered: true }), allGone: total({ unfiltered: true, onlyDeleted: true }) };
}

export default function useProductPanel(filters, productKey) {
  const [state, setState] = useState(IDLE);
  const [attempt, setAttempt] = useState(0);
  // `generation`: the product and filter set; `listGeneration` also the escapes the list was asked with.
  const generation = useRef(0);
  const listGeneration = useRef(0);
  const latest = useRef({ filters, state });
  useEffect(() => {
    latest.current = { filters, state };
  }, [filters, state]);

  // What the panel is asked with: the selection, the page and the sort of the list do not start it over.
  const summaryKey = productKey ? JSON.stringify(buildSummaryParams(filters, productKey)) : '';

  /**
   * One page of the list from `offset`: the live publications of the scope, then (with "Ver eliminadas") its deleted
   * ones, from `offset - liveTotal`. A page that ends the live ones goes on with the deleted ones at once.
   */
  const fetchItems = useCallback((summary, escapes, offset, liveTotal) => {
    const mine = listGeneration.current;
    const gone = escapes.showDeleted && liveTotal !== null && offset >= liveTotal;
    const params = buildLeafParams(latest.current.filters, summary, gone ? offset - liveTotal : offset, {
      unfiltered: escapes.verTodos,
      onlyDeleted: gone,
    });
    setState((current) => ({ ...current, status: offset === 0 ? 'loading' : 'more', error: null }));
    publicacionesMlAPI
      .items(params)
      .then((response) => {
        if (mine !== listGeneration.current) return;
        const page = response.data?.items ?? [];
        const total = response.data?.total ?? 0;
        setState((current) => ({
          ...current,
          status: 'ready',
          items: offset === 0 ? page : appendPage(current.items, page),
          ...(gone ? { goneTotal: total } : { liveTotal: total }),
        }));
        if (!gone && escapes.showDeleted && offset + page.length >= total) fetchItems(summary, escapes, total, total);
      })
      .catch((error) => {
        if (mine !== listGeneration.current) return;
        setState((current) => ({ ...current, status: 'error', error }));
      });
  }, []);

  const fetchCounts = useCallback((summary) => {
    const mine = generation.current;
    for (const [name, request] of Object.entries(countRequests(latest.current.filters, summary))) {
      request
        .then((value) => {
          if (mine !== generation.current) return;
          setState((current) => ({ ...current, counts: { ...current.counts, [name]: value } }));
        })
        .catch(() => {}); // An unknown count offers nothing: the list itself is unaffected.
    }
  }, []);

  useEffect(() => {
    generation.current += 1;
    listGeneration.current += 1;
    const mine = generation.current;
    if (!summaryKey) {
      setState(IDLE);
      return;
    }
    setState({ ...IDLE, status: 'loading' });
    publicacionesMlAPI
      .products(JSON.parse(summaryKey))
      .then((response) => {
        if (mine !== generation.current) return;
        const row = response.data?.rows?.[0];
        if (!row) {
          setState({ ...IDLE, status: 'ready' });
          return;
        }
        const summary = readProduct(row);
        setState({ ...IDLE, summary, status: 'loading' });
        fetchItems(summary, NO_ESCAPES, 0, null);
        fetchCounts(summary);
      })
      .catch((error) => {
        if (mine !== generation.current) return;
        setState({ ...IDLE, status: 'error', error });
      });
  }, [summaryKey, attempt, fetchItems, fetchCounts]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  const { escapes, counts, liveTotal, goneTotal } = state;
  const total = (liveTotal ?? 0) + (escapes.showDeleted ? goneTotal : 0);
  const hasMore = state.summary !== null && state.items.length < total;
  const loadMore = useCallback(() => {
    const current = latest.current.state;
    const { summary, items, status } = current;
    const known = (current.liveTotal ?? 0) + (current.escapes.showDeleted ? current.goneTotal : 0);
    if (!summary || status !== 'ready' || items.length >= known) return;
    // Marked at once: a second call before the next render must not ask for the same page again.
    latest.current = { ...latest.current, state: { ...current, status: 'more' } };
    fetchItems(summary, current.escapes, items.length, current.liveTotal);
  }, [fetchItems]);

  /** Asks the list again from the start under other escapes; what the previous list asked never lands. */
  const restart = useCallback(
    (change) => {
      const current = latest.current.state;
      if (!current.summary) return;
      listGeneration.current += 1;
      const next = { ...current, ...change(current), items: [] };
      latest.current = { ...latest.current, state: next };
      setState(next);
      fetchItems(current.summary, next.escapes, 0, null);
    },
    [fetchItems],
  );
  const showAll = useCallback(
    () =>
      restart(({ escapes: now, counts: known }) => ({
        escapes: { ...now, verTodos: true },
        liveTotal: known.allLive,
        goneTotal: known.allGone ?? 0,
      })),
    [restart],
  );
  const toggleDeleted = useCallback(
    () =>
      restart(({ escapes: now, counts: known }) => ({
        escapes: { ...now, showDeleted: !now.showDeleted },
        goneTotal: (now.verTodos ? known.allGone : known.filteredGone) ?? 0,
      })),
    [restart],
  );

  const deletedCount = (escapes.verTodos ? counts.allGone : counts.filteredGone) ?? 0;
  const { filtered } = leafScope(filters);
  const withGone = (live, gone) => (escapes.showDeleted ? (gone === null ? null : live + gone) : live);
  const all = counts.allLive === null ? null : withGone(counts.allLive, counts.allGone);
  const shown = liveTotal === null ? null : withGone(liveTotal, goneTotal);
  const hiddenCount = filtered && !escapes.verTodos && all !== null && shown !== null ? Math.max(0, all - shown) : 0;
  const ready = state.status === 'ready';

  return {
    summary: state.summary,
    items: state.items,
    loading: state.status === 'loading' || state.status === 'more',
    error: state.error,
    reload,
    loadMore,
    hasMore,
    verTodos: escapes.verTodos,
    showDeleted: escapes.showDeleted,
    hiddenCount,
    deletedCount,
    onlyDeleted: ready && !escapes.showDeleted && liveTotal === 0 && deletedCount > 0,
    showAll,
    toggleDeleted,
  };
}
