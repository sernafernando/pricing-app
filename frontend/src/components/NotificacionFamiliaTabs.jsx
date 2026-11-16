import { FAMILIAS_NOTIFICACION, noLeidasDeFamilia } from '../utils/notificacionFamilias';
import styles from './NotificacionFamiliaTabs.module.css';

export default function NotificacionFamiliaTabs({ familia, onChange, stats, compact = false }) {
  return (
    <div
      role="tablist"
      aria-label="Familias de notificaciones"
      className={`${styles.tabs} ${compact ? styles.compact : ''}`}
    >
      {FAMILIAS_NOTIFICACION.map(({ key, label }) => {
        const activa = familia === key;
        const noLeidas = noLeidasDeFamilia(stats, key);
        return (
          <button
            key={label}
            type="button"
            role="tab"
            aria-selected={activa}
            className={`${styles.tab} ${activa ? styles.active : ''}`}
            onClick={() => onChange(key)}
          >
            {label}
            <span className={`${styles.count} ${noLeidas > 0 ? styles.countUnread : ''}`}>
              {noLeidas}
            </span>
          </button>
        );
      })}
    </div>
  );
}
