import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { publicacionesMlAPI } from '../../services/api';
import {
  ALL_ROWS,
  LAZY_CHUNK,
  buildProductsParams,
  effectiveProductSortKeys,
  headerSort,
} from '../../hooks/usePublicacionesMLFilters';
import { buildLeafParams } from './groupNodes';
import { flattenTree } from './groupTree';

/**
 * State of the Producto view of Publicaciones ML: one page of product rows from
 * `GET /ml-publications/view/products` (one row per LINKED product over the
 * selected publications, its figures the sum of theirs, sorted and paged by the
 * backend), each opening into exactly its `publications_count` publications
 * from `/view/items` with the row's `params` -- the same leaf read as the
 * Agrupado tree's products, 100 at a time with "Ver más".
 *
 * The rows are the tree's (`groupTree.flattenTree`): the products are the
 * roots, each a leaf node. What a product loaded is kept while the list stays
 * the same, so closing and opening it again asks for nothing; a new list
 * (filters, sort, page, permission) starts over, collapsed, and an answer to a
 * request of the previous list is dropped.
 *
 * "Todos" (`ALL_ROWS`) is not one request: the products come LAZY_CHUNK at a time, the first part with the list and
 * each next one on `loadMoreProducts` (the table's end in view), with the same params, appended, until the page's
 * products (`total`) are in. The pager's figures are the first part's.
 */
const ROOT = '';
// `sinMlaCount`: Productos' Sin MLA card; null when unknown (a publication filter is on, or nothing loaded yet).
const NO_SUMMARY = { total: 0, mlaCount: 0, sinMlaCount: null };

/**
 * A row of `/view/products` as a leaf node of the tree. `metrics` is absent without `ml_metricas.ver`, `costo` without
 * `ml_metricas.ver_ganancia`.
 */
export function readProduct(raw) {
  return {
    kind: 'producto',
    key: raw.key,
    label: raw.descripcion || 'Sin producto',
    count: raw.publications_count ?? 0,
    leaf: true,
    params: raw.params ?? {},
    withoutProduct: raw.product_item_id == null,
    productoItemId: raw.product_item_id ?? null,
    codigo: raw.codigo ?? null,
    marca: raw.marca ?? null,
    stock: raw.stock ?? null,
    costo: raw.costo ?? null, // the product's cost, only with ml_metricas.ver_ganancia
    ppp: raw.ppp, // the lines under the cost, same gate; undefined (absent) without it
    sellInOut: raw.sell_in_out,
    metrics: raw.metrics ?? null,
    colorMarcado: raw.color_marcado ?? null,
    colorHintGlobal: raw.color_hint_global ?? null,
    // Productos' wholesale quick view (`PxqTramosBadge`); absent when the product has no tiers.
    pxqTramos: raw.pxq_tramos ?? null,
    pxqPrecioDesde: raw.pxq_precio_desde ?? null,
  };
}

/** Pages are by offset: a row that moved between two requests stays once (publications by `item_id`). */
export function appendPage(rows, page, keyOf = (row) => row.item_id) {
  const seen = new Set(rows.map(keyOf));
  return [...rows, ...page.filter((row) => !seen.has(keyOf(row)))];
}

/**
 * The products' request for the part at `offset` of the page: the page itself, or with "Todos" its LAZY_CHUNK rows
 * from there (never past `end`, the page's products once the first part said how many).
 */
function productsPartParams(params, lazy, offset, end) {
  if (!lazy) return params;
  return { ...params, offset: params.offset + offset, limit: Math.min(LAZY_CHUNK, (end ?? LAZY_CHUNK) - offset) };
}

