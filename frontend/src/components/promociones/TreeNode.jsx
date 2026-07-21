import { useState } from 'react';
import ExpandableRow from './ExpandableRow';
import MlaPromocionesPanel from './MlaPromocionesPanel';
import { isMlaBearing, isFilterActive, isNodeHidden, nodeHasVisibleContent } from './treeNodeUtils';
import styles from './promociones.module.css';

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

  return (
    <ExpandableRow
      colSpan={colSpan}
      isOpen={isOpen}
      onToggle={() => setIsOpen((prev) => !prev)}
      ariaLabel={isOpen ? `Colapsar ${displayLabel}` : `Expandir ${displayLabel}`}
      header={
        <>
          <td>
            <span className={`${styles.badge} ${badgeClass}`}>{kindLabel}</span>
          </td>
          <td>{displayLabel}</td>
        </>
      }
    >
      {bearsMla && (
        <div className={styles.treeNodePromosSection}>
          <button
            type="button"
            className={styles.retryLink}
            onClick={() => setPromosOpen((prev) => !prev)}
            aria-expanded={promosOpen}
          >
            Promociones {promosOpen ? '▾' : '▸'}
          </button>
          {promosOpen && <MlaPromocionesPanel mla={node.mla} promosCacheRef={promosCacheRef} />}
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
