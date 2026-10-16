/**
 * The `kpis.ads` block of `GET /ml-metricas/board` (backend `KpiAds`), as the
 * ads UI tests share it. The shape mirrors `kpi_strip.KpiAds`; the figures are
 * the owner's mock numbers.
 */
export const ADS_KPIS = {
  cost_total: 17516239.51,
  cost_api: 21195649.8,
  impressions: 4812340,
  clicks: 96247,
  direct_amount: 121400000,
  indirect_amount: 37555926,
  direct_units: 1210,
  indirect_units: 402,
  organic_units: 3200,
  organic_amount: 253362474,
  acos_pct: 11,
  roas: 9.07,
  tacos_pct: 4.25,
  cpc: 182,
  ctr_pct: 2,
  requested: 'mla',
  applied: 'mla',
  subtracted_total: 17516239.51,
  coverage: { available: true, data_through: '2026-10-13', missing_days: [], mismatch_days: [] },
  unattributed: null,
};
