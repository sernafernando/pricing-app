import { useCallback } from 'react';
import { productosAPI } from '../../services/api';
import { useLazyResource } from '../../hooks/useLazyResource';
import { useExpandedSet } from '../../hooks/useExpandedSet';
import { getPublicationTypeLabel } from '../../constants/mlPublicationTypes';
import ExpandableRow from './ExpandableRow';
import MlaPromocionesPanel from './MlaPromocionesPanel';
import styles from './promociones.module.css';

const L1_COL_SPAN = 4;

/**
 * Level 1 panel: MLAs (MercadoLibre publications) of a product.
 * Lazily fetches `GET /productos/{item_id}/mercadolibre` on first mount
 * (i.e. on first expand — the parent conditionally mounts this component).
 * `data.publicaciones_ml` is consumed AS-IS (already ordered by the
 * endpoint Clásica -> 3 -> 6 -> 9 -> 12 cuotas) — do not re-sort here.
 */
function ProductoMLAsPanel({ itemId, mlasCacheRef, promosCacheRef }) {
  const fetcher = useCallback((id) => productosAPI.getProductoMercadolibre(id).then((r) => r.data), []);
  const { data, loading, error, reload } = useLazyResource(mlasCacheRef, itemId, fetcher);
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

  const publicaciones = data?.publicaciones_ml || [];

  if (publicaciones.length === 0) {
    return <div className={styles.panelState}>Sin publicaciones en MercadoLibre.</div>;
  }

  return (
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
                    {getPublicationTypeLabel(pub.pricelist_id)}
                  </span>
                </td>
                <td>{pub.mla}</td>
                <td>{pub.publication_status || 'N/A'}</td>
              </>
            }
          >
            <MlaPromocionesPanel mla={pub.mla} promosCacheRef={promosCacheRef} />
          </ExpandableRow>
        ))}
      </tbody>
    </table>
  );
}

export default ProductoMLAsPanel;
