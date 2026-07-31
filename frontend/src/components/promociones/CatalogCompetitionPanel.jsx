import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { promocionesAPI } from '../../services/api';
import { useLazyResource } from '../../hooks/useLazyResource';
import { getMarkupColor } from '../../hooks/useProductosOffsets';
import styles from './promociones.module.css';

function formatFechaConsulta(iso) {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString('es-AR');
}

function formatPrice(value) {
  if (value === null || value === undefined) return 'N/A';
  return `$${Number(value).toLocaleString('es-AR')}`;
}

// Backend-computed markup (product decision #8) — this component only
// formats it, it never recomputes it.
function formatMarkup(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
  return `${Number(value).toFixed(1)}%`;
}

/**
 * Catalog-competition panel for one MLA
 * (promos-catalog-prices-and-official-store, slice C2).
 *
 * Reads the LATEST STORED snapshot on mount via
 * `GET /promociones/catalogo-competencia/{mla}` — cheap (our own DB, no
 * ML-webhook call). It NEVER auto-fetches a FRESH snapshot: that only
 * happens from the explicit refresh button below, which is per-MLA only
 * (product decision #4 — the ML throttle is global and shared with
 * sales-webhook processing).
 *
 * The backend already filters `undercutting` to same-bucket AND strictly
 * cheaper competitors (product decision #6, spec C2.6); this component
 * never recomputes bucket membership, currency conversion, or markup.
 */
function CatalogCompetitionPanel({ mla, catalogCompetitionCacheRef }) {
  const fetcher = (id) => promocionesAPI.getCompetenciaCatalogo(id).then((r) => r.data);
  const { data, loading, error, reload } = useLazyResource(catalogCompetitionCacheRef, mla, fetcher);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(false);

  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshError(false);
    try {
      await promocionesAPI.refreshCompetenciaCatalogo(mla);
      catalogCompetitionCacheRef.current.delete(mla);
      reload();
    } catch {
      setRefreshError(true);
    } finally {
      setRefreshing(false);
    }
  };

  const refreshButton = (
    <button
      type="button"
      className="btn-tesla outline-subtle-primary icon-only sm"
      onClick={handleRefresh}
      disabled={refreshing}
      aria-label={`Refrescar competencia de catálogo de ${mla}`}
    >
      <RefreshCw size={14} />
    </button>
  );

  if (loading) {
    return <div className={styles.panelState}>Cargando competencia de catálogo...</div>;
  }

  if (error) {
    return (
      <div className={styles.panelStateError}>
        Error al cargar competencia de catálogo.{' '}
        <button type="button" className="btn-tesla ghost sm" onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  }

  const fetchStatus = data?.fetch_status || 'never';
  const fechaLabel = formatFechaConsulta(data?.fecha_consulta);

  if (fetchStatus === 'never') {
    return (
      <div className={styles.panelState}>
        Sin consultar todavía. {refreshButton}
        {refreshing && <span className={styles.provisionalPending}>Consultando…</span>}
        {refreshError && <span className={styles.feedbackError}>No se pudo consultar</span>}
      </div>
    );
  }

  if (fetchStatus === 'not_catalog') {
    return (
      <div className={styles.panelState}>
        No aplica: esta publicación no pertenece a un catálogo de MercadoLibre.
        {fechaLabel && <span className={styles.treeNodeSummaryCounts}> (consultado {fechaLabel})</span>}
      </div>
    );
  }

  if (fetchStatus === 'error') {
    return (
      <div className={styles.panelStateError}>
        Error al consultar competencia de catálogo{data.error_detail ? `: ${data.error_detail}` : ''}. {refreshButton}
        {refreshing && <span className={styles.provisionalPending}>Reintentando…</span>}
      </div>
    );
  }

  const undercutting = data.undercutting || [];

  return (
    <div>
      <div className={styles.filterMessage}>
        {fechaLabel && <span className={styles.treeNodeSummaryCounts}>Consultado {fechaLabel}</span>}
        {data.our_price != null && (
          <span className={styles.treeNodeSummaryCounts}> · Nuestro precio: {formatPrice(data.our_price)}</span>
        )}
        {refreshButton}
        {refreshing && <span className={styles.provisionalPending}>Consultando…</span>}
        {refreshError && <span className={styles.feedbackError}>No se pudo consultar</span>}
      </div>
      {undercutting.length === 0 ? (
        <div className={styles.panelState}>
          Sin competidores más baratos en tu mismo formato
          {data.competitor_count
            ? ` (${data.competitor_count} competidores relevados, ocultos por formato distinto o no comparables)`
            : ''}
          .
        </div>
      ) : (
        <ul className={styles.promoList}>
          {undercutting.map((competitor) => (
            <li key={competitor.item_id || competitor.seller_id} className={styles.promoRow}>
              <span className={styles.promoName}>
                {competitor.seller_nickname || competitor.item_id || 'Competidor'}
              </span>
              <span className={styles.promoPrice}>{formatPrice(competitor.price_ars ?? competitor.price)}</span>
              <span className={styles.promoMarkup} style={{ color: getMarkupColor(competitor.markup) }}>
                Tu markup si igualás: {formatMarkup(competitor.markup)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default CatalogCompetitionPanel;
