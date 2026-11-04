/**
 * Display tab helpers (ML Ads): dates of a range, the short money of the stacked chart, and each campaign's cost per
 * day of the range.
 */

// The API accepts at most 366 calendar days, both ends included (`MAX_DAYS` in routers/ml_ads.py).
const MAX_DAYS = 366;

export const isoDay = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

export const formatDate = (iso) => {
  if (!iso) return '—';
  const [year, month, day] = iso.split('-');
  return `${day}/${month}/${year}`;
};

/** Every day of the range, ISO, both ends included. */
export function daysOf(from, to) {
  const days = [];
  const cursor = new Date(`${from}T12:00:00`);
  const end = new Date(`${to}T12:00:00`);
  while (cursor <= end && days.length < MAX_DAYS) {
    days.push(isoDay(cursor));
    cursor.setDate(cursor.getDate() + 1);
  }
  return days;
}

const DECIMAL = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const WHOLE = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 });

/** "$ 1,42M", "$ 897K", "$ 68": the legend's and the axis' short money. */
export function formatShortMoney(value) {
  const abs = Math.abs(value);
  if (abs >= 1e6) return `$ ${DECIMAL.format(value / 1e6)}M`;
  if (abs >= 1e3) return `$ ${WHOLE.format(value / 1e3)}K`;
  return `$ ${WHOLE.format(value)}`;
}

/** One campaign's cost per day of the range, for the kit Sparkline: a covered day without its row is zero, a day
 * never fetched is null (a gap, never drawn as zero spend). */
export function campaignDailyCosts(campaign, daily, range) {
  const covered = new Set(daily.map((d) => d.day));
  const byDay = new Map(campaign.days.map((d) => [d.day, d.cost]));
  return daysOf(range.from, range.to).map((day) => (covered.has(day) ? byDay.get(day) || 0 : null));
}
