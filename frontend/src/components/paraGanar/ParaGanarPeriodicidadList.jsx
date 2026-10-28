import { AlertTriangle, RefreshCw } from 'lucide-react';
import { scopeSummary } from './periodicidadForm';
import styles from '../../pages/ParaGanarAdvisor.module.css';

export default function ParaGanarPeriodicidadList({
  items,
  loading,
  error,
  page,
  totalPages,
  selectedEan,
  onSelect,
  onRetry,
  onPrevPage,
  onNextPage,
}) {
  return (
    <section className={styles.queue} aria-label="EANs del alcance">
      <div className={styles.panelTitle}>
        EANs (alcance filtrado)
        {!loading && (
          <span className={styles.panelMeta}>
            pág. {page}/{totalPages}
          </span>
        )}
      </div>

      {loading && (
        <div className={styles.loadingState}>
          <RefreshCw size={18} className={styles.spinner} aria-hidden />
          <span>Cargando…</span>
        </div>
      )}

      {!loading && error && (
        <div className={styles.errorState}>
          <AlertTriangle size={18} aria-hidden />
          <span>{error}</span>
          <button type="button" className={styles.retryBtn} onClick={onRetry}>
            Reintentar
          </button>
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <div className={styles.emptyState}>
          <p className={styles.emptyTitle}>Sin EANs</p>
          <p className={styles.emptyBody}>
            No hay códigos en el alcance actual. Ajustá los filtros de arriba.
          </p>
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <>
          <ul className={styles.queueList}>
            {items.map((row) => {
              const selected = row.ean === selectedEan;
              return (
                <li key={row.ean}>
                  <button
                    type="button"
                    className={`${styles.queueRow} ${
                      row.suscripto ? styles.queueRowCriteriaApplied : ''
                    } ${selected ? styles.queueRowSelected : ''}`}
                    onClick={() => onSelect(row)}
                    aria-pressed={selected}
                  >
                    <div className={styles.queueRowTop}>
                      <strong>{row.ean}</strong>
                      <span className={styles.queueRowMeta}>
                        {row.suscripto
                          ? row.enabled === false
                            ? 'Suscripto · pausada'
                            : 'Suscripto'
                          : 'Sin suscribir'}
                      </span>
                    </div>
                    <div className={styles.queueRowTitle}>
                      {row.descripcion || row.marca || 'Sin descripción'}
                    </div>
                    <div className={styles.queueRowMeta}>
                      <span>{row.marca || '—'}</span>
                      <span>{scopeSummary(row)}</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
          <div className={styles.pager}>
            <button
              type="button"
              className={styles.pagerBtn}
              disabled={page <= 1}
              onClick={onPrevPage}
            >
              Anterior
            </button>
            <button
              type="button"
              className={styles.pagerBtn}
              disabled={page >= totalPages}
              onClick={onNextPage}
            >
              Siguiente
            </button>
          </div>
        </>
      )}
    </section>
  );
}
