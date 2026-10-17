import { describeLoadError } from '../loadErrors';

/** `null` on a side that does not exist (a field that was added or removed) is the dash. */
export const EMPTY_VALUE = '—';

/** What to tell the operator when a feed (events, history) cannot be loaded. */
export const describeFeedError = (error, { forbidden, fallback }) =>
  describeLoadError(error, { notFound: 'La publicación ya no existe.', forbidden, fallback });
