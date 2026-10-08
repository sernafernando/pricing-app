import StatusPill from '../kit/StatusPill';
import styles from './cells.module.css';

const LINK_STATES = {
  auto: { label: 'Automático', tone: 'success' },
  manual: { label: 'Manual', tone: 'info' },
  sin_producto: { label: 'Sin producto', tone: 'warning' },
  conflicto: { label: 'Conflicto', tone: 'danger' },
  no_evaluado: { label: 'Sin evaluar', tone: 'neutral' },
};

export default function LinkBadge({ link }) {
  const known = LINK_STATES[link?.state];
  if (!known) return <span className={styles.empty}>—</span>;
  return (
    <div className={styles.stack}>
      <StatusPill tone={known.tone} title={link.descripcion ?? undefined}>
        {known.label}
      </StatusPill>
      {link.codigo && <span className={styles.code}>{link.codigo}</span>}
    </div>
  );
}
