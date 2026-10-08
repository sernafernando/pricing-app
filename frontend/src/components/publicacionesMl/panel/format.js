import { formatAmount, formatDateTime } from '../../../utils/ventasMlFormat';

/** Money as the list writes it; a missing figure stays `null` so `Field` shows the dash. */
export const amount = (value) => (value === null || value === undefined || value === '' ? null : formatAmount(value));

export const date = (value) => (value ? formatDateTime(value) : null);

export const orNull = (value) => (value == null ? null : value);
