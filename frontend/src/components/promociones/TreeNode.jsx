import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, CircleHelp, Clock, PauseCircle, RefreshCw, XCircle } from 'lucide-react';
import ExpandableRow from './ExpandableRow';
import MlaPromocionesPanel from './MlaPromocionesPanel';
import CatalogCompetitionPanel from './CatalogCompetitionPanel';
import PxqPanel from './PxqPanel';
import {
  isMlaBearing,
  isFilterActive,
  hoistsChildren,
  nodeHasVisibleContent,
  describeChildKinds,
} from './treeNodeUtils';
import { getPublicationTypeLabel } from '../../constants/mlPublicationTypes';
import { publicationStatusInfo, subStatusTitle } from '../publicacionesMl/publicationStatus';
import { useTiendasOficiales } from '../../hooks/useTiendasOficiales';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { getMarkupColor } from '../../hooks/useProductosOffsets';
import { useTreeViewStore } from '../../store/treeViewStore';
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

// Per-MLA publication status badge. Status comes from the ML publications
// store (`ml_items.status`, the same field the promotions panel's banner
// reads), labelled by the shared Publicaciones ML map so every view reads the
// same. The glyph is a `lucide-react` icon (AGENTS.md: no emoji as icons) and
// the color comes from semantic tokens, both picked by the label's tone.
const STATUS_BADGE_BY_TONE = {
  success: { Icon: CheckCircle2, className: styles.badgeStatusActive },
  warning: { Icon: PauseCircle, className: styles.badgeStatusPaused },
  danger: { Icon: XCircle, className: styles.badgeStatusClosed },
  info: { Icon: Clock, className: styles.badgeStatusUnderReview },
  neutral: { Icon: CircleHelp, className: styles.badgeReadonly },
};

function statusBadgeFor(node) {
  const info = publicationStatusInfo(node.publication_status, node.publication_sub_status);
  if (!info) return null;
  const { Icon, className } = STATUS_BADGE_BY_TONE[info.tone] || STATUS_BADGE_BY_TONE.neutral;
  return { label: info.label, Icon, className, title: subStatusTitle(node.publication_sub_status) };
}

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
 * `promoTipos`/`promoEstado`/`mlasCacheRef`/`promosCacheRef`/
 * `catalogCompetitionCacheRef`/`pxqCacheRef` MUST be forwarded unchanged
 * through every recursive call so the shipped promo filter, per-MLA
 * dynamic-refresh reload timers, and the catalog-competition/PxQ panels'
 * caches keep working at any depth — dropping them here silently breaks
 * those features deeper in the tree (this is the design's flagged #1 FE
 * risk; the catalog-competition panel was previously omitted from the
 * collapse-epoch sync effect below and had to be fixed once already).
 * `revealAll` and `showDeleted` are forwarded the same way.
 */
