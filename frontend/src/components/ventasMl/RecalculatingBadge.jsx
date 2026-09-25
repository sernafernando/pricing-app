import { Loader2, AlertTriangle, MinusCircle } from 'lucide-react';
import styles from './RecalculatingBadge.module.css';

/**
 * RecalculatingBadge — ventas-ml-rediseno PR14.T9/T10 (SM R3/R9 FE side).
 *
 * `metrics_state` on `SaleListItem` (PR10.T8, `metrics_state_for_orders`)
 * is one of `ok`, `recalculating`, `failed`, `pending`. The caller (a
 * money cell) is responsible for NOT rendering the stored `neto`/
 * `total_gauss` number when this component says a row is not `ok` --
 * this component only owns which distinct message to show:
 *
 *  - `recalculating`: a stored value existed before but is being redone;
 *    showing it now would be a STALE number presented as current.
 *  - `failed`: the same amount to the eye, but nothing retries it -- a
 *    permanent "calculando..." would be a lie that never resolves.
 *  - `pending`: no stored row exists yet, nothing to be stale about.
 *  - `ok` or an unrecognised value: render nothing, so the caller falls
 *    back to the real number.
 */
export default function RecalculatingBadge({ state }) {
  if (state === 'recalculating') {
    return (
      <span className={styles.badge} data-state="recalculating" role="status">
        <Loader2 size={12} className={styles.spin} aria-hidden="true" />
        Recalculando…
      </span>
    );
  }

  if (state === 'failed') {
    return (
      <span
        className={`${styles.badge} ${styles.failed}`}
        data-state="failed"
        role="status"
        title="El recálculo de esta venta falló y no se reintenta automáticamente."
      >
        <AlertTriangle size={12} aria-hidden="true" />
        No se pudo calcular
      </span>
    );
  }

  if (state === 'pending') {
    return (
      <span className={`${styles.badge} ${styles.pending}`} data-state="pending" role="status">
        <MinusCircle size={12} aria-hidden="true" />
        Sin calcular aún
      </span>
    );
  }

  return null;
}
