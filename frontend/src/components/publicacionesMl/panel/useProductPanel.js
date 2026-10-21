import { useCallback, useEffect, useRef, useState } from 'react';
import { publicacionesMlAPI } from '../../../services/api';
import { buildProductsParams } from '../../../hooks/usePublicacionesMLFilters';
import { buildLeafParams } from '../groupNodes';
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
 * A new product or a new filter set starts over, and an answer to a request of the previous one is dropped.
 */
export const NO_PRODUCT_KEY = '0';

const IDLE = { summary: null, items: [], total: 0, status: 'idle', error: null };

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

export default function useProductPanel(filters, productKey) {
  const [state, setState] = useState(IDLE);
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  const latest = useRef({ filters, state });
  useEffect(() => {
    latest.current = { filters, state };
  }, [filters, state]);

  // What the panel is asked with: the selection, the page and the sort of the list do not start it over.
  const summaryKey = productKey ? JSON.stringify(buildSummaryParams(filters, productKey)) : '';

  const fetchItems = useCallback((summary, offset) => {
    const mine = generation.current;
    setState((current) => ({ ...current, status: offset === 0 ? 'loading' : 'more', error: null }));
    publicacionesMlAPI
      .items(buildLeafParams(latest.current.filters, summary, offset))
      .then((response) => {
        if (mine !== generation.current) return;
        const page = response.data?.items ?? [];
        setState((current) => ({
          ...current,
          status: 'ready',
          items: offset === 0 ? page : appendPage(current.items, page),
          total: response.data?.total ?? 0,
        }));
      })
      .catch((error) => {
        if (mine !== generation.current) return;
        setState((current) => ({ ...current, status: 'error', error }));
      });
  }, []);

  useEffect(() => {
    generation.current += 1;
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
        fetchItems(summary, 0);
      })
      .catch((error) => {
        if (mine !== generation.current) return;
        setState({ ...IDLE, status: 'error', error });
      });
  }, [summaryKey, attempt, fetchItems]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  const hasMore = state.summary !== null && state.items.length < state.total;
  const loadMore = useCallback(() => {
    const { summary, items, total, status } = latest.current.state;
    if (!summary || status !== 'ready' || items.length >= total) return;
    // Marked at once: a second call before the next render must not ask for the same page again.
    latest.current = { ...latest.current, state: { ...latest.current.state, status: 'more' } };
    fetchItems(summary, items.length);
  }, [fetchItems]);

  return {
    summary: state.summary,
    items: state.items,
    loading: state.status === 'loading' || state.status === 'more',
    error: state.error,
    reload,
    loadMore,
    hasMore,
  };
}
