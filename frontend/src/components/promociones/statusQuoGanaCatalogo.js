/** True when our_price is strictly below every checked same-bucket rival (same rule as backend C2). */
export function statusQuoGanaCatalogo(competencia, { mla, sellersExcluidos = [] } = {}) {
  if (!competencia || competencia.fetch_status !== 'ok') return false;
  const ourPrice = competencia.our_price;
  if (ourPrice == null || !Number.isFinite(Number(ourPrice))) return false;
  const excluded = new Set((sellersExcluidos || []).map(String));
  const rivals = Array.isArray(competencia.same_bucket) ? competencia.same_bucket : [];
  const prices = [];
  for (const row of rivals) {
    const itemId = row?.item_id != null ? String(row.item_id) : '';
    if (!itemId || itemId === mla || excluded.has(itemId)) continue;
    const price = row?.price_ars ?? row?.price;
    if (price == null || !Number.isFinite(Number(price))) continue;
    prices.push(Number(price));
  }
  if (prices.length === 0) return false;
  return Number(ourPrice) < Math.min(...prices);
}
