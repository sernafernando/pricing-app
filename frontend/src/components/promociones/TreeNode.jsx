import { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import ExpandableRow from './ExpandableRow';
import MlaPromocionesPanel from './MlaPromocionesPanel';
import { isMlaBearing, isFilterActive, isNodeHidden, nodeHasVisibleContent, describeChildKinds } from './treeNodeUtils';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { getMarkupColor } from '../../hooks/useProductosOffsets';
import styles from './promociones.module.css';

// Backend-computed price formatting for the applied promo's price — kept
// local/minimal (no currency-conversion concerns here, unlike
// MlaPromocionesPanel's fuller money formatting) since this only surfaces a
// compact collapsed-node hint.
function formatAppliedPrice(value) {
  if (value === null || value === undefined) return null;
  return `$${Number(value).toFixed(2)}`;
}

const KIND_LABELS = {
  producto: 'Producto',
  familia: 'Familia',
  catalogo: 'Catálogo',
  vinculada: 'Vinculada',
  publicacion: 'Publicación',
};

const KIND_BADGE_CLASS = {
  producto: styles.badgeKindProducto,
  familia: styles.badgeKindFamilia,
  catalogo: styles.badgeKindCatalogo,
  vinculada: styles.badgeKindVinculada,
  publicacion: styles.badgeKindPublicacion,
};

// Subtle per-kind row tint (design's requested "group band" read) — one level
// down in weight from the badge hues above, so the row reads as a group
// without competing with the badge itself.
const KIND_ROW_CLASS = {
  familia: styles.rowTintFamilia,
  catalogo: styles.rowTintCatalogo,
  vinculada: styles.rowTintVinculada,
};

/**
 * Recursive tree node — generalizes `ExpandableRow` for the productos catalog
 * /family publication tree (any variable depth, per `kind`:
 * "producto"|"familia"|"catalogo"|"vinculada"|"publicacion").
 *
 * MLA-bearing nodes render their own promos in a SEPARATE sub-spoiler
 * (design's locked decision C) — visually distinct from `children`
 * (vinculada nodes), so a promo row is never confused with a vinculada
 * publication row.
 *
 * `promoTipos`/`promoEstado`/`mlasCacheRef`/`promosCacheRef` MUST be
 * forwarded unchanged through every recursive call so the shipped promo
 * filter and per-MLA dynamic-refresh reload timers keep working at any
 * depth — dropping them here silently breaks those features deeper in the
 * tree (this is the design's flagged #1 FE risk).
 */
function TreeNode({ node, colSpan, mlasCacheRef, promosCacheRef, promoTipos, promoEstado, revealAll = false }) {
  const [isOpen, setIsOpen] = useState(false);
  const [promosOpen, setPromosOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(false);
  const [promosReloadKey, setPromosReloadKey] = useState(0);
  const { tienePermiso } = usePermisos();

  // Guards the async refresh follow-up from setState-ing after the node
  // unmounts (e.g. the tree re-renders on a promo-filter change while a
  // refresh is still in flight).
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const filterActive = isFilterActive(promoTipos, promoEstado);

  if (!nodeHasVisibleContent(node, filterActive, revealAll)) {
    return null;
  }

  if (isMlaBearing(node.kind) && isNodeHidden(node, filterActive, revealAll)) {
    return null;
  }

  const kindLabel = KIND_LABELS[node.kind] || node.kind;
  const badgeClass = KIND_BADGE_CLASS[node.kind] || styles.badgeReadonly;
  const displayLabel = node.label || node.mla || kindLabel;
  const rowKey = node.mla || `${node.kind}-${node.family_id || node.catalog_product_id || node.level}`;
  const children = node.children || [];
  const bearsMla = isMlaBearing(node.kind);
  // The refresh endpoint requires `promos.escribir` (same as enroll/remove);
  // gate the button's visibility so a view-only user never sees a control
  // that would 403 — mirrors PromoApplyControl's gating.
  const canRefresh = bearsMla && tienePermiso('promos.escribir');

  // Collapsed-node promo summary (catalog-tree-node-summary PR) — restores
  // the old flat panel's per-MLA badges, visible without expanding the
  // node. Fail-open: absent `promo_summary` renders nothing extra.
  const promoSummary = bearsMla ? node.promo_summary : null;
  const appliedPriceLabel = promoSummary ? formatAppliedPrice(promoSummary.applied_price) : null;
  // `applied_markup` is deferred server-side (see TreeNodePromoSummary's
  // docstring) — rendered defensively in case a future backend adds it,
  // reusing the same markup-color treatment as MlaPromocionesPanel.
  const appliedMarkup = promoSummary?.applied_markup;

  // Grouping nodes (familia/catalogo with children) get a purely FE-computed
  // "N catálogos · M vinculadas" hint — no backend involvement.
  const childKindSummary = !bearsMla ? describeChildKinds(children) : '';

  // Promos-only manual refresh (locked decision): reconciles the MLA's
  // promo mirror via the existing ml-webhook proxy WITHOUT expanding the
  // promos sub-spoiler. Never asserts the final promo state itself — on
  // success it just invalidates the cache entry and, if the sub-spoiler is
  // open, bumps a reload key to force `MlaPromocionesPanel` to remount and
  // re-fetch; the panel remains the source of truth (eventual-consistency
  // safe, money-path rule — this only triggers a read-reconcile, never a
  // price/promo write).
  const handleRefreshPromos = async (event) => {
    event.stopPropagation();
    if (refreshing) return;
    setRefreshing(true);
    setRefreshError(false);
    try {
      const { data } = await promocionesAPI.refreshItemPromociones(node.mla);
      if (data?.ok) {
        // Cache invalidation is safe even if we unmounted — it makes the
        // NEXT expand fetch fresh data. State updates below are guarded.
        promosCacheRef.current.delete(node.mla);
        if (mountedRef.current && promosOpen) {
          setPromosReloadKey((prev) => prev + 1);
        }
      } else if (mountedRef.current) {
        setRefreshError(true);
      }
    } catch {
      if (mountedRef.current) setRefreshError(true);
    } finally {
      if (mountedRef.current) setRefreshing(false);
    }
  };

  return (
    <ExpandableRow
      colSpan={colSpan}
      isOpen={isOpen}
      onToggle={() => setIsOpen((prev) => !prev)}
      ariaLabel={isOpen ? `Colapsar ${displayLabel}` : `Expandir ${displayLabel}`}
      headerRowClassName={KIND_ROW_CLASS[node.kind]}
      header={
        <>
          <td className={styles.treeNodeLabelCell}>
            <span className={`${styles.badge} ${badgeClass}`}>{kindLabel}</span>
            <span className={styles.treeNodeLabel}>{displayLabel}</span>
            {promoSummary && (
              <span className={styles.treeNodeSummary}>
                {promoSummary.applied_name && (
                  <span className={`${styles.badge} ${styles.appliedIndicator}`}>
                    Aplicada: {promoSummary.applied_name}
                  </span>
                )}
                <span className={styles.treeNodeSummaryCounts}>
                  {promoSummary.started_count} aplicada{promoSummary.started_count === 1 ? '' : 's'} ·{' '}
                  {promoSummary.candidate_count} disponible{promoSummary.candidate_count === 1 ? '' : 's'}
                </span>
                {appliedPriceLabel && <span className={styles.treeNodeSummaryCounts}>{appliedPriceLabel}</span>}
                {appliedMarkup !== undefined && appliedMarkup !== null && (
                  <span style={{ color: getMarkupColor(appliedMarkup) }}>Markup: {appliedMarkup}</span>
                )}
              </span>
            )}
            {childKindSummary && <span className={styles.treeNodeChildKindCount}>{childKindSummary}</span>}
            {canRefresh && (
              <>
                <button
                  type="button"
                  className="btn-tesla outline-subtle-primary icon-only sm"
                  onClick={handleRefreshPromos}
                  disabled={refreshing}
                  aria-label={`Refrescar promociones de ${displayLabel}`}
                >
                  <RefreshCw size={14} />
                </button>
                {refreshing && <span className={styles.provisionalPending}>Refrescando…</span>}
                {refreshError && <span className={styles.feedbackError}>No se pudo refrescar</span>}
              </>
            )}
          </td>
        </>
      }
    >
      {bearsMla && (
        <div className={styles.treeNodePromosSection}>
          <button
            type="button"
            className="btn-tesla ghost sm"
            onClick={() => setPromosOpen((prev) => !prev)}
            aria-expanded={promosOpen}
          >
            Promociones {promosOpen ? '▾' : '▸'}
          </button>
          {promosOpen && (
            <MlaPromocionesPanel key={promosReloadKey} mla={node.mla} promosCacheRef={promosCacheRef} />
          )}
        </div>
      )}

      {children.length > 0 && (
        <div className={styles.treeNodeChildrenSection}>
          <table className={styles.innerTable}>
            <tbody>
              {children.map((child) => (
                <TreeNode
                  key={child.mla || `${child.kind}-${child.family_id || child.catalog_product_id || child.level}-${rowKey}`}
                  node={child}
                  colSpan={colSpan}
                  mlasCacheRef={mlasCacheRef}
                  promosCacheRef={promosCacheRef}
                  promoTipos={promoTipos}
                  promoEstado={promoEstado}
                  revealAll={revealAll}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </ExpandableRow>
  );
}

export default TreeNode;
