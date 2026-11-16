import { formatAmount } from '../../../utils/ventasMlFormat';
import { ML_PRICED_TYPES } from '../../promociones/promoDisplayPrice';
import { comparableMarkups, parsePromoInstant } from './pickPonerPreciosPromos';
import promoStyles from '../../promociones/promociones.module.css';
import styles from './panel.module.css';

// Same per-type badge hue as the Promos tab rows (MlaPromocionesPanel TYPE_BADGE_CLASS).
export const SLOT_BADGE = {
  SMART: promoStyles.badgeTypeSmart,
  DEAL: promoStyles.badgeTypeDeal,
  PRE_NEGOTIATED: promoStyles.badgeTypePreNegotiated,
  PRICE_MATCHING: promoStyles.badgeTypePriceMatching,
  LIGHTNING: promoStyles.badgeTypeLightning,
  SMART_LIGHTNING: promoStyles.badgeTypeSmartLightning,
  SELLER_CAMPAIGN: promoStyles.badgeTypeSellerCampaign,
};

export const pct = (value) => `${formatAmount(value)}%`;

// dd/mm of an ML promotion date; naive values are UTC (parsePromoInstant), shown in the operator's time zone.
function shortDate(value) {
  const ms = parsePromoInstant(value);
  if (ms == null) return null;
  const date = new Date(ms);
  return `${String(date.getDate()).padStart(2, '0')}/${String(date.getMonth() + 1).padStart(2, '0')}`;
}

export function dateRange(promo) {
  const start = shortDate(promo?.start_date);
  const finish = shortDate(promo?.finish_date);
  if (start && finish) return [`${start} –`, finish];
  if (finish) return [`hasta ${finish}`];
  if (start) return [`desde ${start}`];
  return ['Sin fecha'];
}

export function shares(promo) {
  const seller = promo?.payload?.seller_percentage;
  const meli = promo?.payload?.meli_percentage;
  if (seller == null && meli == null) return ['—'];
  return [`${seller != null ? pct(seller) : '—'} /`, meli != null ? pct(meli) : '—'];
}

/** Markup delta of a candidate vs the applied promo (or the sale price), on the basis `comparableMarkups` picks. */
export function markupDelta(promo, statusQuo) {
  const [candidate, current] = comparableMarkups(promo, statusQuo);
  if (candidate == null || current == null) return null;
  const delta = candidate - current;
  return `${delta >= 0 ? '+' : '−'}${formatAmount(Math.abs(delta))} pp`;
}

export function markupTone(value) {
  return value != null && Number(value) < 0 ? styles.mejoresMarkupNegative : styles.mejoresMarkupPositive;
}

/**
 * An apply went through cleanly: sent or confirmed, and (for an ML-priced offer) ML applied the
 * price the operator confirmed. Anything else keeps the pub open so its feedback stays visible.
 */
export function appliedCleanly(promo, data) {
  if (data?.status === 'reconciled_applied') return true;
  if (data?.status !== 'submitted') return false;
  return !ML_PRICED_TYPES.has(promo.promotion_type) || data.precio_difiere === false;
}
