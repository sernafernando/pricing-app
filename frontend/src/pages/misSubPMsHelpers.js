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

/**
 * Backend error detail helper (Slice 3's T3.3/T3.4, deferred here). The bulk
 * PUT's 403 sends `detail` as a DICT with `pares_rechazados` (marcas_pm.py
 * :775-781); every other error path on this page still sends `detail` as a
 * plain string. Both shapes must resolve to a real message — never blank.
 */
export function extraerError(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const rechazados = Array.isArray(detail.pares_rechazados) ? detail.pares_rechazados : [];
    const mensaje = detail.mensaje || fallback;
    return { texto: mensaje, rechazados };
  }
  if (typeof detail === 'string' && detail) return { texto: detail, rechazados: [] };
  return { texto: fallback, rechazados: [] };
}
