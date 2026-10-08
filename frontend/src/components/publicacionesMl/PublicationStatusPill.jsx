import StatusPill from '../kit/StatusPill';
import styles from './cells.module.css';

const STATUSES = {
  active: { label: 'Activa', tone: 'success' },
  paused: { label: 'Pausada', tone: 'warning' },
  closed: { label: 'Cerrada', tone: 'danger' },
  under_review: { label: 'En revisión', tone: 'info' },
  inactive: { label: 'Inactiva', tone: 'neutral' },
};

/** `gone` (vanished from ML) wins over the last known status. */
export default function PublicationStatusPill({ status, gone = false, subStatus = [] }) {
  if (gone) return <StatusPill tone="danger">Eliminada</StatusPill>;
  const known = STATUSES[status];
  if (!known) return status ? <StatusPill tone="neutral">{status}</StatusPill> : <span className={styles.empty}>—</span>;
  const title = subStatus.length > 0 ? subStatus.join(', ') : undefined;
  return (
    <StatusPill tone={known.tone} title={title}>
      {known.label}
    </StatusPill>
  );
}
