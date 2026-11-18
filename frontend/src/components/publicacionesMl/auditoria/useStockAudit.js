import { useEffect, useRef, useState } from 'react';
import { publicacionesMlAPI } from '../../../services/api';
import { buildStockAuditParams } from '../../../hooks/usePublicacionesMLFilters';
import { buildLeafParams } from '../groupNodes';
import { appendPage } from '../../../utils/appendPage';
import { flattenAudit, needsBranch } from './stockAuditRows';

// A category's products, asked like its publications are: 100 at a time with "Ver más".
const BRANCH_PAGE = 100;

/** The `/view/stock-audit` query of a group's products: the list's own (filters, sort), at the product level, inside
 * the group (its `grupo`, over the list's drill). */
function groupProductsParams(listParams, grupo, offset) {
  const { limit, offset: listOffset, ...params } = listParams;
  void limit, listOffset;
  const drill = {};
  if (grupo?.marca) drill.grupo_marca = grupo.marca;
  if (grupo?.categoria) drill.grupo_categoria = grupo.categoria;
  return { ...params, ...drill, nivel: 'producto', limit: BRANCH_PAGE, offset };
}

/**
 * State of the Auditoría de stock view: one page of `GET /view/stock-audit` (rows, KPIs, the BNA rate) for the
 * filters, level, drill, sort and page, and what every row the user opened brings: a category its products (the
 * audit at `nivel=producto` inside it), a product or a variant its publications (`/view/items` with the node's
 * `params`, 100 at a time with "Ver más", as the Producto view opens a product). The opened rows are the caller's
 * (`expanded`, the URL's `abiertos`): a reload opens them again and asks what they hold. An answer to a request of
 * an older list is dropped.
 */
export default function useStockAudit({
  filters,
  pageSize,
  canSeeSales = false,
  canSeeMargin = false,
  enabled = true,
  expanded: expandedKeys = [],
  onExpandedChange,
}) {
  const params = enabled ? buildStockAuditParams(filters, pageSize, { canSeeSales, canSeeMargin }) : null;
  const listKey = params ? JSON.stringify(params) : '';
  const [state, setState] = useState({ data: null, loading: enabled, error: null });
  const [branches, setBranches] = useState({});
  const [reloadToken, setReloadToken] = useState(0);
  const generation = useRef(0);
  // The branches asked in this generation, so an effect run twice asks each once.
  const requested = useRef(new Set());
  const latest = useRef({ filters, listKey, canSeeSales });
  useEffect(() => {
    latest.current = { filters, listKey, canSeeSales };
  }, [filters, listKey, canSeeSales]);
  const expanded = new Set(expandedKeys);

  useEffect(() => {
    generation.current += 1;
    const mine = generation.current;
    requested.current = new Set();
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

  const fetchBranch = (key, row, offset) => {
    const mine = generation.current;
    requested.current.add(key);
    setBranches((all) => ({
      ...all,
      [key]: { items: [], total: 0, ...all[key], row, status: offset === 0 ? 'loading' : 'more', error: null },
    }));
    const { filters: current, listKey: currentList, canSeeSales: sales } = latest.current;
    const request =
      row.type === 'group'
        ? publicacionesMlAPI
            .stockAudit(groupProductsParams(JSON.parse(currentList || '{}'), row.node.grupo, offset))
            .then((response) => ({ items: response.data?.rows ?? [], total: response.data?.total ?? 0 }))
        : publicacionesMlAPI
            // The publications' ERP / Full split of their sales (auditoria-stock-niveles S3), with the sales.
            .items({ ...buildLeafParams(current, { params: row.node.params }, offset), ...(sales ? { desglose_envio: true } : {}) })
            .then((response) => ({ items: response.data?.items ?? [], total: response.data?.total ?? 0 }));
    request
      .then(({ items, total }) => {
        if (mine !== generation.current) return;
        setBranches((all) => ({
          ...all,
          [key]: { ...all[key], status: 'ready', items: offset === 0 ? items : appendPage(all[key].items, items), total },
        }));
      })
      .catch((error) => {
        if (mine === generation.current) setBranches((all) => ({ ...all, [key]: { ...all[key], status: 'error', error } }));
      });
  };

  const data = state.data;
  const rows = flattenAudit(data?.rows ?? [], expanded, branches);

  // Every open row asks what it holds once: on opening it, and after a reload for the rows the URL keeps open (a
  // category's products first, then the products it holds that were open).
  useEffect(() => {
    for (const row of rows) {
      if (row.expanded && needsBranch(row) && !branches[row.pathKey] && !requested.current.has(row.pathKey)) {
        fetchBranch(row.pathKey, row, 0);
      }
    }
  });

  /** Opens or closes a group, a product or a variant row; a branch that failed with nothing is asked again. */
  const toggle = (row) => {
    const key = row.pathKey;
    const next = new Set(expanded);
    if (!next.delete(key)) {
      next.add(key);
      const loaded = branches[key];
      if (loaded && loaded.status === 'error' && loaded.items.length === 0) fetchBranch(key, row, 0);
    }
    onExpandedChange?.([...next]);
  };

  /** "Ver más" / "Reintentar": what the branch does not have yet. */
  const loadMore = (key) => {
    const branch = branches[key];
    if (branch) fetchBranch(key, branch.row, branch.items.length);
  };

  return {
    data,
    rows,
    loading: state.loading,
    error: state.error,
    total: data?.total ?? 0,
    toggle,
    loadMore,
    reload: () => setReloadToken((token) => token + 1),
  };
}
