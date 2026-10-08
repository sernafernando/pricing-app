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
