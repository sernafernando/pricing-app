import { formatDateTime, timeAgo } from '../../utils/ventasMlFormat';
import styles from './cells.module.css';

/** When the publication last moved (`last_activity_at`), relative, with the exact time as a tooltip. */
export default function ActivityCell({ item }) {
  const ago = timeAgo(item.last_activity_at);
  if (!ago) return <span className={styles.empty}>—</span>;
  return (
    <span className={styles.when} title={formatDateTime(item.last_activity_at)}>
      {ago}
    </span>
  );
}
