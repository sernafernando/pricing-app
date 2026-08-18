import { pxqAPI } from '../services/api';
import { useLazyResource } from './useLazyResource';

/**
 * Fetches the per-tier markup for a PxQ publication (`GET /pxq/{item_id}/markup`,
 * slice A1 of `pxq-markup-antes-de-publicar`) and indexes the response by
 * `tier_id` so the panel can look up a mirror tier's markup in O(1) while
 * rendering its rows.
 *
 * Gated the same way `PxqPanel` gates its own `getLive` fetcher: `canRead` is
 * checked INSIDE the fetcher, not via an early return in the caller --
 * `useLazyResource`'s effect fires unconditionally on mount, so an early
 * return after the hook call would still let the fetch race the permission
 * check.
 *
 * Takes its OWN `cacheRef`, separate from the one `PxqPanel` passes to its
 * `getLive` fetch: this is a second, independent resource for the same
 * `itemId` (no shared shape with the live/mirror payload), so caching it
 * under one shared key space would collide with `getLive`'s entry.
 *
 * @param {import('react').MutableRefObject<Map>} cacheRef
 * @param {string} itemId
 * @param {boolean} canRead
 * @returns {{ data: Map<number, object>|null, loading: boolean, error: any, reload: () => void }}
 */
export function usePxqMarkup(cacheRef, itemId, canRead) {
  const fetcher = (id) => (canRead ? pxqAPI.getMarkup(id).then((r) => indexByTierId(r.data)) : Promise.resolve(null));
  return useLazyResource(cacheRef, itemId, fetcher);
}

// Never returns null for an empty/missing `tiers` array -- an empty Map means
// "no tiers to report on", which is a different fact from "the fetch never
// ran" (`data === null`, the `canRead === false` case above).
function indexByTierId(payload) {
  const byTierId = new Map();
  for (const tier of payload?.tiers ?? []) {
    byTierId.set(tier.tier_id, tier);
  }
  return byTierId;
}

export default usePxqMarkup;
