import { ExternalLink, FileSpreadsheet, Info, X } from 'lucide-react';
import styles from './SheetsNotice.module.css';

/**
 * What "Exportar a Sheets" leaves on screen that is not an error: `{ url }` of the sheet it created (a success banner
 * with a link to it, shown even when its tab opened: a browser can block that tab silently), or `{ text }` of a quiet
 * note such as a cancelled Google popup. `onClose` dismisses it.
 */
export default function SheetsNotice({ notice, onClose }) {
  if (!notice) return null;
  const created = Boolean(notice.url);
  return (
    <div className={created ? styles.success : styles.note} role="status">
      {created ? (
        <FileSpreadsheet size={18} className={styles.icon} aria-hidden="true" />
      ) : (
        <Info size={18} className={styles.icon} aria-hidden="true" />
      )}
      <div className={styles.body}>
        {created ? (
          <>
            <span className={styles.title}>Hoja creada en Google Sheets</span>
            <span className={styles.detail}>Quedó guardada en Mi unidad.</span>
          </>
        ) : (
          <span className={styles.detail}>{notice.text}</span>
        )}
      </div>
      {created && (
        <a className={styles.open} href={notice.url} target="_blank" rel="noopener noreferrer">
          Abrir en Google Sheets
          <ExternalLink size={14} aria-hidden="true" />
        </a>
      )}
      <button type="button" className={styles.close} onClick={onClose} aria-label="Cerrar aviso">
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}
