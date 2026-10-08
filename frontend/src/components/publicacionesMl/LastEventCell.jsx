import { formatDateTime, timeAgo } from '../../utils/ventasMlFormat';
import { eventLabel } from './eventLabels';
import styles from './cells.module.css';

/** `event` is `last_event` (absent when the publication has none, and for every row while events are off). */
export default function LastEventCell({ event, now }) {
  if (!event?.event_type) return <span className={styles.empty}>—</span>;
  const ago = timeAgo(event.observed_at, now);
  return (
    <div className={styles.stack}>
      <span>{eventLabel(event.event_type)}</span>
      {ago && (
        <span className={styles.when} title={formatDateTime(event.observed_at)}>
          {ago}
        </span>
      )}
    </div>
  );
}
