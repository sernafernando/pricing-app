/**
 * ventas-ml-kpi-strip T5: the ONE place that turns this screen's filter
 * state into request params. `GET /ml-ventas-ops/sales` (the list) and
 * `GET /ml-ventas-ops/sales/kpis` (the totals strip) accept EXACTLY the
 * same filter+toggle params (task doc, "Contrato del endpoint"). If each
 * caller built its own params object they could drift — a filter that
 * reaches the list but not the KPI strip (or vice versa) breaks the
 * "lo que veo es lo que suma" promise this feature exists to restore.
 *
 * `limit`/`offset` are NOT included here: the KPI endpoint does not accept
 * them (KPI R8, it aggregates the whole filtered set), so the list caller
 * adds them itself on top of this shared object.
 */
export function buildVentasMLFilterParams({
  operationStatusFilter,
  goodsStatusFilter,
  fechaDesde,
  fechaHasta,
  searchQuery,
  productFilters,
  includeUnknown,
  includeInDispute,
  includeMixed,
  includeProvisional,
  // ON (cancelled sales included) unless a caller says otherwise, so a
  // caller that predates the switch never hides cancelled sales by accident.
  includeCancelled = true,
}) {
  const params = {};
  if (operationStatusFilter) params.operation_status = operationStatusFilter;
  if (goodsStatusFilter) params.goods_status = goodsStatusFilter;
  if (fechaDesde) params.date_from = fechaDesde;
  if (fechaHasta) params.date_to = fechaHasta;
  if (searchQuery) params.q = searchQuery;
  if (productFilters?.marcas?.length > 0) params.marcas = productFilters.marcas.join(',');
  if (productFilters?.subcategorias?.length > 0) params.subcategorias = productFilters.subcategorias.join(',');
  if (productFilters?.pms?.length > 0) params.pms = productFilters.pms.join(',');
  // The five toggles are ALWAYS sent explicitly (never omitted), even when
  // `true` — the backend's own per-endpoint defaults disagree with each
  // other (KPI R11 vs the list's legacy `True` default), which is exactly
  // the parity bug this feature fixes. Sending the frontend's own state
  // explicitly is what keeps both endpoints in lockstep regardless of
  // their individual defaults.
  params.include_unknown = Boolean(includeUnknown);
  params.include_in_dispute = Boolean(includeInDispute);
  params.include_mixed = Boolean(includeMixed);
  params.include_provisional = Boolean(includeProvisional);
  params.include_cancelled = Boolean(includeCancelled);
  return params;
}
