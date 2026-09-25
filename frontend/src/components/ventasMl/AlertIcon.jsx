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
      // PR14 review fix P3: a `title` ATTRIBUTE on an `<svg>` renders no
      // native browser tooltip — only a real (non-svg) host element does.
      // The wrapper carries the hoverable title; the svg stays the visual
      // icon.
      <span className={styles.iconWrapper} title={reason}>
        <XCircle size={16} className={styles.error} data-alert-level="error" role="img" aria-label="Alerta" />
      </span>
    );
  }

  if (level === 'warning') {
    return (
      <span className={styles.iconWrapper} title={reason}>
        <AlertTriangle
          size={16}
          className={styles.warning}
          data-alert-level="warning"
          role="img"
          aria-label="Advertencia"
        />
      </span>
    );
  }

  return null;
}
