import { CheckCircle, AlertCircle, Info, X } from 'lucide-react';
import styles from './Toast.module.css';

const ICONS = {
  success: CheckCircle,
  error: AlertCircle,
  info: Info,
};

/**
 * Reusable toast notification component.
 *
 * @param {{ toast: { message: string, type: 'success'|'error'|'info' } | null, onClose: () => void }} props
 *
 * Usage:
 *   const { toast, showToast, hideToast } = useToast();
 *   <Toast toast={toast} onClose={hideToast} />
 */
export default function Toast({ toast, onClose }) {
  if (!toast) return null;

  const { message, type = 'success' } = toast;
  const Icon = ICONS[type] || ICONS.info;

  const typeClass =
    type === 'error' ? styles.error : type === 'info' ? styles.info : styles.success;

  return (
    <div className={`${styles.toast} ${typeClass}`} onClick={onClose}>
      <Icon size={16} className={styles.icon} />
      <span className={styles.message}>{message}</span>
      <button
        className={styles.close}
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
        aria-label="Cerrar notificación"
      >
        <X size={14} />
      </button>
    </div>
  );
}
