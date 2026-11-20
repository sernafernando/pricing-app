import { catalogSnapshotIsFresh } from '../publicacionesMl/panel/catalogSnapshot';

/** True when our_price is strictly below every checked same-bucket rival (same rule as backend C2). */
export function statusQuoGanaCatalogo(competencia, { mla, sellersExcluidos = [] } = {}) {
  if (!catalogSnapshotIsFresh(competencia)) return false;
  const ourPrice = competencia.our_price;
  if (ourPrice == null || !Number.isFinite(Number(ourPrice))) return false;
  const excluded = new Set((sellersExcluidos || []).map(String));
  const rivals = Array.isArray(competencia.same_bucket) ? competencia.same_bucket : [];
  const prices = [];
  for (const row of rivals) {
    const itemId = row?.item_id != null ? String(row.item_id) : '';
    const sellerId = row?.seller_id != null && row.seller_id !== '' ? String(row.seller_id) : '';
    if (!itemId || itemId === mla) continue;
    // Prefer seller_id (ranking checkboxes); legacy JSONB may still hold item_id.
    if (excluded.has(sellerId) || (itemId && excluded.has(itemId))) continue;
    const price = row?.price_ars ?? row?.price;
    if (price == null || !Number.isFinite(Number(price))) continue;
    prices.push(Number(price));
  }
  if (prices.length === 0) return false;
  return Number(ourPrice) < Math.min(...prices);
}
