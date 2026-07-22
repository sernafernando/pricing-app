import { ChevronDown, ChevronRight } from 'lucide-react';
import styles from './promociones.module.css';

/**
 * Generic expandable inner-table row primitive.
 * Renders a header <tr> (chevron toggle + header slot) and, when open, a
 * detail <tr><td colSpan> with children.
 *
 * NOT intended for the top-level Productos product row — scoped to the new
 * inner tables (L1 MLA rows, L2 promotion rows).
 */
function ExpandableRow({
  isOpen,
  onToggle,
  colSpan,
  header,
  children,
  ariaLabel,
  'data-testid': dataTestId,
  headerRowClassName,
}) {
  const label = ariaLabel || (isOpen ? 'Colapsar' : 'Expandir');

  return (
    <>
      <tr data-testid={dataTestId} className={headerRowClassName}>
        <td className={styles.spoilerToggleCell}>
          <button
            type="button"
            className={styles.spoilerToggle}
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
            aria-label={label}
            aria-expanded={isOpen}
          >
            {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
        </td>
        {header}
      </tr>
      {isOpen && (
        <tr className={styles.filaDetalle}>
          <td colSpan={colSpan}>
            <div className={styles.filaDetalleContent}>{children}</div>
          </td>
        </tr>
      )}
    </>
  );
}

export default ExpandableRow;
