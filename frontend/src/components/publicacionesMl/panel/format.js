import { formatAmount, formatDateTime } from '../../../utils/ventasMlFormat';

/** Money as the list writes it; a missing figure stays `null` so `Field` shows the dash. */
export const amount = (value) => (value === null || value === undefined || value === '' ? null : formatAmount(value));

export const date = (value) => (value ? formatDateTime(value) : null);

export const orNull = (value) => (value == null ? null : value);

/** A quantity as text; `null` stays null so `Field` shows the dash and a real 0 stays "0". */
export const count = (value) => (value == null ? null : String(value));

/** A calendar day (`2026-10-05`) as `05/10/2026`, without the time-zone shift a Date would add. */
export const day = (value) => {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? '');
  return match ? `${match[3]}/${match[2]}/${match[1]}` : null;
};

export const yesNo = (value) => (value == null ? null : value ? 'Sí' : 'No');

const pad = (n) => String(n).padStart(2, '0');
const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/** The local calendar day of a moment, as a key for grouping (`2026-10-13`). */
export const dayKey = (value) => {
  const at = new Date(value);
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
};

/** A day heading: "Hoy", "Ayer", or the weekday and the date ("Martes 13/10"). */
export function dayHeading(value, now = new Date()) {
  const at = new Date(value);
  if (sameDay(at, now)) return 'Hoy';
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (sameDay(at, yesterday)) return 'Ayer';
  const weekday = at.toLocaleDateString('es-AR', { weekday: 'long' });
  return `${weekday.charAt(0).toUpperCase()}${weekday.slice(1)} ${pad(at.getDate())}/${pad(at.getMonth() + 1)}`;
}

/** The local time of day, `03:11`. */
export const timeOfDay = (value) => {
  const at = new Date(value);
  return `${pad(at.getHours())}:${pad(at.getMinutes())}`;
};
