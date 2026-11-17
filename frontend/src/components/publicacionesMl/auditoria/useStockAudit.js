import { useEffect, useRef, useState } from 'react';
import { publicacionesMlAPI } from '../../../services/api';
import { buildStockAuditParams } from '../../../hooks/usePublicacionesMLFilters';
import { buildLeafParams } from '../groupNodes';
import { appendPage } from '../../../utils/appendPage';
import { flattenAudit } from './stockAuditRows';

/**
 * State of the Auditoría de stock view: one page of `GET /view/stock-audit` (rows, KPIs, the BNA rate) for the
 * filters, sort and page, and the publications of every node the user opened (`/view/items` with the node's
 * `params`, 100 at a time with "Ver más", as the Producto view opens a product). A new list (filters, sort, page)
 * starts collapsed, and an answer to a request of an older list is dropped.
 */
export default function useStockAudit({ filters, pageSize, canSeeSales = false, canSeeMargin = false, enabled = true }) {
  const params = enabled ? buildStockAuditParams(filters, pageSize, { canSeeSales, canSeeMargin }) : null;
  const listKey = params ? JSON.stringify(params) : '';
  const [state, setState] = useState({ data: null, loading: enabled, error: null });
  const [expanded, setExpanded] = useState(() => new Set());
  const [branches, setBranches] = useState({});
  const [reloadToken, setReloadToken] = useState(0);
  const generation = useRef(0);
  const latestFilters = useRef(filters);
  useEffect(() => {
    latestFilters.current = filters;
  }, [filters]);

  useEffect(() => {
    generation.current += 1;
    const mine = generation.current;
    setExpanded(new Set());
    setBranches({});
    if (!listKey) return;
    setState((current) => ({ ...current, loading: true, error: null }));
    publicacionesMlAPI
      .stockAudit(JSON.parse(listKey))
      .then((response) => {
        if (mine === generation.current) setState({ data: response.data, loading: false, error: null });
      })
      .catch((error) => {
        if (mine === generation.current) setState({ data: null, loading: false, error });
      });
  }, [listKey, reloadToken]);

  const fetchBranch = (key, node, offset) => {
    const mine = generation.current;
    setBranches((all) => ({
      ...all,
      [key]: { items: [], total: 0, ...all[key], node, status: offset === 0 ? 'loading' : 'more', error: null },
    }));
    publicacionesMlAPI
      .items(buildLeafParams(latestFilters.current, { params: node.params }, offset))
      .then((response) => {
        if (mine !== generation.current) return;
        const items = response.data?.items ?? [];
        setBranches((all) => ({
          ...all,
          [key]: {
            ...all[key],
            status: 'ready',
            items: offset === 0 ? items : appendPage(all[key].items, items),
            total: response.data?.total ?? 0,
          },
        }));
      })
      .catch((error) => {
        if (mine === generation.current) setBranches((all) => ({ ...all, [key]: { ...all[key], status: 'error', error } }));
      });
  };

  /** Opens or closes a product or variant row; opening one asks its publications once. */
  const toggle = (row) => {
    const key = row.pathKey;
    const next = new Set(expanded);
    if (!next.delete(key)) {
      next.add(key);
      const loaded = branches[key];
      if (row.node.publications_count > 0 && (!loaded || (loaded.status === 'error' && loaded.items.length === 0))) {
        fetchBranch(key, row.node, 0);
      }
    }
    setExpanded(next);
  };

  /** "Ver más" / "Reintentar": what the branch does not have yet. */
  const loadMore = (key) => {
    const branch = branches[key];
    if (branch) fetchBranch(key, branch.node, branch.items.length);
  };

  const data = state.data;
  return {
    data,
    rows: flattenAudit(data?.rows ?? [], expanded, branches),
    loading: state.loading,
    error: state.error,
    total: data?.total ?? 0,
    toggle,
    loadMore,
    reload: () => setReloadToken((token) => token + 1),
  };
}
