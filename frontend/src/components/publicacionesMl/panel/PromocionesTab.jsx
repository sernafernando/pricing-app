import { useEffect, useState } from 'react';
import MlaPromocionesPanel from '../../promociones/MlaPromocionesPanel';
import CatalogCompetitionPanel from '../../promociones/CatalogCompetitionPanel';
import { markPromoPulled, promoPulledRecently } from '../../promociones/promoPullTtl';
import styles from './panel.module.css';

/** One MLA's promotions; mounted per MLA, so its pull decision is that MLA's. */
function ItemPromotions({ itemId, suggestedPromotionIds, promosCacheRef, onPromoApplied }) {
  // Read once per mount: the pull this mount starts must not switch itself off when it succeeds.
  const [pullOnOpen] = useState(() => !promoPulledRecently(itemId));
  return (
    <MlaPromocionesPanel
      mla={itemId}
      promosCacheRef={promosCacheRef}
      pullOnOpen={pullOnOpen}
      ignoreGlobalFilter
      suggestedPromotionIds={suggestedPromotionIds}
      sections
      onApplied={onPromoApplied}
      onPulled={markPromoPulled}
    />
  );
}

/**
 * Promociones tab: the promotions of the selected publication, through the
 * panel the Productos page already uses.
 *
 * It mounts only while the tab is open (the panel renders the active tab and
 * nothing else). It is the panel's first tab (owner, 2026-11-02), so opening a
 * publication opens it: to keep a click through rows from costing an ML pull
 * per click on a throttle shared with sales-webhook processing, an MLA pulled
 * successfully in the last 5 minutes shows its mirror without pulling again
 * (`promoPullTtl`); an apply or remove forgets it (inside `MlaPromocionesPanel`). `MlaPromocionesPanel`
 * itself gates the pull and the apply/remove controls on `promos.ver` /
 * `promos.escribir`.
 *
 * The promotions come in sections (S3): Activa ahora, Disponibles para activar (with the markup each would leave),
 * Otras promociones and, last and quieter, the coupons, read-only with a link to Mercado Libre.
 *
 * `onPromoApplied` fires after an apply or remove, so the panel can re-read
 * the price and markup it shows.
 *
 * `suggestedPromotionIds` are the promotions the "Hay candidatas mejores" block above the tabs suggests;
 * their rows carry a "Sugerida" chip instead of a second banner here.
 *
 * When the publication is a catalog listing, the same-bucket ranking
 * (`CatalogCompetitionPanel` variant `ranking`) shows in column 2 while
 * `competenciaOpen` (open by default; **Ocultar competencia** closes it).
 * `onCompetenciaShownChange` tells the page when it is on screen, so the
 * split starts wider. Promos stay in column 1 at their compact width; on a
 * panel too narrow for both, the ranking stacks under them.
 *
 * `key={itemId}` makes a new selection start from scratch, so one
 * publication's promotions are never shown under the next. The cache is
 * private to this tab: the Productos filter bar that reads its entries is not
 * on this page, and the global promo filter is ignored for the same reason.
 */
export default function PromocionesTab({
  itemId,
  detail,
  onPromoApplied,
  suggestedPromotionIds,
  competenciaOpen = false,
  onCompetenciaOpenChange,
  onCompetenciaShownChange,
}) {
  const [promosCacheRef] = useState(() => ({ current: new Map() }));
  const [catalogCacheRef] = useState(() => ({ current: new Map() }));
  const isCatalog = Boolean(detail?.row?.catalog_listing);
  const showRanking = isCatalog && competenciaOpen;

  useEffect(() => {
    onCompetenciaShownChange?.(showRanking);
  }, [showRanking, onCompetenciaShownChange]);
  // Leaving the tab (or the publication) takes the ranking off screen.
  useEffect(() => () => onCompetenciaShownChange?.(false), [onCompetenciaShownChange]);

  const toggleCompetencia = () => {
    onCompetenciaOpenChange?.(!competenciaOpen);
  };

  return (
    <div className={styles.promosContainer}>
      <div className={showRanking ? styles.promosLayoutWide : styles.promosLayout}>
        <div className={styles.promosCol}>
          {isCatalog && (
            <button
              type="button"
              className={`btn-tesla outline-subtle-primary sm ${styles.promosCompetenciaToggle}`}
              onClick={toggleCompetencia}
              aria-pressed={competenciaOpen}
            >
              {competenciaOpen ? 'Ocultar competencia' : 'Ver competencia'}
            </button>
          )}
          <ItemPromotions
            key={itemId}
            itemId={itemId}
            suggestedPromotionIds={suggestedPromotionIds}
            promosCacheRef={promosCacheRef}
            onPromoApplied={onPromoApplied}
          />
        </div>
        {showRanking && (
          <div className={styles.promosCompetenciaCol}>
            <h3 className={styles.promosCompetenciaTitle}>Competencia del catálogo</h3>
            <CatalogCompetitionPanel
              key={`catalog-${itemId}`}
              mla={itemId}
              catalogCompetitionCacheRef={catalogCacheRef}
              variant="ranking"
            />
          </div>
        )}
      </div>
    </div>
  );
}
