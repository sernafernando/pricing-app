import { formatPct } from '../../utils/metricasMlFormat';

/**
 * "12,0% – 18,0%" for a range, "15,0%" when every variation agrees. The figures
 * are the server's (P6); a null range is "—" with the reason as tooltip, never
 * 0. A real 0% stays "0,0%".
 */
export function formatMarkupRange(min, max) {
  return min === max ? formatPct(min) : `${formatPct(min)} – ${formatPct(max)}`;
}
