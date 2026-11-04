/**
 * `GET /ml-ads/display` as the backend answers it, built from REAL captures of advertiser 25713:
 *  - each campaign's catalog (name, goal, status, dates) is the captured `display/campaigns` list;
 *  - each campaign's figures are its captured 07/09-06/10/2026 summary (cost, prints, clicks, reach,
 *    event_time sales and units); the three paused campaigns had no activity;
 *  - the daily series is the one captured day (2026-10-05, the four active campaigns' cost), and each campaign's
 *    `days` is its own captured 2026-10-05 row (cost and event_time direct_amount); the paused ones had none.
 * Ratios and totals are computed with the backend's own formulas (ML's `ctr` is 0.0 even with clicks).
 */
const ratios = (f) => ({
  ...f,
  ctr: f.prints ? f.clicks / f.prints : null,
  cpc: f.clicks ? f.cost / f.clicks : null,
  cpm: f.prints ? (f.cost * 1000) / f.prints : null,
  roas: f.cost ? f.attributed_amount / f.cost : null,
});

const DAY = '2026-10-05';
const day = (cost, attributed_amount) => [{ day: DAY, cost, attributed_amount }];

const campaign = (campaign_id, name, goal, status, start_date, end_date, figures, days = []) =>
  ratios({
    advertiser_id: 25713,
    campaign_id,
    name,
    type: 'PROGRAMMATIC',
    goal,
    status,
    start_date,
    end_date,
    cost: 0,
    prints: 0,
    clicks: 0,
    reach: 0,
    attributed_amount: 0,
    attributed_units: 0,
    ...figures,
    days,
  });

export const DISPLAY_CAMPAIGNS = [
  campaign(259859, 'DisplayCatalogo', 'conversion', 'active', '2026-05-05', '2026-11-05', {
    cost: 1424818.12,
    prints: 958657,
    clicks: 1524,
    reach: 332354,
    attributed_amount: 77131574.24,
    attributed_units: 581,
  }, day(45179.15, 1650176.05)),
  campaign(301232, 'Tp-link-asus-lenovo', 'conversion', 'active', '2026-07-15', '2026-11-05', {
    cost: 1385503.51,
    prints: 1068221,
    clicks: 1098,
    reach: 177017,
    attributed_amount: 50351579.36,
    attributed_units: 295,
  }, day(49464.21, 86030)),
  campaign(294806, 'Tp-link-PVP', 'conversion', 'active', '2026-07-02', '2026-10-04', {
    cost: 897381.54,
    prints: 445714,
    clicks: 610,
    reach: 99319,
    attributed_amount: 49995319.15,
    attributed_units: 470,
  }, day(68.67, 2005642)),
  campaign(335306, 'XeroxB110', 'conversion', 'active', '2026-09-07', '2026-11-01', {
    cost: 748449.6,
    prints: 467762,
    clicks: 523,
    reach: 69598,
    attributed_amount: 16874875.25,
    attributed_units: 115,
  }, day(27226.79, 1658026.88)),
  campaign(340339, 'B110creativa', 'conversion', 'paused', '2026-09-11', '2026-09-30', {}),
  campaign(290925, 'prueba', 'conversion', 'paused', '2026-07-01', '2026-07-31', {}),
  campaign(281280, 'DisplayCatalogo-Consideracion', 'consideration', 'paused', '2026-06-04', '2026-08-01', {}),
];

const sum = (key) => DISPLAY_CAMPAIGNS.reduce((total, c) => total + c[key], 0);

export const DISPLAY_REPORT = {
  coverage: { data_through: '2026-10-06', missing_days: [], mismatch_days: [] },
  totals: ratios({
    cost: sum('cost'),
    prints: sum('prints'),
    clicks: sum('clicks'),
    reach: sum('reach'),
    attributed_amount: sum('attributed_amount'),
    attributed_units: sum('attributed_units'),
  }),
  campaigns: DISPLAY_CAMPAIGNS,
  daily: [{ day: DAY, cost: 121938.82 }],
};
