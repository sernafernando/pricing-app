import { useEffect, useId, useRef, useState } from 'react';
import { ChevronRight, X } from 'lucide-react';
import styles from './FilterSheet.module.css';

/**
 * The filters of a phone screen as a bottom sheet (design `MetricasFiltros.dc.html`): a title with "Limpiar" and
 * close, the sections scrolling, and a sticky "Ver N …" that closes it. The filters apply as they are tapped (the
 * page's own state), so closing never discards anything. Escape and the backdrop close it too.
 */
export default function FilterSheet({ title = 'Filtros', onClose, onClear, applyLabel, children }) {
  const titleId = useId();
  const sheetRef = useRef(null);
  // The latest `onClose`, so the open-once effect below never re-runs (and re-focuses) on a parent render.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    const previous = document.activeElement;
    sheetRef.current?.focus();
    const onKey = (event) => {
      if (event.key === 'Escape') onCloseRef.current();
    };
    document.addEventListener('keydown', onKey);
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, []);

  return (
    <div className={styles.backdrop} onClick={(event) => event.target === event.currentTarget && onClose()}>
      <div ref={sheetRef} className={styles.sheet} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className={styles.grip} aria-hidden="true">
          <span />
        </div>
        <div className={styles.header}>
          <h2 id={titleId} className={styles.title}>
            {title}
          </h2>
          <div className={styles.headerActions}>
            {onClear && (
              <button type="button" className={styles.clear} onClick={onClear}>
                Limpiar
              </button>
            )}
            <button type="button" className={styles.close} aria-label="Cerrar" onClick={onClose}>
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
        <div className={styles.body}>{children}</div>
        <div className={styles.footer}>
          <button type="button" className={styles.apply} onClick={onClose}>
            {applyLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** One always-open block of the sheet: a legend and its controls. */
export function SheetSection({ legend, children }) {
  return (
    <fieldset className={styles.section}>
      <legend className={styles.legend}>{legend}</legend>
      <div className={styles.controls}>{children}</div>
    </fieldset>
  );
}

/** A folded row of the sheet (Producto, Publicación, Cálculo): its name and what it holds, open on tap. */
export function SheetFold({ title, hint, children }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <div className={styles.fold}>
      <button type="button" className={styles.foldButton} aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((prev) => !prev)}>
        <span className={styles.foldText}>
          <span className={styles.foldTitle}>{title}</span>
          <span className={styles.foldHint}>{hint}</span>
        </span>
        <ChevronRight size={16} aria-hidden="true" className={open ? styles.chevronOpen : styles.chevron} />
      </button>
      {open && (
        <div id={panelId} className={styles.foldPanel}>
          {children}
        </div>
      )}
    </div>
  );
}
