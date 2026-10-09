import { describeLoadError } from '../loadErrors';
import { amount } from './format';

/** `null` on a side that does not exist (a field that was added or removed) is the dash. */
export const EMPTY_VALUE = '—';

/**
 * One stored JSON value as text: money as the list writes it (when `money`),
 * strings and counts as they are, a list joined, anything else as JSON. The
 * values are the store's, not an invention: nothing is converted or guessed.
 */
export function formatFeedValue(value, { money = false } = {}) {
  if (value === null || value === undefined || value === '') return EMPTY_VALUE;
  if (money && typeof value === 'number') return amount(value);
  if (Array.isArray(value)) return value.length === 0 ? EMPTY_VALUE : value.map((entry) => formatFeedValue(entry)).join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'boolean') return value ? 'Sí' : 'No';
  return String(value);
}

/** What to tell the operator when a feed (events, history) cannot be loaded. */
export const describeFeedError = (error, { forbidden, fallback }) =>
  describeLoadError(error, { notFound: 'La publicación ya no existe.', forbidden, fallback });
