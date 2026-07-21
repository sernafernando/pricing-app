import { useCallback, useEffect, useMemo, useState } from 'react';
import { productosAPI } from '../../services/api';
import { useLazyResource } from '../../hooks/useLazyResource';
import { useExpandedSet } from '../../hooks/useExpandedSet';
import { getPublicationTypeLabel } from '../../constants/mlPublicationTypes';
import ExpandableRow from './ExpandableRow';
import MlaPromocionesPanel from './MlaPromocionesPanel';
import styles from './promociones.module.css';

const L1_COL_SPAN = 5;

/**
 * Builds the lite-endpoint filter params from the active promo filter props.
 * Mirrors `useProductosFilters.construirFiltrosParams` promo mapping (D2/D4):
 * types present -> promo_tipos + promo_estado; types absent -> legacy
 * type-agnostic boolean fallback ('disponible' = true no-op, no params).
 */
function buildPromoFilterParams(promoTipos, promoEstado) {
  const tipos = promoTipos || [];
  const estado = promoEstado || 'disponible';
  if (tipos.length > 0) {
    return { promo_tipos: tipos.join(','), promo_estado: estado };
  }
  if (estado === 'aplicada') return { con_promo_aplicada: true };
  if (estado === 'sin_aplicar') return { con_promo_sin_aplicar: true };
  return {};
}

/**
 * Level 1 panel: MLAs (MercadoLibre publications) of a product.
 * Lazily fetches `GET /productos/{item_id}/mercadolibre` on first mount
 * (i.e. on first expand — the parent conditionally mounts this component).
 * `data.publicaciones_ml` is consumed AS-IS (already ordered by the
 * endpoint Clásica -> 3 -> 6 -> 9 -> 12 cuotas) — do not re-sort here.
 *
 * `promoTipos`/`promoEstado` (optional) forward the active list-level promo
 * filter (productos-promo-filter-per-mla) so the lite endpoint can compute a
 * per-pub `matches_filter`. When active, publications with
 * `matches_filter === false` are hidden by default with a "ver todos (N)"
 * escape hatch; `matches_filter` absent/true always shows (fail-open).
 */
function ProductoMLAsPanel({ itemId, mlasCacheRef, promosCacheRef, promoTipos, promoEstado }) {
  const filterParams = useMemo(() => buildPromoFilterParams(promoTipos, promoEstado), [promoTipos, promoEstado]);
  const filterActive = Object.keys(filterParams).length > 0;
  const filterKey = useMemo(() => JSON.stringify(filterParams), [filterParams]);
  const cacheKey = `${itemId}::${filterKey}`;
  const [verTodos, setVerTodos] = useState(false);

  // Reset the "ver todos" reveal whenever the active filter changes, so a
  // filter change on an already-expanded (still-mounted) panel re-applies the
  // new hide set. Without this, verTodos stays true and the new filter is
  // silently defeated — all pubs shown, with no button to re-hide them.
  useEffect(() => {
    setVerTodos(false);
  }, [filterKey]);

  const fetcher = useCallback(
    () => productosAPI.getProductoMercadolibreLite(itemId, filterParams).then((r) => r.data),
    [itemId, filterParams],
  );
  const { data, loading, error, reload } = useLazyResource(mlasCacheRef, cacheKey, fetcher);
  const mlaExpanded = useExpandedSet();

  if (loading) {
    return <div className={styles.panelState}>Cargando publicaciones...</div>;
  }

  if (error) {
    return (
      <div className={styles.panelStateError}>
        Error al cargar publicaciones.{' '}
        <button type="button" className={styles.retryLink} onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  }

  const todasLasPublicaciones = data?.publicaciones_ml || [];

  if (todasLasPublicaciones.length === 0) {
    return <div className={styles.panelState}>Sin publicaciones en MercadoLibre.</div>;
  }

  // matches_filter absent/null/true = show (fail-open); false = hide unless
  // "ver todos" was clicked.
  const ocultas = filterActive ? todasLasPublicaciones.filter((pub) => pub.matches_filter === false) : [];
  const publicaciones = (filterActive && !verTodos)
    ? todasLasPublicaciones.filter((pub) => pub.matches_filter !== false)
    : todasLasPublicaciones;

  return (
    <>
      {filterActive && ocultas.length > 0 && !verTodos && (
        <div className={styles.filterMessage}>
          <button type="button" className={styles.retryLink} onClick={() => setVerTodos(true)}>
            ver todos ({ocultas.length})
          </button>
        </div>
      )}
      <table className={styles.innerTable}>
      <tbody>
        {publicaciones.map((pub) => (
          <ExpandableRow
            key={pub.mla}
            colSpan={L1_COL_SPAN}
            isOpen={mlaExpanded.isOpen(pub.mla)}
            onToggle={() => mlaExpanded.toggle(pub.mla)}
            ariaLabel={mlaExpanded.isOpen(pub.mla) ? `Colapsar ${pub.mla}` : `Expandir ${pub.mla}`}
            header={
              <>
                <td>
                  <span className={`${styles.badge} ${styles.badgeReadonly}`}>
                    {pub.lista_nombre || getPublicationTypeLabel(pub.pricelist_id)}
                  </span>
                </td>
                <td>{pub.mla}</td>
                <td>{pub.publication_status || 'N/A'}</td>
                <td>
                  {pub.promo_active_count > 0 && (
                    <span className={`${styles.badge} ${styles.promoCountBadge}`}>
                      {pub.promo_active_count} promos
                    </span>
                  )}
                  {pub.promo_has_applied && (
                    <span className={`${styles.badge} ${styles.appliedIndicator}`}>
                      Aplicada{pub.promo_applied_name ? `: ${pub.promo_applied_name}` : ''}
                    </span>
                  )}
                </td>
              </>
            }
          >
            <MlaPromocionesPanel mla={pub.mla} promosCacheRef={promosCacheRef} />
          </ExpandableRow>
        ))}
      </tbody>
      </table>
    </>
  );
}

export default ProductoMLAsPanel;
