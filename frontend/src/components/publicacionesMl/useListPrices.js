import { useEffect, useMemo, useState } from 'react';
import { productosAPI } from '../../services/api';

const NONE = new Map();

/**
 * Productos' prices of the products on show (S11): one `GET /productos?item_ids=` for the distinct product ids of
 * the page, so the prices and markups are the very ones Productos lists (its cuota and PVP markups are computed per
 * product by that listing, not stored). `productIds` may repeat and hold nulls (publications with no product).
 *
 * @returns {{ byId: Map<number, object>, loading: boolean, error: boolean }}
 */
export default function useListPrices(productIds, enabled) {
  const key = useMemo(
    () => (enabled ? [...new Set(productIds.filter((id) => id !== null && id !== undefined))].sort((a, b) => a - b).join(',') : ''),
    [productIds, enabled],
  );
  const [state, setState] = useState({ key: '', byId: NONE, error: false });

  useEffect(() => {
    if (!key) return undefined;
    let current = true;
    productosAPI
      .listar({ item_ids: key, page: 1, page_size: key.split(',').length })
      .then((response) => {
        if (!current) return;
        const byId = new Map((response.data?.productos ?? []).map((product) => [product.item_id, product]));
        setState({ key, byId, error: false });
      })
      .catch(() => {
        if (current) setState({ key, byId: NONE, error: true });
      });
    return () => {
      current = false;
    };
  }, [key]);

  const answered = Boolean(key) && state.key === key;
  return { byId: answered ? state.byId : NONE, loading: Boolean(key) && !answered, error: answered && state.error };
}
