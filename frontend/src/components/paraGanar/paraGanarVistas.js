/** PARA GANAR URL subviews (`?vista=`). */

export const VISTA_ADVISOR = 'advisor';
export const VISTA_CRITERIOS = 'criterios';
export const VISTA_PERIODICIDAD = 'periodicidad';

const KNOWN = new Set([VISTA_ADVISOR, VISTA_CRITERIOS, VISTA_PERIODICIDAD]);

/** Normalize query `vista` — unknown / empty → advisor. */
export function parseVista(raw) {
  if (raw && KNOWN.has(raw) && raw !== VISTA_ADVISOR) return raw;
  return VISTA_ADVISOR;
}
