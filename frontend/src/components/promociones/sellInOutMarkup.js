export const SELL_IN_OUT_LABEL = 'c/ sell in/out';

export function isSellInOutShown(value) {
  return value !== null && value !== undefined && Number.isFinite(Number(value));
}

export function formatSellInOutPct(value) {
  return `${Number(value).toFixed(1)}%`;
}

/**
 * The text form of the backend's `markup_sell_in_out` next to a promo markup rendered as text
 * (" · c/ sell in/out 12.3%"), or '' when it sent none (promos-markup-sell-in-out).
 */
export function sellInOutText(value, format = formatSellInOutPct) {
  return isSellInOutShown(value) ? ` · ${SELL_IN_OUT_LABEL} ${format(value)}` : '';
}
