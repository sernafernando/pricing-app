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
 * (an unconfirmed or failed answer asks again on the next open); any successful pull clears it, since the pull
 * re-read what ML has (`MlaPromocionesPanel` does it itself, whatever its host).
 * A pull marks the TTL with the generation it started on (`promoPullGeneration`): a write forgets the MLA and
 * bumps its generation, so a pull that was already in flight settles without marking it.
 */
const PROMO_PULL_TTL_MS = 5 * 60 * 1000;

const pulledAt = new Map();
const confirmedEmptyAt = new Map();
const generation = new Map();

const isRecent = (at) => at != null && Date.now() - at < PROMO_PULL_TTL_MS;

export const promoPullGeneration = (mla) => generation.get(mla) ?? 0;

/** `startedOn`: the generation the pull started on; a write since then means the pull no longer counts. */
export const markPromoPulled = (mla, startedOn = promoPullGeneration(mla)) => {
  if (startedOn !== promoPullGeneration(mla)) return;
  pulledAt.set(mla, Date.now());
  forgetPromoEmptyConfirmed(mla);
};

export const promoPulledRecently = (mla) => isRecent(pulledAt.get(mla));

export const markPromoEmptyConfirmed = (mla) => {
  confirmedEmptyAt.set(mla, Date.now());
};

export const forgetPromoEmptyConfirmed = (mla) => {
  confirmedEmptyAt.delete(mla);
};

export const promoEmptyConfirmedRecently = (mla) => isRecent(confirmedEmptyAt.get(mla));

export const forgetPromoPull = (mla) => {
  pulledAt.delete(mla);
  confirmedEmptyAt.delete(mla);
  generation.set(mla, promoPullGeneration(mla) + 1);
};

/** Tests only: start from no MLA pulled. */
export const resetPromoPulls = () => {
  pulledAt.clear();
  confirmedEmptyAt.clear();
  generation.clear();
};
