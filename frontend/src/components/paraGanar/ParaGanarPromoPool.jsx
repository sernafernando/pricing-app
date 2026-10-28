import { useEffect, useState } from 'react';
import api, { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { ML_PRICED_TYPES, promoDisplayPrice } from '../promociones/promoDisplayPrice';
import { formatPrice } from './formatPrice';
import { selectParaGanarPromoPool } from './selectParaGanarPromoPool';
import styles from '../../pages/ParaGanarAdvisor.module.css';

function promoLabel(promo) {
  return promo.name || promo.payload?.name || promo.promotion_type || promo.promotion_id;
}

function priceHint(promo) {
  const offer = promoDisplayPrice(promo);
  if (ML_PRICED_TYPES.has(promo.promotion_type)) {
    return offer != null ? `$ ${formatPrice(offer)}` : 'precio ML';
  }
  // Started Premium often has a live offer price and null min/max.
  if (promo.pool_applied && offer != null) {
    return `$ ${formatPrice(offer)}`;
  }
  const min = promo.min_discounted_price;
  const max = promo.max_discounted_price;
  if (min != null && max != null) {
    return `$ ${formatPrice(min)} – ${formatPrice(max)}`;
  }
  if (offer != null) return `$ ${formatPrice(offer)}`;
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
        const [promosRes, criteriosRes] = await Promise.all([
          promocionesAPI.getPromocionesItem(mla),
          api.get(`/para-ganar/criterios/${encodeURIComponent(mla)}`).catch(() => ({ data: null })),
        ]);
        if (cancelled) return;
        const promotions = promosRes.data?.promotions || [];
        const criterios = criteriosRes.data;
        setPool(
          selectParaGanarPromoPool(promotions, {
            precioSugerido,
            markupMin: criterios?.markup_min ?? null,
            markupMax: criterios?.markup_max ?? null,
          }),
        );
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
        <h3 className={styles.sellersTitle}>Hasta 3 sugeridas</h3>
        <p className={styles.emptyBody} role="status">
          Requiere permiso promos.ver para listar el mirror de promociones.
        </p>
      </section>
    );
  }

  return (
    <section className={styles.promoPool} aria-label="Pool de promociones">
      <h3 className={styles.sellersTitle}>Hasta 3 sugeridas</h3>
      <p className={styles.promoPoolLead}>
        Hasta un SMART, un DEAL/campaña y un Premium (nombre). El precio de apply al
        sugerido llega con el enroll. Aplicar sigue deshabilitado.
      </p>
      {loading && <p className={styles.emptyBody}>Cargando promociones…</p>}
      {error && (
        <p className={styles.criteriaFeedbackError} role="alert">
          {error}
        </p>
      )}
      {!loading && !error && pool.length === 0 && (
        <p className={styles.emptyBody}>
          Ninguna candidata encaja con markup/rango del precio sugerido.
        </p>
      )}
      {!loading && pool.length > 0 && (
        <ul className={styles.promoPoolList}>
          {pool.map((promo) => (
            <li key={`${promo.promotion_type}-${promo.promotion_id}`} className={styles.promoPoolRow}>
              <div className={styles.promoPoolBody}>
                <div className={styles.promoPoolName}>
                  <span className={styles.promoPoolSlot}>{promo.pool_slot}</span>
                  {promo.pool_applied ? (
                    <span className={styles.promoPoolApplied}>Aplicada</span>
                  ) : null}
                  {promoLabel(promo)}
                </div>
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
                title={
                  promo.pool_applied
                    ? 'Ya está aplicada en ML'
                    : 'Próximo: enroll desde Advisor (mismo POST que Productos)'
                }
              >
                {promo.pool_applied ? 'Aplicada' : 'Aplicar'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
