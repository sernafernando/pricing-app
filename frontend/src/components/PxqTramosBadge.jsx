import { Layers } from 'lucide-react';
import styles from './PxqTramosBadge.module.css';

/**
 * Compact pill showing a product's wholesale (PxQ) tiers at a glance, so the
 * listing answers "does this have wholesale prices, and from how much?"
 * without opening anything.
 *
 * Render logic:
 *   - no tiers (null/0)          → renders nothing
 *   - tiers + cheapest amount    → "3 tramos · desde $37.800"
 *   - tiers but no amount        → "3 tramos" ALONE. The price half is never
 *     guessed: the tier data is read cross-DB and fails open, and a made-up
 *     "desde" is a money figure someone would act on.
 *
 * @param {{ tramos: number | null | undefined, precioDesde: number | null | undefined }} props
 */
export default function PxqTramosBadge({ tramos, precioDesde }) {
  if (!tramos) return null;

  const label = `${tramos} tramo${tramos === 1 ? '' : 's'}`;
  const desde =
    typeof precioDesde === 'number' && Number.isFinite(precioDesde)
      ? `desde $${precioDesde.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`
      : null;

  const texto = desde ? `${label} · ${desde}` : label;
  const tooltip = `Precios mayoristas (PxQ) — ${texto}`;

  return (
    <span className={styles.badge} title={tooltip} aria-label={tooltip}>
      <Layers size={11} aria-hidden />
      <span className={styles.label}>{texto}</span>
    </span>
  );
}
