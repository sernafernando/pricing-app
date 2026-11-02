/**
 * When each MLA's promotions were last pulled successfully from ML in this browser tab, by the Publicaciones ML
 * Promos tab or the Productos refresh button (the Productos tree's pull on expand does not mark it: at worst one
 * extra pull). The Publicaciones ML panel opens on Promos (owner, 2026-11-02), and every pull goes through a
 * throttle shared with sales-webhook processing: clicking through rows must not cost a pull per click. Module
 * scope on purpose: the tab remounts per MLA (`key={itemId}`), and component state would forget every pull.
 *
 * Only a successful pull starts the TTL (a failed or abandoned one retries on the next open); a write
 * (apply/remove) forgets the MLA; the manual refresh button always pulls, and its success restarts the TTL.
 * The "no promotions" confirmation for an empty mirror is also a live ML call, so ML's YES gets the same TTL
 * (an unconfirmed or failed answer asks again on the next open).
 */
const PROMO_PULL_TTL_MS = 5 * 60 * 1000;

const pulledAt = new Map();
const confirmedEmptyAt = new Map();

const isRecent = (at) => at != null && Date.now() - at < PROMO_PULL_TTL_MS;

export const markPromoPulled = (mla) => {
  pulledAt.set(mla, Date.now());
};

export const promoPulledRecently = (mla) => isRecent(pulledAt.get(mla));

export const markPromoEmptyConfirmed = (mla) => {
  confirmedEmptyAt.set(mla, Date.now());
};

export const promoEmptyConfirmedRecently = (mla) => isRecent(confirmedEmptyAt.get(mla));

export const forgetPromoPull = (mla) => {
  pulledAt.delete(mla);
  confirmedEmptyAt.delete(mla);
};

/** Tests only: start from no MLA pulled. */
export const resetPromoPulls = () => {
  pulledAt.clear();
  confirmedEmptyAt.clear();
};