function TreeNode({
  node,
  colSpan,
  mlasCacheRef,
  promosCacheRef,
  catalogCompetitionCacheRef,
  pxqCacheRef,
  promoTipos,
  promoEstado,
  tiendaOficial,
  conPxq,
  revealAll = false,
  showDeleted = false,
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [promosOpen, setPromosOpen] = useState(false);
  const [catalogCompetitionOpen, setCatalogCompetitionOpen] = useState(false);
  const [pxqOpen, setPxqOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(false);
  const [promosReloadKey, setPromosReloadKey] = useState(0);
  const { tienePermiso } = usePermisos();
  const { getLabel } = useTiendasOficiales();
  const showFamilia = useTreeViewStore((state) => state.showFamilia);
  const collapseEpoch = useTreeViewStore((state) => state.collapseEpoch);
  const collapseMode = useTreeViewStore((state) => state.collapseMode);
  const markManual = useTreeViewStore((state) => state.markManual);

  // Global synchronized collapse toggle (tree-view-collapse, design D6): syncs
  // this node's local open state from the store when the epoch changes (an
  // actual global activation) and on mount, never on every render.
  //
  // The mount case is load-bearing, not incidental: children only mount once
  // their parent is open, so "expand all" reaches an unmounted subtree through
  // the mount cascade. `markManual()` below is what stops that cascade from
  // outliving the global action — once the user toggles anything by hand the
  // mode goes back to 'manual' and later mounts stop force-opening. Without it,
  // every node opened by hand after one "expand all" would re-explode its whole
  // subtree for the rest of the session.
  useEffect(() => {
    if (collapseEpoch === 0 || collapseMode === 'manual') return;
    const open = collapseMode === 'all-open';
    setIsOpen(open);
    setPromosOpen(open);
    setCatalogCompetitionOpen(open);
    setPxqOpen(open);
    // collapseMode is read on purpose without being a dependency: the effect
    // must fire only on an actual global activation (the epoch), never when
    // the mode changes on its own, or a manual toggle would be clobbered on
    // the next render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collapseEpoch]);

  // Guards the async refresh follow-up from setState-ing after the node
  // unmounts (e.g. the tree re-renders on a promo-filter change while a
  // refresh is still in flight).
  const mountedRef = useRef(true);
  // Set right before a refresh-triggered remount so the panel skips its own
  // pull — the refresh handler already did it. Cleared once that remount has
  // committed: it covers exactly ONE mount. Left sticky, a single click on
  // refresh stopped this node from ever pulling on open again.
  const justRefreshedRef = useRef(false);
  useEffect(() => () => { mountedRef.current = false; }, []);

  // Runs after the refresh-triggered remount has rendered with the flag set,
  // so the NEXT open pulls again. Clearing it during render would mutate a ref
  // in a phase React requires to be pure.
  useEffect(() => {
    justRefreshedRef.current = false;
  }, [promosReloadKey]);

  const filterActive = isFilterActive(promoTipos, promoEstado, tiendaOficial, conPxq);

  // Also hides an MLA-bearing node that does not hoist its children: for it,
  // `nodeHasVisibleContent` is `!isNodeHidden`.
  if (!nodeHasVisibleContent(node, filterActive, revealAll, showDeleted)) {
    return null;
  }

  const children = node.children || [];

  // Familia grouping is OPTIONAL (global view toggle, default hidden): when
  // disabled, skip rendering the familia's own header row entirely and
  // render its children directly — everything below shifts one level up
  // (under the producto). Only `kind === 'familia'` is affected; every other
  // kind (producto/catalogo/vinculada/publicacion) renders unchanged either
  // way. Children keep forwarding the exact same props so promo filter
  // (matches_filter reveal), the promo summary, the lista badge and the
  // refresh button keep working via each hoisted child's own TreeNode logic.
  // A deleted publication hidden only for being deleted hoists its children
  // the same way (`hoistsChildren`): its live vinculadas stay in view.
  if ((node.kind === 'familia' && !showFamilia) || hoistsChildren(node, filterActive, revealAll, showDeleted)) {
    const rowKey = node.mla || `${node.kind}-${node.family_id || node.catalog_product_id || node.level}`;
    return (
      <>
        {children.map((child) => (
          <TreeNode
            key={child.mla || `${child.kind}-${child.family_id || child.catalog_product_id || child.level}-${rowKey}`}
            node={child}
            colSpan={colSpan}
            mlasCacheRef={mlasCacheRef}
            promosCacheRef={promosCacheRef}
            catalogCompetitionCacheRef={catalogCompetitionCacheRef}
            pxqCacheRef={pxqCacheRef}
            promoTipos={promoTipos}
            promoEstado={promoEstado}
            tiendaOficial={tiendaOficial}
            conPxq={conPxq}
            revealAll={revealAll}
            showDeleted={showDeleted}
          />
        ))}
      </>
    );
  }

  const kindLabel = KIND_LABELS[node.kind] || node.kind;
  const badgeClass = KIND_BADGE_CLASS[node.kind] || styles.badgeReadonly;
  const displayLabel = node.label || node.mla || kindLabel;
  const rowKey = node.mla || `${node.kind}-${node.family_id || node.catalog_product_id || node.level}`;
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

  // Price-list badge (restores the old flat panel's per-publication
  // `lista_nombre || getPublicationTypeLabel(pricelist_id)` badge) — fail-open:
  // absent on both fields renders nothing.
  const listaLabel = bearsMla
    ? node.lista_nombre || (node.pricelist_id != null ? getPublicationTypeLabel(node.pricelist_id) : null)
    : null;

  // Publication status badge (from `ml_items.status`) — grouping nodes never
  // carry one; an absent status (the store read failed) renders nothing, an
  // MLA the store has no row for says "Sin datos de ML", and an unknown ML
  // status is shown verbatim.
  const statusBadge = bearsMla ? statusBadgeFor(node) : null;

  // Official store badge (promos-catalog-prices-and-official-store, slice A)
  // — grouping nodes never carry one. NULL/unknown store still renders an
  // explicit "Sin tienda" pill (never blank/omitted), per spec A3.
  const storeLabel = bearsMla ? getLabel(node.official_store_id) : null;

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
        // The entry also feeds the promo filter bar's derived types, so
        // dropping the stale one keeps that from showing what the server just
        // replaced. Safe even if we unmounted; state updates are guarded.
        promosCacheRef.current.delete(node.mla);
        if (mountedRef.current && promosOpen) {
          // The remount must NOT pull again: this handler just did. Without
          // the flag one click on refresh became two pulls, on the throttle
          // shared with sales-webhook processing.
          justRefreshedRef.current = true;
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
      onToggle={() => { markManual(); setIsOpen((prev) => !prev); }}
      ariaLabel={isOpen ? `Colapsar ${displayLabel}` : `Expandir ${displayLabel}`}
      headerRowClassName={KIND_ROW_CLASS[node.kind]}
      header={
        <>
          <td className={styles.treeNodeLabelCell}>
            <span className={`${styles.badge} ${badgeClass}`}>{kindLabel}</span>
            <span className={styles.treeNodeLabel}>{displayLabel}</span>
            {listaLabel && <span className={`${styles.badge} ${styles.badgeReadonly}`}>{listaLabel}</span>}
            {statusBadge && (
              <span className={`${styles.badge} ${statusBadge.className}`} title={statusBadge.title}>
                <statusBadge.Icon size={12} aria-hidden="true" />
                {statusBadge.label}
              </span>
            )}
            {bearsMla && (
              <span className={`${styles.badge} ${styles.badgeReadonly}`}>
                {storeLabel || 'Sin tienda'}
              </span>
            )}
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
            className={`btn-tesla outline-subtle-primary sm ${promosOpen ? 'toggle-active' : ''}`}
            onClick={() => { markManual(); setPromosOpen((prev) => !prev); }}
            aria-expanded={promosOpen}
          >
            Promociones {promosOpen ? '▾' : '▸'}
          </button>
          {promosOpen && (
            <MlaPromocionesPanel
              key={promosReloadKey}
              mla={node.mla}
              promosCacheRef={promosCacheRef}
              pullOnOpen={!justRefreshedRef.current && collapseMode !== 'all-open'}
            />
          )}
          <button
            type="button"
            className={`btn-tesla outline-subtle-primary sm ${catalogCompetitionOpen ? 'toggle-active' : ''}`}
            onClick={() => { markManual(); setCatalogCompetitionOpen((prev) => !prev); }}
            aria-expanded={catalogCompetitionOpen}
          >
            Competencia catálogo {catalogCompetitionOpen ? '▾' : '▸'}
          </button>
          {catalogCompetitionOpen && (
            <CatalogCompetitionPanel mla={node.mla} catalogCompetitionCacheRef={catalogCompetitionCacheRef} />
          )}
          <button
            type="button"
            className={`btn-tesla outline-subtle-primary sm ${pxqOpen ? 'toggle-active' : ''}`}
            onClick={() => { markManual(); setPxqOpen((prev) => !prev); }}
            aria-expanded={pxqOpen}
          >
            Precios mayoristas {pxqOpen ? '▾' : '▸'}
          </button>
          {pxqOpen && <PxqPanel itemId={node.mla} pxqCacheRef={pxqCacheRef} />}
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
                  catalogCompetitionCacheRef={catalogCompetitionCacheRef}
                  pxqCacheRef={pxqCacheRef}
                  promoTipos={promoTipos}
                  promoEstado={promoEstado}
                  tiendaOficial={tiendaOficial}
                  conPxq={conPxq}
                  revealAll={revealAll}
                  showDeleted={showDeleted}
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
