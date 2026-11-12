import { ChevronLeft, X } from 'lucide-react';
import useIsPhone from '../../../hooks/useIsPhone';
import styles from './panel.module.css';

/**
 * The frame of a side panel beside the table: a header with the title, what
 * the caller puts under it (`meta`), the close button and the key figures
 * (`figures`), which stays in view while the panel scrolls; then the loading
 * skeleton or the error with its retry, then the panel's own content.
 *
 * @param {object} props
 * @param {import('react').ReactNode} props.title
 * @param {import('react').ReactNode} [props.meta] Rendered under the title (ids, links, status).
 * @param {import('react').ReactNode} [props.figures] The header's figures (`PanelFigures`), on every tab.
 * @param {() => void} props.onClose
 * @param {boolean} [props.loading] Shows the skeleton.
 * @param {string} [props.loadingLabel] Accessible name of the skeleton.
 * @param {string|null} [props.error] What to tell the operator; shows the error block when set.
 * @param {() => void} [props.onRetry] Shows "Reintentar" in the error block.
 * @param {import('react').ReactNode} [props.phoneActions] On a phone, beside "‹ Publicaciones" at the top right.
 * @param {import('react').ReactNode} [props.children] The panel's content.
 */
export default function PanelShell({
  title,
  meta,
  figures,
  onClose,
  loading = false,
  loadingLabel,
  error = null,
  onRetry,
  phoneActions = null,
  children,
}) {
  // On a phone the panel is the whole screen (mobile-metricas-pubml S2): "‹ Publicaciones" goes back to the list.
  const phone = useIsPhone();
  return (
    <div className={styles.panel}>
      <header className={styles.header}>
        {phone && (
          <div className={styles.phoneBar}>
            <button type="button" className={styles.phoneBack} onClick={onClose}>
              <ChevronLeft size={18} aria-hidden="true" />
              Publicaciones
            </button>
            {phoneActions}
          </div>
        )}
        <div className={styles.headerTop}>
          <div className={styles.identity}>
            <h2 className={styles.title}>{title}</h2>
            {meta}
          </div>
          {!phone && (
            <button type="button" className={styles.close} aria-label="Cerrar panel" onClick={onClose}>
              <X size={16} aria-hidden="true" />
            </button>
          )}
        </div>
        {figures}
      </header>

      {loading && (
        <div className={styles.skeleton} role="status" aria-label={loadingLabel} aria-busy="true">
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className={styles.skeletonRow} />
          ))}
        </div>
      )}

      {error && (
        <div className={styles.error} role="alert">
          <span>{error}</span>
          {onRetry && (
            <button type="button" className="btn-tesla outline sm" onClick={onRetry}>
              Reintentar
            </button>
          )}
        </div>
      )}

      {children}
    </div>
  );
}
