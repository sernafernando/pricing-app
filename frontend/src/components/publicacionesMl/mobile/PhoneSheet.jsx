import { useEffect, useId, useRef } from 'react';
import { X } from 'lucide-react';
import styles from './PhoneSheet.module.css';

/**
 * A bottom sheet for the phone layout (mobile-metricas-pubml S2): the filters, or the header's "⋯" actions.
 *
 * Modal while open: a backdrop that closes it, Escape closes it, focus moves into it and goes back to the opener on
 * close. The body scrolls inside the sheet; `footer` (the "Ver N publicaciones" button) stays at its bottom.
 *
 * @param {object} props
 * @param {boolean} props.open
 * @param {string} props.title
 * @param {() => void} props.onClose
 * @param {import('react').ReactNode} [props.headerAction] Beside the title, before the close button ("Limpiar").
 * @param {import('react').ReactNode} [props.footer]
 * @param {import('react').ReactNode} props.children
 */
export default function PhoneSheet({ open, title, onClose, headerAction = null, footer = null, children }) {
  const titleId = useId();
  const sheetRef = useRef(null);
  // The latest `onClose`, so a parent's new function on each render never re-runs the effect (and moves the focus).
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return undefined;
    const opener = document.activeElement;
    sheetRef.current?.focus();
    const handleKeyDown = (event) => {
      // A modal opened from the sheet (a bulk action) owns its own Escape.
      if (event.key !== 'Escape' || event.defaultPrevented || document.querySelector('.modal-overlay-tesla')) return;
      event.preventDefault();
      closeRef.current();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      if (opener instanceof HTMLElement && document.body.contains(opener)) opener.focus();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div className={styles.layer}>
      <div className={styles.backdrop} aria-hidden="true" onClick={onClose} />
      <div ref={sheetRef} className={styles.sheet} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <header className={styles.header}>
          <h2 id={titleId} className={styles.title}>
            {title}
          </h2>
          {headerAction}
          <button type="button" className={styles.close} aria-label="Cerrar" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className={styles.body}>{children}</div>
        {footer && <footer className={styles.footer}>{footer}</footer>}
      </div>
    </div>
  );
}
