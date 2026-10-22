import styles from './OffsetMigradoBadge.module.css';

/**
 * Marks a legacy offset that was migrated to a sell-out campaign (T15/T16). The offset keeps feeding today's
 * figures, but editing it does not change its campaign. Renders nothing when `campanaId` is empty.
 */
export default function OffsetMigradoBadge({ campanaId }) {
  if (!campanaId) return null;
  return (
    <span
      className={styles.badge}
      title="Este offset ya tiene su campaña de sell-out. Los cambios que hagas acá no se pasan a la campaña."
    >
      Migrado a campaña #{campanaId}
    </span>
  );
}
