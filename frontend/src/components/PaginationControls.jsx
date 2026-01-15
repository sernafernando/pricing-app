import { useMemo } from 'react';
import PropTypes from 'prop-types';
import styles from './PaginationControls.module.css';

/**
 * Componente de controles de paginación reutilizable.
 * Soporta scroll infinito y paginación clásica con toggle.
 */
function PaginationControls({
  mode,
  onToggleMode,
  currentPage,
  totalPages,
  totalItems,
  hasMore,
  loading,
  onGoToPage,
  pageSize
}) {
  // Calcular rango de items mostrados
  const itemRange = useMemo(() => {
    const start = (currentPage - 1) * pageSize + 1;
    const end = Math.min(currentPage * pageSize, totalItems);
    return { start, end };
  }, [currentPage, pageSize, totalItems]);

  // Generar números de página para mostrar
  const pageNumbers = useMemo(() => {
    if (mode !== 'classic' || totalPages === 0) return [];

    const pages = [];
    const maxVisible = 7; // Máximo de números de página visibles
    
    if (totalPages <= maxVisible) {
      // Mostrar todas las páginas
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i);
      }
    } else {
      // Mostrar con ellipsis
      if (currentPage <= 4) {
        // Cerca del inicio: 1 2 3 4 5 ... N
        for (let i = 1; i <= 5; i++) pages.push(i);
        pages.push('...');
        pages.push(totalPages);
      } else if (currentPage >= totalPages - 3) {
        // Cerca del final: 1 ... N-4 N-3 N-2 N-1 N
        pages.push(1);
        pages.push('...');
        for (let i = totalPages - 4; i <= totalPages; i++) pages.push(i);
      } else {
        // En el medio: 1 ... P-1 P P+1 ... N
        pages.push(1);
        pages.push('...');
        pages.push(currentPage - 1);
        pages.push(currentPage);
        pages.push(currentPage + 1);
        pages.push('...');
        pages.push(totalPages);
      }
    }

    return pages;
  }, [mode, currentPage, totalPages]);

  return (
    <div className={styles.container}>
      {/* Toggle de modo */}
      <div className={styles.modeToggle}>
        <button
          className={`${styles.toggleBtn} ${mode === 'infinite' ? styles.active : ''}`}
          onClick={onToggleMode}
          title="Alternar entre scroll infinito y páginas"
        >
          <span className={styles.icon}>
            {mode === 'infinite' ? '∞' : '#'}
          </span>
          <span className={styles.label}>
            {mode === 'infinite' ? 'Scroll Infinito' : 'Páginas'}
          </span>
        </button>
      </div>

      {/* Información */}
      <div className={styles.info}>
        {mode === 'infinite' ? (
          <>
            <span className={styles.count}>
              {totalItems > 0 ? `${totalItems} resultados cargados` : 'Cargando...'}
            </span>
            {hasMore && !loading && (
              <span className={styles.hasMore}>• Hay más resultados</span>
            )}
            {loading && (
              <span className={styles.loadingText}>• Cargando...</span>
            )}
          </>
        ) : (
          <>
            {totalItems > 0 && (
              <span className={styles.count}>
                Mostrando {itemRange.start}-{itemRange.end} de {totalItems.toLocaleString()} resultados
              </span>
            )}
          </>
        )}
      </div>

      {/* Controles de paginación clásica */}
      {mode === 'classic' && totalPages > 1 && (
        <div className={styles.pagination}>
          {/* Botón anterior */}
          <button
            className={styles.pageBtn}
            onClick={() => onGoToPage(currentPage - 1)}
            disabled={currentPage === 1 || loading}
            aria-label="Página anterior"
          >
            ‹
          </button>

          {/* Números de página */}
          {pageNumbers.map((page, idx) => (
            page === '...' ? (
              <span key={`ellipsis-${idx}`} className={styles.ellipsis}>
                ...
              </span>
            ) : (
              <button
                key={page}
                className={`${styles.pageBtn} ${page === currentPage ? styles.active : ''}`}
                onClick={() => onGoToPage(page)}
                disabled={loading}
              >
                {page}
              </button>
            )
          ))}

          {/* Botón siguiente */}
          <button
            className={styles.pageBtn}
            onClick={() => onGoToPage(currentPage + 1)}
            disabled={currentPage === totalPages || loading}
            aria-label="Página siguiente"
          >
            ›
          </button>

          {/* Input para ir a página específica */}
          <div className={styles.goToPage}>
            <input
              type="number"
              min="1"
              max={totalPages}
              value={currentPage}
              onChange={(e) => {
                const page = parseInt(e.target.value);
                if (page >= 1 && page <= totalPages) {
                  onGoToPage(page);
                }
              }}
              className={styles.pageInput}
              disabled={loading}
              aria-label="Ir a página"
            />
            <span className={styles.pageInputLabel}>de {totalPages}</span>
          </div>
        </div>
      )}
    </div>
  );
}

PaginationControls.propTypes = {
  mode: PropTypes.oneOf(['infinite', 'classic']).isRequired,
  onToggleMode: PropTypes.func.isRequired,
  currentPage: PropTypes.number.isRequired,
  totalPages: PropTypes.number.isRequired,
  totalItems: PropTypes.number.isRequired,
  hasMore: PropTypes.bool.isRequired,
  loading: PropTypes.bool.isRequired,
  onGoToPage: PropTypes.func.isRequired,
  pageSize: PropTypes.number.isRequired,
};

export default PaginationControls;
