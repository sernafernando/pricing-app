/** Dates of the Aportes page: plain days as the API sends them, and backend timestamps on the Argentine calendar. */
const AR_STAMP = new Intl.DateTimeFormat('en-US', {
  day: 'numeric',
  month: 'numeric',
  year: 'numeric',
  hour: 'numeric',
  minute: 'numeric',
  hourCycle: 'h23',
  timeZone: 'America/Argentina/Buenos_Aires',
});

/** "2026-10-16" -> "16/10". */
export const dayMonth = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

/** A backend timestamp's Argentine parts; one without an offset is UTC, as the backend stores it. */
function stampParts(iso) {
  const parts = AR_STAMP.formatToParts(new Date(/(Z|[+-]\d\d:\d\d)$/.test(iso) ? iso : `${iso}Z`));
  const part = (type) => parts.find((p) => p.type === type).value.padStart(2, '0');
  return { day: part('day'), month: part('month'), year: part('year'), hour: part('hour'), minute: part('minute') };
}

/** "16/10": the Argentine day of a backend timestamp. */
export function stampDay(iso) {
  const p = stampParts(iso);
  return `${p.day}/${p.month}`;
}

/** "16/10/2026 15:20": the Argentine day and time of a backend timestamp. */
export function stampDateTime(iso) {
  const p = stampParts(iso);
  return `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute}`;
}
