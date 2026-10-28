import { useEffect, useMemo, useState } from 'react';
import { productosAPI } from '../../services/api';

const NONE = new Map();
// Products per request: under the listing's cap of 500 ids, so a "Todos" page is read in parts,
export const PRICES_CHUNK = 200;
// at most this many at a time, so a huge page never takes the server's connections all at once.
export const PRICES_IN_FLIGHT = 3;

// Each part's products, asked PRICES_IN_FLIGHT at a time in the parts' order; it stops asking when one fails or
// `stopped()` (the page moved on), and rejects with the first failure.
async function readParts(parts, stopped) {
  const answers = new Array(parts.length);
  let next = 0;
  let failed = false;
  const worker = async () => {
    while (next < parts.length && !failed && !stopped()) {
      const at = next;
      next += 1;
      try {
        const response = await productosAPI.listar({ item_ids: parts[at].join(','), page: 1, page_size: parts[at].length });
        answers[at] = response.data?.productos ?? [];
      } catch (error) {
        failed = true;
        throw error;
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(PRICES_IN_FLIGHT, parts.length) }, worker));
  return answers.flat();
}

/**
 * Productos' prices of the products on show (S11): one `GET /productos?item_ids=` for the distinct product ids of
 * the page, so the prices and markups are the very ones Productos lists (its cuota and PVP markups are computed per
 * product by that listing, not stored). `productIds` may repeat and hold nulls (publications with no product).
 * A page with more than PRICES_CHUNK products is asked in parts (PRICES_IN_FLIGHT at a time); any part failing
 * fails the whole answer.
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
    readParts(parts, () => !current)
      .then((products) => {
        if (!current) return;
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
