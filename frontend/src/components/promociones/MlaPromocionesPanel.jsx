import { useCallback, useEffect, useRef } from 'react';
import { promocionesAPI } from '../../services/api';
import { useLazyResource } from '../../hooks/useLazyResource';
import PromoApplyControl from './PromoApplyControl';
import styles from './promociones.module.css';

// SELLER_CAMPAIGN/DEAL/SMART can be enrolled via the apply control (FE-C).
// DOD/LIGHTNING/PRICE_DISCOUNT are read-only informational entries.
const APPLICABLE_TYPES = new Set(['SELLER_CAMPAIGN', 'DEAL', 'SMART']);

// SMART and PRE_NEGOTIATED both carry ML co-funding (meli_percentage /
// seller_percentage in payload); other types don't fund the discount.
const CO_FUNDED_TYPES = new Set(['SMART', 'PRE_NEGOTIATED']);

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
  const fetcher = useCallback((id) => promocionesAPI.getPromocionesItem(id).then((r) => r.data), []);
  const { data, loading, error, reload } = useLazyResource(promosCacheRef, mla, fetcher);
  const reloadTimerRef = useRef(null);

  useEffect(
    () => () => {
      if (reloadTimerRef.current) {
        clearTimeout(reloadTimerRef.current);
        reloadTimerRef.current = null;
      }
    },
    [],
  );

  if (loading) {
    return <div className={styles.panelState}>Cargando promociones...</div>;
  }

  if (error) {
    return (
      <div className={styles.panelStateError}>
        Error al cargar promociones.{' '}
        <button type="button" className={styles.retryLink} onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  }

  const promociones = data?.promotions || [];

  if (promociones.length === 0) {
    return <div className={styles.panelState}>Sin promociones habilitadas.</div>;
  }

  return (
    <ul className={styles.promoList}>
      {promociones.map((promo) => {
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
            <span className={`${styles.badge} ${applicable ? styles.badgeApplicable : styles.badgeReadonly}`}>
              {promo.promotion_type || 'N/A'}
            </span>
            {promo.application_status === 'active' && (
              <span className={`${styles.badge} ${styles.badgeApplicable}`}>Aplicada</span>
            )}
            {promo.application_status === 'programmed' && (
              <span className={`${styles.badge} ${styles.badgeProgrammed}`}>Programada</span>
            )}
            <span className={styles.promoName}>
              {promo.name || promo.payload?.name || promo.promotion_type || promo.promotion_id}
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
            <span className={styles.promoMarkup}>Tu markup: {formatMarkup(promo.nuestro_markup)}</span>
            {applicable && (
              <PromoApplyControl
                mla={mla}
                promotion={promo}
                onApplied={() => {
                  // Invalidate the L2 cache so a manual/later refresh re-reads;
                  // do NOT assert the final state from this reload alone
                  // (eventual consistency — the table stays the source of truth).
                  // Clear any prior pending timer before scheduling a new one, and
                  // clear on unmount so we never call reload() after the panel
                  // (and the underlying setState) is gone.
                  if (reloadTimerRef.current) {
                    clearTimeout(reloadTimerRef.current);
                  }
                  reloadTimerRef.current = setTimeout(() => {
                    reloadTimerRef.current = null;
                    reload();
                  }, 4000);
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
