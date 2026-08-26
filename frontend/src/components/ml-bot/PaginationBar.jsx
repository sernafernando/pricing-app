/**
 * Shared offset-based pagination control for the ml-bot panel's Preguntas
 * and Mensajes tabs (introduced inline in PR1, extracted verbatim into its
 * own module in PR4 — ml-bot-panel-operador, design ADR-3).
 */
import styles from '../../pages/MLQuestions.module.css';

export function PaginationBar({ offset, pageSize, total, onOffsetChange, unitLabel = 'resultados' }) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + pageSize, total);
  const isFirstPage = offset === 0;
  const isLastPage = offset + pageSize >= total;

  return (
    <div className={styles.filtersBar}>
      <button
        type="button"
        className="btn-tesla ghost sm"
        onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}
        disabled={isFirstPage}
      >
        Anterior
      </button>
      <span>
        mostrando {from}-{to} de {total} {unitLabel}
      </span>
      <button
        type="button"
        className="btn-tesla ghost sm"
        onClick={() => onOffsetChange(offset + pageSize)}
        disabled={isLastPage}
      >
        Siguiente
      </button>
    </div>
  );
}
