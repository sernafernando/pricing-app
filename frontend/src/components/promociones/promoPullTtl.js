/**
 * When each MLA's promotions were last pulled from ML in this browser tab. The Publicaciones ML panel opens on
 * Promos (owner, 2026-11-02), and every pull goes through a throttle shared with sales-webhook processing:
 * clicking through rows must not cost a pull per click. Module scope on purpose: the tab remounts per MLA
 * (`key={itemId}`), and component state would forget every pull.
 *
 * Only a successful pull starts the TTL (a failed or abandoned one retries on the next open); a write
 * (apply/remove) forgets the MLA; the manual refresh button always pulls, and its success restarts the TTL.
 */
export const PROMO_PULL_TTL_MS = 5 * 60 * 1000;

const pulledAt = new Map();

export const markPromoPulled = (mla) => {
  pulledAt.set(mla, Date.now());
};

export const promoPulledRecently = (mla) => {
  const at = pulledAt.get(mla);
  return at != null && Date.now() - at < PROMO_PULL_TTL_MS;
};

export const forgetPromoPull = (mla) => {
  pulledAt.delete(mla);
};

/** Tests only: start from no MLA pulled. */
export const resetPromoPulls = () => {
  pulledAt.clear();
};
