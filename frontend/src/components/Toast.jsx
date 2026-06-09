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
 * @param {{
 *   toast: { message: string, type: 'success'|'error'|'info' } | null,
 *   onClose: () => void,
 *   action?: { label: string, onClick: () => void },
 * }} props
 *
 * Usage:
 *   const { toast, showToast, hideToast } = useToast();
 *   <Toast toast={toast} onClose={hideToast} />
 *
 * With an action button (e.g. "new version available"):
 *   <Toast toast={t} onClose={dismiss} action={{ label: 'Actualizar', onClick: apply }} />
 */
export default function Toast({ toast, onClose, action }) {
  if (!toast) return null;

  const { message, type = 'success' } = toast;
  const Icon = ICONS[type] || ICONS.info;

  const typeClass =
    type === 'error' ? styles.error : type === 'info' ? styles.info : styles.success;

  // When the toast carries an action, clicking the body must NOT dismiss it —
  // the user could lose the chance to act by accident. They use the buttons.
  const handleBodyClick = action ? undefined : onClose;

  return (
    <div className={`${styles.toast} ${typeClass}`} onClick={handleBodyClick}>
      <Icon size={16} className={styles.icon} />
      <span className={styles.message}>{message}</span>
      {action && (
        <button
          className={styles.action}
          onClick={(e) => {
            e.stopPropagation();
            action.onClick();
          }}
        >
          {action.label}
        </button>
      )}
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
