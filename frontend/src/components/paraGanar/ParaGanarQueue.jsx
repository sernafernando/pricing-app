import { RefreshCw, AlertTriangle, Link2 } from 'lucide-react';
import { formatPrice } from './formatPrice';
import styles from '../../pages/ParaGanarAdvisor.module.css';

export default function ParaGanarQueue({
  mode,
  items,
  loading,
  error,
  page,
  totalPages,
  selectedMla,
  onSelect,
  onRetry,
  onPrevPage,
  onNextPage,
}) {
  const isCriterios = mode === 'criterios';

  return (
    <section
      className={styles.queue}
      aria-label={isCriterios ? 'MLAs para criterios' : 'Cola de sugerencias'}
    >
      <div className={styles.panelTitle}>
        {isCriterios ? 'MLAs (criterios)' : 'Cola (MLA)'}
        {!loading && (
          <span className={styles.panelMeta}>
            pág. {page}/{totalPages}
          </span>
        )}
      </div>

      {loading && (
        <div className={styles.loadingState}>
          <RefreshCw size={18} className={styles.spinner} aria-hidden />
          <span>Cargando publicaciones…</span>
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
          <p className={styles.emptyTitle}>Sin resultados</p>
          <p className={styles.emptyBody}>
            No hay publicaciones activas para este filtro en el sandbox.
          </p>
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <>
          <ul className={styles.queueList}>
            {items.map((row) => {
              const isSelected = row.mla === selectedMla;
              const hasCriteria = Boolean(row.criterios_aplicados);
              const rowClass = [
                styles.queueRow,
                hasCriteria ? styles.queueRowCriteriaApplied : '',
                isSelected ? styles.queueRowSelected : '',
              ]
                .filter(Boolean)
                .join(' ');
              return (
                <li key={row.mla}>
                  <button
                    type="button"
                    className={rowClass}
                    onClick={() => onSelect(row.mla)}
                    aria-pressed={isSelected}
                  >
                    <div className={styles.queueRowTop}>
                      <span className={styles.mla}>{row.mla}</span>
                      {row.sync_partner_mla && (
                        <span className={styles.syncBadge} title={`Par sync: ${row.sync_partner_mla}`}>
                          <Link2 size={12} aria-hidden />
                          Sync
                        </span>
                      )}
                      {row.catalog_listing && (
                        <span className={styles.catalogBadge}>Catálogo</span>
                      )}
                      {isCriterios && (
                        <span
                          className={
                            row.criterios_aplicados
                              ? styles.criteriaBadgeApplied
                              : styles.criteriaBadge
                          }
                        >
                          {row.criterios_aplicados
                            ? 'Con criterio aplicado'
                            : 'Sin criterio aplicado'}
                        </span>
                      )}
                    </div>
                    <div className={styles.queueRowTitle}>
                      {row.titulo || row.producto_descripcion || 'Sin título'}
                    </div>
                    <div className={styles.queueRowMeta}>
                      <span>{row.codigo || '—'}</span>
                      <span>{row.lista_nombre || 'Sin lista'}</span>
                      <span className={styles.price}>$ {formatPrice(row.precio)}</span>
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
