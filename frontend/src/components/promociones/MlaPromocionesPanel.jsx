import { useCallback, useEffect, useRef } from 'react';
import { promocionesAPI } from '../../services/api';
import { useLazyResource } from '../../hooks/useLazyResource';
import { usePromoFilterStore } from '../../store/promoFilterStore';
import { useTreeViewStore } from '../../store/treeViewStore';
import { getMarkupColor } from '../../hooks/useProductosOffsets';
import { matchesPromoFilter } from './promoFilterPredicate';
import { resolvePromoName } from './resolvePromoName';
import PromoApplyControl from './PromoApplyControl';
import styles from './promociones.module.css';

// SELLER_CAMPAIGN/DEAL/SMART/PRE_NEGOTIATED/PRICE_MATCHING can be enrolled
// via the apply control (FE-C). DOD/LIGHTNING/PRICE_DISCOUNT are read-only
// informational entries. PRICE_MATCHING_MELI_ALL is intentionally EXCLUDED
// (ML-autogestionado, never writable) — its absence here is what keeps it
// read-only; never add it.
const APPLICABLE_TYPES = new Set(['SELLER_CAMPAIGN', 'DEAL', 'SMART', 'PRE_NEGOTIATED', 'PRICE_MATCHING']);

// SMART, PRE_NEGOTIATED and PRICE_MATCHING all carry ML co-funding
// (meli_percentage / seller_percentage in payload); other types don't fund
// the discount.
const CO_FUNDED_TYPES = new Set(['SMART', 'PRE_NEGOTIATED', 'PRICE_MATCHING']);

// Per-type badge hue so each promotion type is visually distinct (no longer
// all-blue). Types not listed (PRICE_DISCOUNT/DOD/LIGHTNING/
// PRICE_MATCHING_MELI_ALL) fall back to the read-only grey badge.
const TYPE_BADGE_CLASS = {
  SELLER_CAMPAIGN: styles.badgeTypeSellerCampaign,
  DEAL: styles.badgeTypeDeal,
  SMART: styles.badgeTypeSmart,
  PRE_NEGOTIATED: styles.badgeTypePreNegotiated,
  PRICE_MATCHING: styles.badgeTypePriceMatching,
};

function formatPercentage(value) {
  if (value === null || value === undefined) return null;
  return `${value}%`;
}

function formatPrice(value) {
  if (value === null || value === undefined) return 'N/A';
  return `$${Number(value).toLocaleString('es-AR')}`;
}

// Backend-computed markup on the promo's effective revenue (server-side
// pricing math). No FE computation — only rendering.
function formatMarkup(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
  return `${Number(value).toFixed(1)}%`;
}

// Formats an ISO date string as short DD/MM (locale-safe, no new deps).
// Returns null when the input isn't a parseable date.
function formatShortDate(isoString) {
  if (!isoString) return null;
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return null;
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  return `${day}/${month}`;
}

// Compact date range for a promo row; null when either date is missing or
// unparseable (never renders "Invalid Date" or a dash-only string).
function formatDateRange(startDate, finishDate) {
  const start = formatShortDate(startDate);
  const finish = formatShortDate(finishDate);
  if (!start || !finish) return null;
  return `${start} – ${finish}`;
}

/**
 * Level 2 panel: promotions of a single MLA.
 * Lazily fetches `GET /promociones/item/{mla}` on first mount (i.e. on
 * first expand — the parent conditionally mounts this component).
 */
