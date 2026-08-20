/**
 * DuplicateGroupCard — one DUPLICADO group's card (table redesign pass C).
 *
 * Replaces the old plain-text header sentence + nested `product_id: N` /
 * `variant_id: N` table with a card: a group header (thumbnail, title, EAN,
 * conflict-count pill, short presence label) and one row per conflicting TN
 * match (thumbnail, SKU, a Publicado/Borrador/Desconocido badge — the same
 * vocabulary `tnPresenceShortLabelFor` uses for the general table's presence
 * label — the bare product_id/variant_id pair, and that match's own
 * "Editar en TN" link).
 *
 * NO single group-level "Editar en TN" link: the group has N conflicting
 * matches, and linking only one of them would implicitly recommend it
 * (violates the DUPLICADO "human decides" rule — see the page's module
 * docstring). Each match row carries its OWN link instead — none privileged,
 * none pre-selected/highlighted.
 */
import { ExternalLink } from 'lucide-react';
import { matchPublishedLabel, rowIdentity } from '../../pages/tiendaNubeReconcileHelpers';
import styles from './DuplicateGroupCard.module.css';

const MATCH_BADGE_CLASS = {
  Publicado: 'badgeGreen',
  Borrador: 'badgeOrange',
  Desconocido: 'badgeTertiary',
};

export default function DuplicateGroupCard({ row }) {
  const { text: titleText, fromErp } = rowIdentity(row);
  const thumbSrc = Array.isArray(row.images) && row.images.length > 0 ? row.images[0] : null;
  const altText = titleText ? `Miniatura de ${titleText}` : `Miniatura del EAN ${row.ean}`;
  const presenceLabel = row.tn_presence === 'not_in_tn' ? 'Sin presencia en TN' : 'Existe en TN';

  return (
    <div className={styles.card} data-testid="duplicado-group">
      <div className={styles.header} data-testid="duplicado-group-header">
        {thumbSrc ? (
          <img src={thumbSrc} alt={altText} className={styles.headerThumb} loading="lazy" />
        ) : (
          <span className={styles.headerThumbPlaceholder} aria-hidden="true" />
        )}
        <div className={styles.headerText}>
          <div className={styles.headerTitle}>
            {fromErp && <span className={styles.erpTag}>ERP</span>}
            {titleText || `EAN ${row.ean}`}
          </div>
          <div className={styles.headerEan}>{row.ean}</div>
        </div>
        <span className={styles.conflictPill}>{row.tn_matches.length} en conflicto</span>
        <span className={styles.presenceNote}>{presenceLabel}</span>
      </div>

      <div className={styles.matches}>
        {row.tn_matches.map((tn) => {
          const publishedLabel = matchPublishedLabel(tn.published);
          const badgeClass = MATCH_BADGE_CLASS[publishedLabel] || 'badgeTertiary';
          return (
            <div
              key={`${tn.product_id}-${tn.variant_id}`}
              className={styles.matchRow}
              data-testid="duplicado-match-row"
            >
              {tn.image ? (
                <img src={tn.image} alt="" aria-hidden="true" className={styles.matchThumb} loading="lazy" />
              ) : (
                <span className={styles.matchThumbPlaceholder} aria-hidden="true" />
              )}
              <span className={styles.matchSku}>{tn.variant_sku}</span>
              <span className={`${styles.matchBadge} ${styles[badgeClass]}`}>{publishedLabel}</span>
              <span className={styles.matchIds}>
                {tn.product_id} / {tn.variant_id}
              </span>
              {tn.tn_admin_url ? (
                <a
                  href={tn.tn_admin_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.tnLink}
                  aria-label={`Editar en TN el producto ${tn.product_id}`}
                >
                  Editar en TN <ExternalLink size={12} aria-hidden="true" />
                </a>
              ) : (
                <span className={styles.noLink}>—</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
