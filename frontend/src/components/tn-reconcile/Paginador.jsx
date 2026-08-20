import styles from '../../pages/TiendaNubeReconcile.module.css';

// Shared paginator — used identically by the DUPLICADO branch and the
// general-table branch (previously duplicated verbatim in both).
export default function Paginador({ page, totalPages, rangeStart, rangeEnd, total, onPrev, onNext }) {
  return (
    <div className={styles.paginatorBar}>
      <span>
        Mostrando {rangeStart}–{rangeEnd} de {total}
      </span>
      <div>
        <button type="button" className="btn-tesla ghost sm" disabled={page <= 1} onClick={onPrev}>
          Anterior
        </button>
        <button
          type="button"
          className={`btn-tesla ghost sm ${styles.btnSpaced}`}
          disabled={page >= totalPages}
          onClick={onNext}
        >
          Siguiente
        </button>
      </div>
    </div>
  );
}