function MlaPromocionesPanel({ mla, promosCacheRef }) {
  // Opening the panel pulls fresh state from MercadoLibre first, then reads
  // the mirror the server just updated.
  //
  // This REVERSES the earlier product decision that kept refreshes manual
  // because the ML throttle is shared with sales-webhook processing. The
  // product owner asked for it explicitly: seeing stale promotions without
  // knowing they are stale was the worse failure. The cost is real — every
  // open competes for that shared throttle — and it is a deliberate trade,
  // not an oversight.
  //
  // `alwaysRefetch` makes a collapse/re-expand genuinely refetch instead of
  // serving the cached mirror, which would defeat the whole point. The cache
  // is still WRITTEN — the promo filter bar derives its types from those
  // entries — so bypassing it is not an option, only re-reading it is.
  const fetchFreshThenRead = useCallback(
    (id) =>
      Promise.resolve(promocionesAPI.refreshItemPromociones(id))
        // A failed refresh degrades to the stored mirror rather than blanking
        // the panel: stale data on a working screen beats an error and
        // nothing. The mirror is still whatever the server last confirmed.
        .catch(() => null)
        .then(() => promocionesAPI.getPromocionesItem(id))
        .then((r) => r.data),
    [],
  );

  // `reload()` reads the mirror WITHOUT pulling from ML again. The post-apply
  // timers and the error-state retry both go through it, and each of those
  // firing a refresh would have added three more ML calls per apply on a
  // throttle shared with sales-webhook processing — a cost nobody asked for
  // and that the "refresh on open" request does not imply.
  const readMirror = useCallback((id) => promocionesAPI.getPromocionesItem(id).then((r) => r.data), []);

  // A global "Expandir todo" mounts every MLA panel in the tree at once. If
  // each one pulled from ML, a product with 20 publications would turn one
  // click into 20 concurrent pulls on a throttle shared with sales-webhook
  // processing. Opening a panel yourself is the interaction that asked for
  // fresh state; a cascade is not, so it reads the mirror like any reload.
  const openedByGlobalToggle = useTreeViewStore.getState().collapseMode === 'all-open';

  const { data, loading, error, reload } = useLazyResource(
    promosCacheRef,
    mla,
    openedByGlobalToggle ? readMirror : fetchFreshThenRead,
    { alwaysRefetch: true, reloadFetcher: readMirror },
  );
  // After our own enroll/remove write the server refreshes on its own
  // (immediate + a ~60s retry-queue drain), and the panel just re-READS that
  // mirror at two points: ~5s (fast SELLER_CAMPAIGN/DEAL/consistency) and ~65s
  // (after the server's ~60s retry drains for slower SMART reconciliation).
  const reloadTimersRef = useRef([]);
  const selectedTypes = usePromoFilterStore((state) => state.selectedTypes);
  const selectedNames = usePromoFilterStore((state) => state.selectedNames);

  const clearReloadTimers = useCallback(() => {
    reloadTimersRef.current.forEach((timerId) => clearTimeout(timerId));
    reloadTimersRef.current = [];
  }, []);

  useEffect(() => () => clearReloadTimers(), [clearReloadTimers]);

  if (loading) {
    return <div className={styles.panelState}>Cargando promociones...</div>;
  }

  if (error) {
    return (
      <div className={styles.panelStateError}>
        Error al cargar promociones.{' '}
        <button type="button" className="btn-tesla ghost sm" onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  }

  const promociones = data?.promotions || [];

  if (promociones.length === 0) {
    return <div className={styles.panelState}>Sin promociones habilitadas.</div>;
  }

  // Global filter (client-side only): type narrows first, then name narrows
  // within the permitted types. Nothing selected in either -> show all.
  const filteredPromociones = promociones.filter((promo) =>
    matchesPromoFilter(promo, selectedTypes, selectedNames),
  );

  if (filteredPromociones.length === 0) {
    return <div className={styles.filterMessage}>Sin promos del tipo filtrado.</div>;
  }

  return (
    <ul className={styles.promoList}>
      {filteredPromociones.map((promo) => {
        const applicable = APPLICABLE_TYPES.has(promo.promotion_type);
        const sellerPct = formatPercentage(promo.payload?.seller_percentage);
        const meliPct = formatPercentage(promo.payload?.meli_percentage);
        // `price` is 0 for candidate promos (not yet applied); fall back to the
        // suggested discounted price so the row shows the price it WOULD apply
        // at, not $0. Started promos (SMART/LIGHTNING) carry a real `price`.
        const effectivePrice = promo.price > 0 ? promo.price : promo.suggested_discounted_price;
        const dateRange = formatDateRange(promo.start_date, promo.finish_date);

        return (
          <li
            key={promo.promotion_id}
            className={`${styles.promoRow} ${applicable ? styles.promoApplicable : styles.promoReadonly}`}
          >
            <span className={`${styles.badge} ${TYPE_BADGE_CLASS[promo.promotion_type] || styles.badgeReadonly}`}>
              {promo.promotion_type || 'N/A'}
            </span>
            {promo.application_status === 'active' && (
              <span className={`${styles.badge} ${styles.badgeApplied}`}>Aplicada</span>
            )}
            {promo.application_status === 'programmed' && (
              <span className={`${styles.badge} ${styles.badgeProgrammed}`}>Programada</span>
            )}
            {promo.application_status === 'pending' && (
              <span className={`${styles.badge} ${styles.badgePending}`}>En espera</span>
            )}
            <span className={styles.promoName}>
              {resolvePromoName(promo) || promo.promotion_type || promo.promotion_id}
            </span>
            {dateRange && <span className={styles.promoDates}>{dateRange}</span>}
            <span className={styles.promoPrice}>
              {formatPrice(effectivePrice)}
              {promo.original_price != null && promo.original_price !== effectivePrice && (
                <span className={styles.promoOriginalPrice}> ({formatPrice(promo.original_price)})</span>
              )}
            </span>
            {CO_FUNDED_TYPES.has(promo.promotion_type) && (sellerPct || meliPct) && (
              <span className={styles.promoSmartCost}>
                {sellerPct && `Costo vendedor: ${sellerPct}`}
                {sellerPct && meliPct && ' · '}
                {meliPct && `Cofinanciación ML: ${meliPct}`}
              </span>
            )}
            <span className={styles.promoMarkup} style={{ color: getMarkupColor(promo.nuestro_markup) }}>
              Tu markup: {formatMarkup(promo.nuestro_markup)}
            </span>
            {applicable && (
              <PromoApplyControl
                mla={mla}
                promotion={promo}
                onApplied={() => {
                  // Do NOT assert the final state from either reload alone
                  // (eventual consistency — the table stays the source of
                  // truth). After a write the server refreshes the mirror on
                  // its own (immediate + ~60s retry) and these two reloads
                  // only RE-READ it — they do not pull from ML. Opening the
                  // panel does pull, which is a different path on purpose.
                  //
                  // Clear any prior pending timers before scheduling new
                  // ones, and clear on unmount so we never call reload()
                  // after the panel (and the underlying setState) is gone.
                  clearReloadTimers();
                  reloadTimersRef.current = [
                    setTimeout(() => reload(), 5000),
                    setTimeout(() => reload(), 65000),
                  ];
                }}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}

export default MlaPromocionesPanel;
