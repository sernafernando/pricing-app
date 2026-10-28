import { useEffect, useState } from 'react';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { ML_PRICED_TYPES, promoDisplayPrice } from '../promociones/promoDisplayPrice';
import { formatPrice } from './formatPrice';
import { selectParaGanarPromoPool } from './selectParaGanarPromoPool';
import styles from '../../pages/ParaGanarAdvisor.module.css';

function promoLabel(promo) {
  return promo.name || promo.payload?.name || promo.promotion_type || promo.promotion_id;
}

function priceHint(promo) {
  if (ML_PRICED_TYPES.has(promo.promotion_type)) {
    const price = promoDisplayPrice(promo);
    return price != null ? `$ ${formatPrice(price)}` : 'precio ML';
  }
  const min = promo.min_discounted_price;
  const max = promo.max_discounted_price;
  if (min != null && max != null) {
    return `$ ${formatPrice(min)} – ${formatPrice(max)}`;
  }
  if (min != null) return `desde $ ${formatPrice(min)}`;
  if (max != null) return `hasta $ ${formatPrice(max)}`;
  return 'rango no informado';
}

export default function ParaGanarPromoPool({ mla, precioSugerido }) {
  const { tienePermiso } = usePermisos();
  const canView = tienePermiso('promos.ver');
  const [pool, setPool] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!mla || !canView) {
      setPool([]);
      setError(null);
      setLoading(false);
      return undefined;
    }

    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const { data } = await promocionesAPI.getPromocionesItem(mla);
        if (cancelled) return;
        const promotions = data?.promotions || [];
        setPool(selectParaGanarPromoPool(promotions, { precioSugerido }));
      } catch (err) {
        if (cancelled) return;
        setPool([]);
        if (err.response?.status === 403) {
          setError('No tenés permiso para ver promociones (promos.ver).');
        } else {
          setError('No se pudo cargar el pool de promociones.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [mla, precioSugerido, canView]);

  if (!canView) {
    return (
      <section className={styles.promoPool} aria-label="Pool de promociones">
        <h3 className={styles.sellersTitle}>Promociones candidatas</h3>
        <p className={styles.emptyBody} role="status">
          Requiere permiso promos.ver para listar el mirror de promociones.
        </p>
      </section>
    );
  }

  return (
    <section className={styles.promoPool} aria-label="Pool de promociones">
      <h3 className={styles.sellersTitle}>Promociones candidatas</h3>
      <p className={styles.promoPoolLead}>
        Preferimos SMART; si no hay, DEAL/campaña cuyo rango cubra el precio sugerido. Aplicar
        desde Advisor llega después.
      </p>
      {loading && <p className={styles.emptyBody}>Cargando promociones…</p>}
      {error && (
        <p className={styles.criteriaFeedbackError} role="alert">
          {error}
        </p>
      )}
      {!loading && !error && pool.length === 0 && (
        <p className={styles.emptyBody}>Sin candidatas SMART ni DEAL/campaña en rango.</p>
      )}
      {!loading && pool.length > 0 && (
        <ul className={styles.promoPoolList}>
          {pool.map((promo) => (
            <li key={`${promo.promotion_type}-${promo.promotion_id}`} className={styles.promoPoolRow}>
              <div className={styles.promoPoolBody}>
                <div className={styles.promoPoolName}>{promoLabel(promo)}</div>
                <div className={styles.promoPoolMeta}>
                  {promo.promotion_type}
                  {' · '}
                  {priceHint(promo)}
                  {promo.nuestro_markup != null
                    ? ` · markup ${Number(promo.nuestro_markup).toFixed(1)}%`
                    : ''}
                </div>
              </div>
              <button
                type="button"
                className={styles.promoApplyBtn}
                disabled
                title="Próximo: enroll desde Advisor (mismo POST que Productos)"
              >
                Aplicar
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
