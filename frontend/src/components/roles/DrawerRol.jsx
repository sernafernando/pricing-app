import { useEffect, useId, useRef } from 'react';
import { X } from 'lucide-react';
import styles from './DrawerRol.module.css';

/**
 * Side panel of the Roles tab: role detail and role management (create, edit,
 * clone, delete). Non-modal: the matrix next to it stays usable. Escape and the
 * close button do nothing while `puedeCerrar` is false (a role save or delete is
 * in flight, or a dialog is open on top of it), so a late response never lands
 * in a panel that was closed or switched to another role. Escape counts only when
 * it comes from inside the drawer (or nothing is focused): Esc in the matrix
 * search must not discard what was typed in the form.
 */
export default function DrawerRol({ titulo, puedeCerrar, onCerrar, children }) {
  const tituloId = useId();
  const tituloRef = useRef(null);
  const drawerRef = useRef(null);

  useEffect(() => {
    tituloRef.current?.focus();
  }, []);

  useEffect(() => {
    const alPresionar = (e) => {
      if (e.key !== 'Escape' || !puedeCerrar) return;
      const desdeDrawer = drawerRef.current?.contains(e.target) || e.target === document.body;
      if (desdeDrawer) onCerrar();
    };
    document.addEventListener('keydown', alPresionar);
    return () => document.removeEventListener('keydown', alPresionar);
  }, [puedeCerrar, onCerrar]);

  return (
    <aside ref={drawerRef} role="dialog" aria-labelledby={tituloId} className={styles.drawer}>
      <header className={styles.encabezado}>
        <h3 id={tituloId} ref={tituloRef} tabIndex={-1} className={styles.titulo}>
          {titulo}
        </h3>
        <button
          type="button"
          className={styles.cerrar}
          onClick={onCerrar}
          disabled={!puedeCerrar}
          aria-label="Cerrar panel del rol"
        >
          <X size={16} aria-hidden="true" />
        </button>
      </header>
      {children}
    </aside>
  );
}
