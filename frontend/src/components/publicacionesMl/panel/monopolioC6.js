/**
 * Client mirror of backend `monopolio_c6_oportunidad` / effective ranking.
 * Checked rivals = same_bucket minus sellers_excluidos (our MLA always counts).
 */

/** Mirror of backend `CATALOG_SNAPSHOT_MAX_AGE_SECONDS` (24h). */
export const CATALOG_SNAPSHOT_MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * True when the catalog API payload is usable for C2/C6 (fetch ok + within max age).
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

export function ourPriceArs(sameBucket, ourMla) {
  for (const row of sameBucket || []) {
    if (String(row?.item_id) !== String(ourMla)) continue;
    const price = row.price_ars ?? row.price;
    if (price == null || Number.isNaN(Number(price))) return null;
    return Number(price);
  }
  return null;
}

export function computeMonopolioC6({
  c6Activo,
  ourPrice,
  segundoPrecio,
  gapMin = 5000,
  distanciaObjetivo = 100,
}) {
  if (!c6Activo) return null;
  if (ourPrice == null || segundoPrecio == null) return null;
  if (ourPrice >= segundoPrecio) return null;
  const gap = segundoPrecio - ourPrice;
  if (gap < Number(gapMin)) return null;
  const distancia = Number(distanciaObjetivo) || 0;
  return {
    our_price: ourPrice,
    segundo_precio: segundoPrecio,
    gap,
    precio_objetivo: segundoPrecio - distancia,
    distancia_objetivo: distancia,
  };
}

export function monopolioFromSnapshotAndCriterios(mla, snapshot, criterios, { salePrice = null } = {}) {
  if (!criterios?.c6_activo) return null;
  if (!catalogSnapshotIsFresh(snapshot)) return null;
  const sameBucket = snapshot?.same_bucket || [];
  // Prefer live sale price (backend baseline); snapshot price is fallback only.
  const our =
    salePrice != null && Number.isFinite(Number(salePrice))
      ? Number(salePrice)
      : ourPriceArs(sameBucket, mla) ?? (snapshot?.our_price != null ? Number(snapshot.our_price) : null);
  const segundo = minRivalPriceArs(sameBucket, mla, criterios.sellers_excluidos || []);
  const out = computeMonopolioC6({
    c6Activo: true,
    ourPrice: our,
    segundoPrecio: segundo,
    gapMin: criterios.c6_gap_min ?? 5000,
    distanciaObjetivo: criterios.c6_distancia_objetivo ?? 100,
  });
  if (!out) return null;
  return {
    ...out,
    solo_via_promo: Boolean(criterios.c6_solo_via_promo),
  };
}
