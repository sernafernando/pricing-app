import { parKey } from '../components/parKey';

/**
 * Tiny pure helpers extracted from `MisSubPMs.jsx` so their branches can be
 * unit tested directly, independent of whether the current UI can actually
 * reach them. Kept out of the page component file: exporting a plain
 * function alongside a default component export trips
 * `react-refresh/only-export-components` (same reasoning as
 * `components/parKey.js`).
 */

/**
 * Builds the post-save `baseline` (and, identically, what `checked` should
 * become) from the payload that was ACTUALLY sent to the bulk PUT — never
 * from the pre-filter `checked` snapshot. A checked key with no matching
 * pair (a stale/ghost grant — see `guardar()`'s omission handling) is
 * dropped from `paresDeseados` before it ever reaches this function, so it
 * is never sent AND never recorded as if the server had accepted it.
 * Recording it anyway would make `baseline` lie: `dirty` would read false
 * for a pair the server never received, and the ghost key would sit in the
 * baseline (and `checked`, implying "granted") forever, poisoning every
 * later diff computed against it.
 */
export function clavesDesdePayload(paresDeseados) {
  return new Set(paresDeseados.map((p) => parKey(p.marca, p.categoria)));
}