export default function useProductRows({ filters, pageSize, canSeeSales = false, canSeeMargin = false, enabled = true }) {
  const [branches, setBranches] = useState({});
  const [expanded, setExpanded] = useState(() => new Set());
  // The pager's figures belong to ONE list: a new list starts without them, and keeps none if it fails.
  const [summary, setSummary] = useState(NO_SUMMARY);
  const generation = useRef(0);
  const inflight = useRef(new Set());
  // With "Todos", the page's products as the list's first part said (null until then): where its parts stop.
  const latestEnd = useRef(null);
  const permissions = useMemo(() => ({ canSeeSales, canSeeMargin }), [canSeeSales, canSeeMargin]);
  const latest = useRef({ filters, pageSize, permissions });
  // Declared before the effect that loads the products, so that effect reads this render's values.
  useEffect(() => {
    latest.current = { filters, pageSize, permissions };
  }, [filters, pageSize, permissions]);

  const sort = headerSort(effectiveProductSortKeys(filters, permissions));
  // What the products are asked with: the selection does not restart the list.
  const listKey = enabled ? JSON.stringify(buildProductsParams(filters, pageSize, permissions)) : '';

  const fetchPage = useCallback((key, node, offset) => {
    const { filters: current, pageSize: size, permissions: allowed } = latest.current;
    const mine = generation.current;
    const page = `${key}@${offset}`;
    // This generation's guard: a late answer of an older list settles in its own Set, never in the current one.
    const pending = inflight.current;
    if (pending.has(page)) return;
    pending.add(page);
    const leaf = key !== ROOT;
    setBranches((all) => ({
      ...all,
      [key]: { rows: [], total: 0, ...all[key], path: leaf ? [key] : [], leaf, node, status: offset === 0 ? 'loading' : 'more', error: null },
    }));
    const lazy = !leaf && size === ALL_ROWS;
    const productsParams = leaf ? null : buildProductsParams(current, size, allowed);
    const asked = leaf ? null : productsPartParams(productsParams, lazy, offset, latestEnd.current);
    const request = leaf ? publicacionesMlAPI.items(buildLeafParams(current, node, offset)) : publicacionesMlAPI.products(asked);
    request
      .then((response) => {
        pending.delete(page);
        if (mine !== generation.current) return;
        if (!leaf) {
          const rows = (response.data?.rows ?? []).map(readProduct);
          // The page is the whole branch: the pager, not "Ver más", moves through the products. With "Todos" a
          // part is appended, and `next` / `end` say what `loadMoreProducts` asks next and where the page ends.
          if (offset === 0 && lazy) {
            latestEnd.current = Math.max(0, (response.data?.total ?? 0) - productsParams.offset);
          }
          setBranches((all) => {
            const merged = offset === 0 ? rows : appendPage(all[key].rows, rows, (row) => row.key);
            const more = lazy ? { next: offset + asked.limit, end: latestEnd.current } : {};
            return { ...all, [key]: { ...all[key], status: 'ready', rows: merged, total: merged.length, ...more } };
          });
          if (offset === 0) {
            setSummary({
              total: response.data?.total ?? 0,
              mlaCount: response.data?.mla_count ?? 0,
              sinMlaCount: response.data?.sin_mla_count ?? null,
            });
          }
          return;
        }
        const items = response.data?.items ?? [];
        setBranches((all) => ({
          ...all,
          [key]: {
            ...all[key],
            status: 'ready',
            rows: offset === 0 ? items : appendPage(all[key].rows, items),
            total: response.data?.total ?? 0,
          },
        }));
      })
      .catch((error) => {
        pending.delete(page);
        if (mine !== generation.current) return;
        setBranches((all) => ({ ...all, [key]: { ...all[key], status: 'error', error } }));
      });
  }, []);

  useEffect(() => {
    generation.current += 1;
    inflight.current = new Set();
    latestEnd.current = null;
    setExpanded(new Set());
    setBranches({});
    setSummary(NO_SUMMARY);
    if (listKey) fetchPage(ROOT, null, 0);
  }, [listKey, fetchPage]);

  const toggle = useCallback(
    (row) => {
      if (expanded.has(row.pathKey)) {
        setExpanded((current) => {
          const next = new Set(current);
          next.delete(row.pathKey);
          return next;
        });
        return;
      }
      setExpanded((current) => new Set(current).add(row.pathKey));
      const loaded = branches[row.pathKey];
      if (!loaded || (loaded.status === 'error' && loaded.rows.length === 0)) fetchPage(row.pathKey, row.node, 0);
    },
    [expanded, branches, fetchPage],
  );

  // "Ver más" and "Reintentar" ask for what the branch does not have yet (the products: their page again, or with
  // "Todos" the part that failed once the first one is in).
  const loadMore = useCallback(
    (pathKey) => {
      const branch = branches[pathKey];
      if (branch) fetchPage(pathKey, branch.node, pathKey === ROOT ? (branch.next ?? 0) : branch.rows.length);
    },
    [branches, fetchPage],
  );

  // "Todos": the next part of the products, when the list has one left and none in flight; otherwise nothing.
  const loadMoreProducts = useCallback(() => {
    const root = branches[ROOT];
    if (root?.status === 'ready' && root.next != null && root.next < root.end) fetchPage(ROOT, null, root.next);
  }, [branches, fetchPage]);

  const rows = useMemo(() => flattenTree({ branches, expanded }), [branches, expanded]);
  const root = branches[ROOT];
  return {
    rows,
    toggle,
    loadMore,
    loadMoreProducts,
    sort,
    total: summary.total,
    mlaCount: summary.mlaCount,
    sinMlaCount: summary.sinMlaCount,
    loading: !root || root.status === 'loading',
  };
}
