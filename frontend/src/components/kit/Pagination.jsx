import { pageWindow, PAGE_SIZE_OPTIONS } from '../../pages/ventasMlTableHelpers';
import styles from './Pagination.module.css';

/**
 * Numbered pager + rows-per-page selector for the Ventas ML list.
 * Controlled: the page owns `offset`/`pageSize` (they drive the request).
 * `summary` replaces the "mostrando a-b de N ventas" line for a screen that
 * counts something else (Métricas ML counts products). `pageSizeOptions`
 * narrows the selector for a backend with a lower cap (Publicaciones ML: 100).
 */
export default function Pagination({ total, offset, pageSize, onOffsetChange, onPageSizeChange, summary, pageSizeOptions = PAGE_SIZE_OPTIONS }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.floor(offset / pageSize) + 1;
  const rangeFrom = total === 0 ? 0 : offset + 1;
  const rangeTo = Math.min(offset + pageSize, total);
  const goTo = (page) => onOffsetChange((page - 1) * pageSize);

  return (
    <div className={styles.bar}>
      {summary ?? (
        <span>
          mostrando {rangeFrom}-{rangeTo} de {total} ventas
        </span>
      )}
      <div className={styles.pages}>
        <button
          type="button"
          className="btn-tesla ghost sm"
          onClick={() => goTo(currentPage - 1)}
          disabled={currentPage <= 1}
        >
          Anterior
        </button>
        {total > 0 &&
          pageWindow(currentPage, totalPages).map((entry) =>
            typeof entry === 'string' ? (
              <span key={entry} className={styles.gap} aria-hidden="true">
                …
              </span>
            ) : (
              <button
                key={entry}
                type="button"
                className={`btn-tesla ${entry === currentPage ? 'primary' : 'ghost'} sm`}
                aria-label={`Página ${entry}`}
                aria-current={entry === currentPage ? 'page' : undefined}
                onClick={() => goTo(entry)}
              >
                {entry}
              </button>
            ),
          )}
        <button
          type="button"
          className="btn-tesla ghost sm"
          onClick={() => goTo(currentPage + 1)}
          disabled={currentPage >= totalPages}
        >
          Siguiente
        </button>
      </div>
      <label className={styles.size}>
        Filas por página
        <select value={pageSize} onChange={(e) => onPageSizeChange(Number(e.target.value))}>
          {pageSizeOptions.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
