import { useEffect, useMemo, useState } from 'react';
import { productosAPI } from '../../services/api';

const NONE = new Map();
// Products per request: under the listing's cap of 500 ids, so a "Todos" page is read in parts.
export const PRICES_CHUNK = 200;

/**
 * Productos' prices of the products on show (S11): one `GET /productos?item_ids=` for the distinct product ids of
 * the page, so the prices and markups are the very ones Productos lists (its cuota and PVP markups are computed per
 * product by that listing, not stored). `productIds` may repeat and hold nulls (publications with no product).
 * A page with more than PRICES_CHUNK products is asked in parts at once; any part failing fails the whole answer.
 *
 * A new `version` (the page's list reloaded after a write) reads the same products again; the shown prices stay
 * until the new ones arrive.
 *
 * @returns {{ byId: Map<number, object>, loading: boolean, error: boolean }}
 */
export default function useListPrices(productIds, enabled, version = 0) {
  const key = useMemo(
    () => (enabled ? [...new Set(productIds.filter((id) => id !== null && id !== undefined))].sort((a, b) => a - b).join(',') : ''),
    [productIds, enabled],
  );
  const [state, setState] = useState({ key: '', byId: NONE, error: false });

  useEffect(() => {
    if (!key) return undefined;
    let current = true;
    const ids = key.split(',');
    const parts = [];
    for (let at = 0; at < ids.length; at += PRICES_CHUNK) parts.push(ids.slice(at, at + PRICES_CHUNK));
    Promise.all(parts.map((part) => productosAPI.listar({ item_ids: part.join(','), page: 1, page_size: part.length })))
      .then((responses) => {
        if (!current) return;
        const products = responses.flatMap((response) => response.data?.productos ?? []);
        const byId = new Map(products.map((product) => [product.item_id, product]));
        setState({ key, byId, error: false });
      })
      .catch(() => {
        if (current) setState({ key, byId: NONE, error: true });
      });
    return () => {
      current = false;
    };
  }, [key, version]);

  const answered = Boolean(key) && state.key === key;
  // The same object while nothing changed: the page's columns depend on it.
  return useMemo(
    () => ({ byId: answered ? state.byId : NONE, loading: Boolean(key) && !answered, error: answered && state.error }),
    [answered, key, state],
  );
}
