import { AlertTriangle, XCircle } from 'lucide-react';
import styles from './AlertIcon.module.css';

/**
 * AlertIcon — ventas-ml-rediseno PR14.T5 (LISTING R29, design D13).
 *
 * Renders `SaleListItem.alert_level`, the SINGLE server-derived alert the
 * backend's `_alert_level` already computes — verified live: the value is
 * `"error" | "warning" | "ok"`, never `"danger"`. This component replaces
 * every ad-hoc per-field FE flag the old table used to derive on its own.
 *
 * `ok` renders nothing: a row with nothing wrong gets no icon.
 */
export default function AlertIcon({ level, reason }) {
  if (level === 'error') {
    return (
      <XCircle
        size={16}
        className={styles.error}
        data-alert-level="error"
        role="img"
        aria-label="Alerta"
        title={reason}
      />
    );
  }

  if (level === 'warning') {
    return (
      <AlertTriangle
        size={16}
        className={styles.warning}
        data-alert-level="warning"
        role="img"
        aria-label="Advertencia"
        title={reason}
      />
    );
  }

  return null;
}
