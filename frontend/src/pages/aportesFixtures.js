/**
 * `GET /ml-ads/contributions` for October 2026, as the backend test `test_ml_ads_contributions_view.py` builds it.
 * DERIVED (not a capture): the shape is the endpoint's `ContributionsViewOut`; the figures are that test's rows.
 */
const base = {
  advertiser_id: 714700,
  advertiser_name: 'TPLINK',
  note: null,
  settlement: null,
  created_by_id: 1,
  updated_by_id: 1,
  created_at: '2026-10-01T12:00:00+00:00',
  updated_at: '2026-10-01T12:00:00+00:00',
  edited_by: null,
  edited_at: null,
};

export const APORTES_VIEW = {
  contributions: [
    {
      ...base,
      id: 1,
      channel: 'product_ads',
      brand: 'TP-Link',
      campaign_id: 351001,
      campaign_name: 'TP-Link Deco',
      kind: 'percentage',
      value: 20,
      date_from: '2026-10-01',
      date_to: '2026-10-31',
      covered: 60.15,
      loaded_by: 'Lucía Fernández',
      loaded_at: '2026-10-02T10:00:00+00:00',
      edited_by: 'Martín Gómez',
      edited_at: '2026-10-18T16:00:00+00:00',
    },
    {
      ...base,
      id: 3,
      channel: 'display',
      brand: 'Xerox',
      advertiser_id: 25713,
      advertiser_name: 'GAUSS',
      campaign_id: null,
      campaign_name: null,
      kind: 'percentage',
      value: 25,
      date_from: '2026-10-01',
      date_to: '2026-10-31',
      covered: 300,
      loaded_by: 'Lucía Fernández',
      loaded_at: '2026-10-04T11:00:00+00:00',
    },
    {
      ...base,
      id: 2,
      channel: 'product_ads',
      brand: 'Epson',
      campaign_id: 351002,
      campaign_name: 'Epson EcoTank',
      kind: 'fixed_amount',
      value: 150,
      settlement: 'full',
      date_from: '2026-10-10',
      date_to: '2026-10-31',
      covered: 150,
      loaded_by: 'Martín Gómez',
      loaded_at: '2026-10-03T09:30:00+00:00',
    },
  ],
  totals: { product_ads_cost: 795.05, display_cost: 1200, no_campaign_cost: 94.3 },
};

const snapshot = {
  id: 5,
  channel: 'product_ads',
  advertiser_id: 25713,
  campaign_id: 353110945,
  kind: 'fixed_amount',
  value: '120000.00',
  date_from: '2026-10-16',
  date_to: '2026-10-25',
  settlement: 'full',
  brand: 'Logitech',
  note: null,
};

/**
 * `GET /ml-ads/contributions/5/history`, as Stitch 973006a2 shows it: loaded, then the amount and the end date edited.
 * DERIVED (not a capture): the shape is the endpoint's `HistoryOut`; `before`/`after` are the audit snapshots.
 */
export const APORTE_HISTORY = {
  events: [
    { action: 'created', user: 'Martín Gómez', at: '2026-10-16T18:20:00+00:00', before: null, after: snapshot },
    {
      action: 'edited',
      user: 'Martín Gómez',
      at: '2026-10-18T13:05:00+00:00',
      before: snapshot,
      after: { ...snapshot, value: '150000.00', date_to: '2026-10-31' },
    },
  ],
};

/** The row the history above belongs to, as the "Por aporte" view lists it. */
export const HISTORY_ROW = {
  id: 5,
  channel: 'product_ads',
  brand: 'Logitech',
  advertiser_id: 25713,
  advertiser_name: 'GAUSS',
  campaign_id: 353110945,
  campaign_name: 'Logitech MX Master & Periféricos',
};
