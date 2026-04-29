/**
 * FiltersBar — Toolbar para filtros del top de cada tab.
 *
 * Children se renderean en flex-wrap. Slot `actions` (opcional) queda
 * pegado a la derecha con margin-left auto, baja a línea nueva en mobile.
 *
 * @example
 * <FiltersBar actions={<button>Nuevo pedido</button>}>
 *   <select>...</select>
 *   <input type="date" />
 *   <SearchInput ... />
 * </FiltersBar>
 */

import styles from './FiltersBar.module.css';

/**
 * @param {Object} props
 * @param {React.ReactNode} props.children - filtros (selects, date pickers, etc.)
 * @param {React.ReactNode} [props.actions] - botones primarios alineados a la derecha
 */
export default function FiltersBar({ children, actions }) {
  return (
    <div className={styles.bar}>
      <div className={styles.filters}>{children}</div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
  );
}
