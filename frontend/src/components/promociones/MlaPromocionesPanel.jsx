import { useCallback } from 'react';
import { promocionesAPI } from '../../services/api';
import { useLazyResource } from '../../hooks/useLazyResource';
import styles from './promociones.module.css';

// SELLER_CAMPAIGN/DEAL/SMART can be enrolled via the apply control (FE-C).
// DOD/LIGHTNING/PRICE_DISCOUNT are read-only informational entries.
const APPLICABLE_TYPES = new Set(['SELLER_CAMPAIGN', 'DEAL', 'SMART']);

function formatPercentage(value) {
  if (value === null || value === undefined) return null;
  return `${value}%`;
}

function formatPrice(value) {
  if (value === null || value === undefined) return 'N/A';
  return `$${Number(value).toLocaleString('es-AR')}`;
}

/**
 * Level 2 panel: promotions of a single MLA.
 * Lazily fetches `GET /promociones/item/{mla}` on first mount (i.e. on
 * first expand — the parent conditionally mounts this component).
 */
function MlaPromocionesPanel({ mla, promosCacheRef }) {
  const fetcher = useCallback((id) => promocionesAPI.getPromocionesItem(id).then((r) => r.data), []);
  const { data, loading, error, reload } = useLazyResource(promosCacheRef, mla, fetcher);

  if (loading) {
    return <div className={styles.panelState}>Cargando promociones...</div>;
  }

  if (error) {
    return (
      <div className={styles.panelStateError}>
        Error al cargar promociones.{' '}
        <button type="button" className={styles.retryLink} onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  }

  const promociones = data?.promotions || [];

  if (promociones.length === 0) {
    return <div className={styles.panelState}>Sin promociones habilitadas.</div>;
  }

  return (
    <ul className={styles.promoList}>
      {promociones.map((promo) => {
        const applicable = APPLICABLE_TYPES.has(promo.promotion_type);
        const sellerPct = formatPercentage(promo.payload?.seller_percentage);
        const meliPct = formatPercentage(promo.payload?.meli_percentage);

        return (
          <li
            key={promo.promotion_id}
            className={`${styles.promoRow} ${applicable ? styles.promoApplicable : styles.promoReadonly}`}
          >
            <span className={`${styles.badge} ${applicable ? styles.badgeApplicable : styles.badgeReadonly}`}>
              {promo.promotion_type || 'N/A'}
            </span>
            <span className={styles.promoName}>{promo.name || promo.promotion_id}</span>
            <span className={styles.promoPrice}>
              {formatPrice(promo.price)}
              {promo.original_price != null && promo.original_price !== promo.price && (
                <span className={styles.promoOriginalPrice}> ({formatPrice(promo.original_price)})</span>
              )}
            </span>
            {promo.promotion_type === 'SMART' && (sellerPct || meliPct) && (
              <span className={styles.promoSmartCost}>
                {sellerPct && `Costo vendedor: ${sellerPct}`}
                {sellerPct && meliPct && ' · '}
                {meliPct && `Cofinanciación ML: ${meliPct}`}
              </span>
            )}
            {/* Apply control slot — real enroll action lands in FE-C. */}
            {applicable && (
              <button type="button" className={styles.applySlot} disabled title="Disponible próximamente">
                Aplicar
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export default MlaPromocionesPanel;
