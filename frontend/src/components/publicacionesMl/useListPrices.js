import { useEffect, useMemo, useRef, useState } from 'react';
import { productosAPI } from '../../services/api';

const NONE = new Map();
// Products per request: under the listing's cap of 500 ids, so a "Todos" page is read in parts,
export const PRICES_CHUNK = 200;
// at most this many at a time, so a huge page never takes the server's connections all at once.
export const PRICES_IN_FLIGHT = 3;

// Each part's products, asked PRICES_IN_FLIGHT at a time in the parts' order; it stops asking when one fails or
// `signal` aborts (the page moved on: the parts in flight are cancelled too), and rejects with the first failure.
async function readParts(parts, signal) {
  const answers = new Array(parts.length);
  let next = 0;
  let failed = false;
  const worker = async () => {
    while (next < parts.length && !failed && !signal.aborted) {
      const at = next;
      next += 1;
      try {
        const params = { item_ids: parts[at].join(','), page: 1, page_size: parts[at].length };
        const response = await productosAPI.listar(params, { signal });
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
 * until the new ones arrive. A list that only grew
 * ("Todos" appends its rows in parts) asks only its new products, and the prices on show stay meanwhile.
 *
 * @returns {{ byId: Map<number, object>, loading: boolean, error: boolean }}
 */
export default function useListPrices(productIds, enabled, version = 0) {
  const key = useMemo(
    () => (enabled ? [...new Set(productIds.filter((id) => id !== null && id !== undefined))].sort((a, b) => a - b).join(',') : ''),
    [productIds, enabled],
  );
  const [state, setState] = useState({ key: '', version, byId: NONE, error: false });
  // The last answer, read by the effect without re-running it.
  const last = useRef(state);
  last.current = state;

  useEffect(() => {
    if (!key) return undefined;
    let current = true;
    const controller = new AbortController();
    const ids = key.split(',');
    // A list that only grew ("Todos" appended a part) asks just its new products and keeps the answer it has.
    const kept = grownFrom(last.current, key, version) ? last.current.byId : null;
    const missing = kept ? ids.filter((id) => !kept.has(Number(id))) : ids;
    const parts = [];
    for (let at = 0; at < missing.length; at += PRICES_CHUNK) parts.push(missing.slice(at, at + PRICES_CHUNK));
    readParts(parts, controller.signal)
      .then((products) => {
        if (!current) return;
        const byId = new Map([...(kept ?? []), ...products.map((product) => [product.item_id, product])]);
        setState({ key, version, byId, error: false });
      })
      .catch(() => {
        // A grown list keeps the prices it had (they are this version's); a list of other products shows none.
        if (current) setState({ key, version, byId: kept ?? NONE, error: true });
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [key, version]);

  // Of the same products, even of an older `version`: a reload keeps the shown prices until the new ones arrive.
  const answered = Boolean(key) && state.key === key;
  // While a grown list's new products are asked, the prices already on show stay.
  const shown = answered || grownFrom(state, key, version) ? state.byId : NONE;
  // The same object while nothing changed: the page's columns depend on it.
  return useMemo(
    () => ({ byId: shown, loading: Boolean(key) && !answered, error: answered && state.error }),
    [answered, key, shown, state.error],
  );
}

/** Whether `answer` (a good answer of this `version`) is about a part of the products of `key`: the list grew. */
function grownFrom(answer, key, version) {
  if (!answer.key || answer.error || answer.version !== version || answer.key === key) return false;
  const now = new Set(key.split(','));
  return answer.key.split(',').every((id) => now.has(id));
}
