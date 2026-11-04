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
  // The "Publicidad restada" card lines (backend `KpiAdsWaterfall`): only Product Ads of publications here.
  waterfall: {
    product_ads_publications: 17516239.51,
    product_ads_sin_producto: null,
    product_ads_contribution: 0,
    product_ads_net: 17516239.51,
    no_campaign: 0,
    display_gross: null,
    display_contribution: null,
    display_net: null,
    brand: null,
    account_subtracted: false,
    total: 17516239.51,
  },
};

/**
 * DERIVED (not an API capture): "Restar toda" unfiltered with aportes on both channels, built so the lines add up
 * the way the API computes them: 17.516.239,51 + 412.380 - 1.265.000 = 16.663.619,51 Product Ads neto;
 * + 1.550.000 Display - 300.000 aporte + 380.500 Brand Ads = 18.294.119,51.
 */
export const ADS_WATERFALL_TODO = {
  product_ads_publications: 17516239.51,
  product_ads_sin_producto: 412380,
  product_ads_contribution: 1265000,
  product_ads_net: 16663619.51,
  no_campaign: 84300,
  display_gross: 1550000,
  display_contribution: 300000,
  display_net: 1250000,
  brand: 380500,
  account_subtracted: true,
  total: 18294119.51,
};
