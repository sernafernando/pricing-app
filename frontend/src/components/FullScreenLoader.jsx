import styles from './FullScreenLoader.module.css';

/**
 * Full-viewport loading state: a simple spinner, no text.
 * Used by route-level gates (ProtectedRoute, SmartRedirect) while the
 * app bootstraps; end users should never read internals like
 * "Cargando permisos...".
 */
export default function FullScreenLoader() {
  return (
    <div className={styles.container} role="status" aria-label="Cargando">
      <div className={styles.spinner} />
    </div>
  );
}
