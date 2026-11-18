// Control characters (C0 + DEL) never belong in an app path.
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;

/**
 * The path the login may send the user back to, or null when it is not safe.
 *
 * Accepts a string or a react-router location (`{ pathname, search, hash }`).
 * Only a relative app path qualifies: it starts with a single `/`, has no `//`
 * prefix, no backslash (browsers treat `/\host` like `//host`) and no control
 * characters. Anything else (absolute URLs, `javascript:`, empty) is null, so
 * the caller falls back to `/`.
 */
export function safeReturnPath(from) {
  let path = from;
  if (from && typeof from === 'object') {
    if (typeof from.pathname !== 'string') return null;
    path = `${from.pathname}${from.search || ''}${from.hash || ''}`;
  }
  if (typeof path !== 'string' || path === '') return null;
  if (!path.startsWith('/') || path.startsWith('//')) return null;
  if (path.includes('\\') || CONTROL_CHARS.test(path)) return null;
  return path;
}
