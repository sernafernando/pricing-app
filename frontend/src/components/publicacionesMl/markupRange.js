import { formatPct } from '../../utils/metricasMlFormat';

/**
 * "12,0% – 18,0%" for a range, "15,0%" when every variation agrees. The figures
 * are the server's (P6); a null range is "—" with the reason as tooltip, never
 * 0. A real 0% stays "0,0%".
 */
export function formatMarkupRange(min, max) {
  return min === max ? formatPct(min) : `${formatPct(min)} – ${formatPct(max)}`;
}

/** The tooltip of "(parcial)": how many variations without a cost the range leaves out. */
export const partialRangeTitle = (partial) =>
  `${partial} ${partial === 1 ? 'variación sin costo no entra' : 'variaciones sin costo no entran'} en el rango`;
