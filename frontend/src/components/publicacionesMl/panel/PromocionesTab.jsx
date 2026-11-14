import { useEffect, useState } from 'react';
import MlaPromocionesPanel from '../../promociones/MlaPromocionesPanel';
import CatalogCompetitionPanel from '../../promociones/CatalogCompetitionPanel';
import PromoFilterBar from '../../promociones/PromoFilterBar';
import { countActivePromoFilter } from '../../promociones/promoFilterPredicate';
import { markPromoPulled, promoPulledRecently } from '../../promociones/promoPullTtl';
import { usePromoFilterStore } from '../../../store/promoFilterStore';
import { usePermisos } from '../../../contexts/PermisosContext';
import { promocionesAPI } from '../../../services/api';
import styles from './panel.module.css';

const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

/**
 * The global promo filter, in the tab header: "Filtrar promos" opens the
 * Productos filter bar (type chips + "Nombres"), and while a filter is set
 * the header says so ("Filtro: 2 tipos · 3 nombres") with a one-click clear,
 * so a promotion it hides never looks missing.
 */
function PromoFilterHeader({ promosCacheRef }) {
  const selectedTypes = usePromoFilterStore((state) => state.selectedTypes);
  const selectedNames = usePromoFilterStore((state) => state.selectedNames);
  const clear = usePromoFilterStore((state) => state.clear);
  const [open, setOpen] = useState(false);

  const active = countActivePromoFilter(selectedTypes, selectedNames);
  const parts = [
    active.types > 0 && plural(active.types, 'tipo', 'tipos'),
    active.names > 0 && plural(active.names, 'nombre', 'nombres'),
  ].filter(Boolean);

  return (
    <div className={styles.promosFilter}>
      <div className={styles.promosFilterRow}>
        <button
          type="button"
          className={`btn-tesla outline-subtle-primary sm ${styles.promosFilterToggle}`}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          Filtrar promos
        </button>
        {parts.length > 0 && (
          <>
            <span className={styles.promosFilterSummary} title={`Filtro: ${parts.join(' · ')}`}>
              Filtro: {parts.join(' · ')}
            </span>
            <button type="button" className={styles.promosFilterClear} onClick={clear}>
              Quitar filtro
            </button>
          </>
        )}
      </div>
      {open && <PromoFilterBar promosCacheRef={promosCacheRef} showLabel={false} />}
    </div>
  );
}

/** One MLA's promotions; mounted per MLA, so its pull decision is that MLA's. */
function ItemPromotions({ itemId, suggestedPromotionIds, promosCacheRef, onPromoApplied }) {
  // Read once per mount: the pull this mount starts must not switch itself off when it succeeds.
  const [pullOnOpen] = useState(() => !promoPulledRecently(itemId));
  return (
    <MlaPromocionesPanel
      mla={itemId}
      promosCacheRef={promosCacheRef}
      pullOnOpen={pullOnOpen}
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
 * private to this tab; the filter bar in the tab header reads its entries for
 * the "Nombres" modal.
 *
 * The global promo filter (the one Productos sets) applies here too: it is one
 * setting for the user, not per publication, so it stays when the selection
 * changes and survives a reload. Its bar and an active-filter summary with a
 * one-click clear sit in the tab header (`PromoFilterHeader`), so a filtered-out
 * promotion always has a visible way back.
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
  const { tienePermiso } = usePermisos();
  const canWritePromos = tienePermiso('promos.escribir');
  const [promosCacheRef] = useState(() => ({ current: new Map() }));
  const [catalogCacheRef] = useState(() => ({ current: new Map() }));
  const [exclusionBusy, setExclusionBusy] = useState(false);
  const [exclusionError, setExclusionError] = useState(null);
  const isCatalog = Boolean(detail?.row?.catalog_listing);
  const showRanking = isCatalog && competenciaOpen;
  const excluido = Boolean(detail?.row?.hay_mejores_excluido);

  useEffect(() => {
    onCompetenciaShownChange?.(showRanking);
  }, [showRanking, onCompetenciaShownChange]);
  // Leaving the tab (or the publication) takes the ranking off screen.
  useEffect(() => () => onCompetenciaShownChange?.(false), [onCompetenciaShownChange]);
  useEffect(() => {
    setExclusionError(null);
  }, [itemId]);

  const toggleCompetencia = () => {
    onCompetenciaOpenChange?.(!competenciaOpen);
  };

  const toggleExclusion = async () => {
    if (!canWritePromos || exclusionBusy) return;
    setExclusionBusy(true);
    setExclusionError(null);
    try {
      await promocionesAPI.setHayMejoresExclusion(itemId, !excluido);
      onPromoApplied?.();
    } catch {
      setExclusionError('No se pudo actualizar la exclusión de hay mejores.');
    } finally {
      setExclusionBusy(false);
    }
  };

  return (
    <div className={styles.promosContainer}>
      <div className={showRanking ? styles.promosLayoutWide : styles.promosLayout}>
        <div className={styles.promosCol}>
          <PromoFilterHeader promosCacheRef={promosCacheRef} />
          <div className={styles.promosToolbarRow}>
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
            {canWritePromos && (
              <label className={styles.promosExclusion}>
                <input
                  type="checkbox"
                  checked={excluido}
                  disabled={exclusionBusy}
                  onChange={toggleExclusion}
                />
                Excluir de hay mejores
              </label>
            )}
          </div>
          {exclusionError && (
            <p className={styles.promosExclusionError} role="alert">
              {exclusionError}
            </p>
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
