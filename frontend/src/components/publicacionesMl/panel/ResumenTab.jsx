import PublicationStatusPill from '../PublicationStatusPill';
import styles from './panel.module.css';

/** Resumen: everything the publication is. */
export default function ResumenTab({ detail }) {
  const { row } = detail;
  return (
    <dl className={styles.fields}>
      <dt>Estado</dt>
      <dd>
        <PublicationStatusPill status={row.status} gone={row.gone} subStatus={detail.subStatus} />
      </dd>
    </dl>
  );
}
