import { X, Loader2, Inbox } from 'lucide-react';
import styles from './PanelCheques.module.css';

/**
 * SelectorListaModal — modal genérico "elegí un ítem de una lista".
 *
 * Extraído del selector de cartera de PanelCheques (S1) para no duplicar la
 * misma estructura (overlay + header + loading/empty/lista) en cada entry
 * point que necesita "elegí un X de esta lista" — S4 lo reutiliza para:
 *   - PanelCheques "Aplicar cheque propio" (lista de cheques elegibles)
 *   - TabCheques "Aplicar a OP" (lista de OPs pendientes del proveedor)
 *
 * Props:
 *   title        string
 *   items        Array<T>
 *   getKey       (item: T) => string|number
 *   renderItem   (item: T) => ReactNode — contenido del botón (sin el <button>)
 *   onSelect     (item: T) => void
 *   isDisabled   (item: T) => boolean — opcional
 *   ariaLabel    (item: T) => string — opcional
 *   loading      bool
 *   emptyMessage string
 *   onClose      () => void
 */
export default function SelectorListaModal({
  title,
  items = [],
  getKey,
  renderItem,
  onSelect,
  isDisabled,
  ariaLabel,
  loading = false,
  emptyMessage = 'No hay elementos disponibles.',
  onClose,
}) {
  return (
    <div className={styles.selectorOverlay}>
      <div
        className={styles.selectorModal}
        role="dialog"
        aria-modal="true"
        aria-labelledby="selector-lista-title"
      >
        <header className={styles.selectorHeader}>
          <h3 id="selector-lista-title" className={styles.selectorTitle}>
            {title}
          </h3>
          <button
            type="button"
            className={styles.btnClose}
            onClick={onClose}
            aria-label="Cerrar"
          >
            <X size={16} />
          </button>
        </header>

        <div className={styles.selectorBody}>
          {loading ? (
            <div className={styles.selectorLoading}>
              <Loader2 size={18} className={styles.spin} />
              <span>Cargando...</span>
            </div>
          ) : items.length === 0 ? (
            <div className={styles.selectorEmpty}>
              <Inbox size={28} />
              <p>{emptyMessage}</p>
            </div>
          ) : (
            <div className={styles.selectorLista}>
              {items.map((item) => {
                const key = getKey(item);
                const disabled = isDisabled ? isDisabled(item) : false;
                return (
                  <button
                    key={key}
                    type="button"
                    className={`${styles.selectorItem} ${disabled ? styles.selectorItemUsado : ''}`}
                    onClick={() => onSelect(item)}
                    disabled={disabled}
                    aria-label={ariaLabel ? ariaLabel(item) : undefined}
                  >
                    {renderItem(item)}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
