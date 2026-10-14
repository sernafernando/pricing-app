import StatusPill from '../kit/StatusPill';
import { publicationStatusInfo, subStatusTitle } from './publicationStatus';
import styles from './cells.module.css';

/** `gone` (vanished from ML) wins over the last known status. */
export default function PublicationStatusPill({ status, gone = false, subStatus }) {
  if (gone) return <StatusPill tone="danger">Eliminada</StatusPill>;
  const info = publicationStatusInfo(status);
  if (!info) return <span className={styles.empty}>—</span>;
  return (
    <StatusPill tone={info.tone} title={subStatusTitle(subStatus)}>
      {info.label}
    </StatusPill>
  );
}
