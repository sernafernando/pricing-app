import { useCallback, useEffect, useMemo, useState } from 'react';
import { productosAPI } from '../../services/api';
import { useLazyResource } from '../../hooks/useLazyResource';
import TreeNode from './TreeNode';
import { isFilterActive, countHiddenDescendants } from './treeNodeUtils';
import styles from './promociones.module.css';

const L1_COL_SPAN = 5;

/**
 * Builds the tree-endpoint filter params from the active promo filter props.
 * Mirrors `useProductosFilters.construirFiltrosParams` promo mapping (D2/D4):
 * types present -> promo_tipos + promo_estado; types absent -> legacy
 * type-agnostic boolean fallback ('disponible' = true no-op, no params).
 */
function buildPromoFilterParams(promoTipos, promoEstado) {
  const tipos = promoTipos || [];
  const estado = promoEstado || 'disponible';
  if (tipos.length > 0) {
    return { promo_tipos: tipos.join(','), promo_estado: estado };
  }
  if (estado === 'aplicada') return { con_promo_aplicada: true };
  if (estado === 'sin_aplicar') return { con_promo_sin_aplicar: true };
  return {};
}

/**
 * Level 1 panel: recursive catalog/family publication tree of a product
 * (productos-catalog-family-tree PR3). Lazily fetches
 * `GET /productos/{item_id}/mercadolibre/tree` on first mount (i.e. on first
 * expand — the parent conditionally mounts this component), then renders the
 * root's children recursively via `<TreeNode>`, generalizing the previous
 * flat MLA list to genuine variable-depth family/catalog/vinculada nesting.
 *
 * `promoTipos`/`promoEstado` (optional) forward the active list-level promo
 * filter (productos-promo-filter-per-mla) so the tree endpoint can compute a
 * per-node `matches_filter` at any depth. When active, MLA-bearing nodes with
 * `matches_filter === false` are hidden by default with a "ver todos (N)"
 * escape hatch counting ALL hidden descendants across the whole tree;
 * `matches_filter` absent/true always shows (fail-open).
 */
function ProductoMLAsPanel({ itemId, mlasCacheRef, promosCacheRef, promoTipos, promoEstado }) {
  const filterParams = useMemo(() => buildPromoFilterParams(promoTipos, promoEstado), [promoTipos, promoEstado]);
  const filterActive = isFilterActive(promoTipos, promoEstado);
  const filterKey = useMemo(() => JSON.stringify(filterParams), [filterParams]);
  const cacheKey = `${itemId}::${filterKey}`;
  const [verTodos, setVerTodos] = useState(false);

  // Reset the "ver todos" reveal whenever the active filter changes, so a
  // filter change on an already-expanded (still-mounted) panel re-applies the
  // new hide set. Without this, verTodos stays true and the new filter is
  // silently defeated — all nodes shown, with no button to re-hide them.
  useEffect(() => {
    setVerTodos(false);
  }, [filterKey]);

  const fetcher = useCallback(
    () => productosAPI.getProductoTree(itemId, filterParams).then((r) => r.data),
    [itemId, filterParams],
  );
  const { data, loading, error, reload } = useLazyResource(mlasCacheRef, cacheKey, fetcher);

  if (loading) {
    return <div className={styles.panelState}>Cargando publicaciones...</div>;
  }

  if (error) {
    return (
      <div className={styles.panelStateError}>
        Error al cargar publicaciones.{' '}
        <button type="button" className={styles.retryLink} onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  }

  const rootChildren = data?.tree?.children || [];

  if (rootChildren.length === 0) {
    return <div className={styles.panelState}>Sin publicaciones en MercadoLibre.</div>;
  }

  const hiddenCount = filterActive
    ? rootChildren.reduce((sum, child) => sum + countHiddenDescendants(child), 0)
    : 0;

  return (
    <>
      {filterActive && hiddenCount > 0 && !verTodos && (
        <div className={styles.filterMessage}>
          <button type="button" className={styles.retryLink} onClick={() => setVerTodos(true)}>
            ver todos ({hiddenCount})
          </button>
        </div>
      )}
      <table className={styles.innerTable}>
        <tbody>
          {rootChildren.map((child) => (
            <TreeNode
              key={child.mla || `${child.kind}-${child.family_id || child.catalog_product_id || child.level}`}
              node={child}
              colSpan={L1_COL_SPAN}
              mlasCacheRef={mlasCacheRef}
              promosCacheRef={promosCacheRef}
              promoTipos={promoTipos}
              promoEstado={promoEstado}
              revealAll={verTodos}
            />
          ))}
        </tbody>
      </table>
    </>
  );
}

export default ProductoMLAsPanel;
