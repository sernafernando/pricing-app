/**
 * Catalog helpers shared by C2 (status-quo win / rival price).
 * C6 monopoly UI/engine lives in a later PR — not in this ship.
 */

/** Mirror of backend `CATALOG_SNAPSHOT_MAX_AGE_SECONDS` (24h). */
export const CATALOG_SNAPSHOT_MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * True when the catalog API payload is usable for C2 (fetch ok + within max age).
 * Missing ``fecha_consulta`` on an ok payload → treated as fresh (legacy).
 */
export function catalogSnapshotIsFresh(snapshot, { now = Date.now() } = {}) {
  if (!snapshot || snapshot.fetch_status !== 'ok') return false;
  const raw = snapshot.fecha_consulta;
  if (raw == null || raw === '') return true;
  const ms = Date.parse(raw);
  if (!Number.isFinite(ms)) return false;
  return now - ms <= CATALOG_SNAPSHOT_MAX_AGE_MS;
}

export function minRivalPriceArs(sameBucket, ourMla, sellersExcluidos = []) {
  const excluded = new Set((sellersExcluidos || []).map(String));
  const prices = [];
  for (const row of sameBucket || []) {
    const id = row?.item_id != null ? String(row.item_id) : '';
    const sellerId = row?.seller_id != null ? String(row.seller_id) : '';
    if (!id || id === ourMla) continue;
    if ((sellerId && excluded.has(sellerId)) || (id && excluded.has(id))) continue;
    const price = row.price_ars ?? row.price;
    if (price == null || Number.isNaN(Number(price))) continue;
    prices.push(Number(price));
  }
  return prices.length ? Math.min(...prices) : null;
}
