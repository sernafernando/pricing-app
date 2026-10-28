import { useCallback, useEffect, useRef, useState } from 'react';
import api, { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { ML_PRICED_TYPES, promoDisplayPrice } from '../promociones/promoDisplayPrice';
import { formatPrice } from './formatPrice';
import {
  buildParaGanarEnrollBody,
  selectParaGanarPromoPool,
  SELLER_PRICED_TYPES,
} from './selectParaGanarPromoPool';
import styles from '../../pages/ParaGanarAdvisor.module.css';

function promoLabel(promo) {
  return promo.name || promo.payload?.name || promo.promotion_type || promo.promotion_id;
}

function priceHint(promo) {
  const offer = promoDisplayPrice(promo);
  if (ML_PRICED_TYPES.has(promo.promotion_type)) {
    return offer != null ? `$ ${formatPrice(offer)}` : 'precio ML';
  }
  if (promo.pool_applied && offer != null) {
    return `$ ${formatPrice(offer)}`;
  }
  if (promo.pool_deal_price != null) {
    return `aplicar a $ ${formatPrice(promo.pool_deal_price)}`;
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

function enrollFeedback(status) {
  const map = {
    submitted: 'Enviado — puede tardar en reflejarse en el mirror.',
    ambiguous: 'Enviado, estado por confirmar — verificá en ML.',
    reconciled_applied: 'Promoción aplicada.',
    reconciled_not_applied: 'Enviado pero aún no reflejado — verificá en ML.',
    disabled: 'Escritura de promociones deshabilitada.',
    rejected_out_of_range: 'Precio fuera de rango.',
    rejected_unsupported_type: 'Tipo de promoción no soportado.',
    rejected_price_unresolved: 'No se pudo resolver el precio.',
    rejected_promotion_not_found: 'Promoción no encontrada.',
    rejected_read_unavailable: 'Servicio de ML no disponible, reintentá.',
    rejected_by_proxy: 'Rechazado por ML.',
  };
  return map[status] || 'No se pudo confirmar el resultado.';
}

function enrollErrorMessage(err) {
  const httpStatus = err?.response?.status;
  const data = err?.response?.data;
  const detail = data?.detail || data?.error?.message || data?.mensaje;
  if (httpStatus === 409 && data?.status === 'rejected_price_changed') {
    const nuevo =
      data.precio_actual != null ? ` Nuevo precio ML: $ ${formatPrice(data.precio_actual)}.` : '';
    return `La oferta cambió en ML; no se aplicó nada.${nuevo} Recargá el pool.`;
  }
  if (httpStatus === 409) {
    return detail || 'La oferta cambió en ML. No se aplicó nada.';
  }
  if (httpStatus === 403) {
    return detail || 'No autorizado o escritura deshabilitada (promos.escribir).';
  }
  if (httpStatus === 503) {
    return 'Servicio de ML no disponible, reintentá.';
  }
  return detail || 'Error al aplicar la promoción.';
}

function canEnrollPromo(promo, precioSugerido, canWrite) {
  if (!canWrite || promo.pool_applied) return false;
  return buildParaGanarEnrollBody(promo, precioSugerido) != null;
}

export default function ParaGanarPromoPool({ mla, precioSugerido }) {
  const { tienePermiso } = usePermisos();
  const canView = tienePermiso('promos.ver');
  const canWrite = tienePermiso('promos.escribir');
  const [pool, setPool] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [confirmKey, setConfirmKey] = useState(null);
  const [submittingKey, setSubmittingKey] = useState(null);
  const [actionFeedback, setActionFeedback] = useState(null);
  const loadGenRef = useRef(0);

  const loadPool = useCallback(
    async ({ resetFeedback = false } = {}) => {
      const gen = ++loadGenRef.current;
      if (!mla || !canView) {
        setPool([]);
        setError(null);
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      if (resetFeedback) {
        setConfirmKey(null);
        setActionFeedback(null);
      }
      try {
        const [promosRes, criteriosRes] = await Promise.all([
          promocionesAPI.getPromocionesItem(mla),
          api
            .get(`/para-ganar/criterios/${encodeURIComponent(mla)}`)
            .catch(() => ({ data: null })),
        ]);
        if (gen !== loadGenRef.current) return;
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
        if (gen !== loadGenRef.current) return;
        setPool([]);
        if (err.response?.status === 403) {
          setError('No tenés permiso para ver promociones (promos.ver).');
        } else {
          setError('No se pudo cargar el pool de promociones.');
        }
      } finally {
        if (gen === loadGenRef.current) setLoading(false);
      }
    },
    [mla, precioSugerido, canView],
  );

  useEffect(() => {
    loadPool({ resetFeedback: true });
    return () => {
      loadGenRef.current += 1;
    };
  }, [loadPool]);

  const rowKey = (promo) => `${promo.promotion_type}-${promo.promotion_id}`;

  const handleApplyClick = (promo) => {
    const key = rowKey(promo);
    setActionFeedback(null);
    if (confirmKey === key) {
      setConfirmKey(null);
      return;
    }
    setConfirmKey(key);
  };

  const handleConfirmEnroll = async (promo) => {
    const key = rowKey(promo);
    const body = buildParaGanarEnrollBody(promo, precioSugerido);
    if (!body) {
      setActionFeedback({ tone: 'error', message: 'No se puede armar el precio de enroll.' });
      setConfirmKey(null);
      return;
    }
    setSubmittingKey(key);
    setActionFeedback(null);
    try {
      const { data } = await promocionesAPI.postPromocionItem(mla, body);
      setActionFeedback({
        tone: data?.status === 'reconciled_applied' ? 'success' : 'info',
        message: enrollFeedback(data?.status),
      });
      setConfirmKey(null);
      await loadPool();
    } catch (err) {
      setActionFeedback({ tone: 'error', message: enrollErrorMessage(err) });
      setConfirmKey(null);
    } finally {
      setSubmittingKey(null);
    }
  };

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
        Hasta un SMART, un DEAL/campaña y un Premium (nombre). DEAL/campaña se
        inscriben al precio sugerido (clamp al rango). SMART usa el precio ML
        visto. Requiere promos.escribir.
      </p>
      {loading && <p className={styles.emptyBody}>Cargando promociones…</p>}
      {error && (
        <p className={styles.criteriaFeedbackError} role="alert">
          {error}
        </p>
      )}
      {actionFeedback && (
        <p
          className={
            actionFeedback.tone === 'error'
              ? styles.criteriaFeedbackError
              : styles.criteriaFeedbackOk
          }
          role="status"
        >
          {actionFeedback.message}
        </p>
      )}
      {!loading && !error && pool.length === 0 && (
        <p className={styles.emptyBody}>
          Ninguna candidata encaja con markup/rango del precio sugerido.
        </p>
      )}
      {!loading && pool.length > 0 && (
        <ul className={styles.promoPoolList}>
          {pool.map((promo) => {
            const key = rowKey(promo);
            const writable = canEnrollPromo(promo, precioSugerido, canWrite);
            const confirming = confirmKey === key;
            const submitting = submittingKey === key;
            return (
              <li key={key} className={styles.promoPoolRow}>
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
                    {confirming &&
                    SELLER_PRICED_TYPES.has(promo.promotion_type) &&
                    promo.pool_deal_price != null
                      ? ` · confirmar $ ${formatPrice(promo.pool_deal_price)}`
                      : ''}
                  </div>
                </div>
                <div className={styles.promoApplyActions}>
                  {confirming ? (
                    <>
                      <button
                        type="button"
                        className={styles.promoApplyBtnActive}
                        disabled={submitting}
                        onClick={() => handleConfirmEnroll(promo)}
                      >
                        {submitting ? 'Enviando…' : 'Confirmar'}
                      </button>
                      <button
                        type="button"
                        className={styles.promoApplyBtnActive}
                        disabled={submitting}
                        onClick={() => setConfirmKey(null)}
                      >
                        Cancelar
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className={
                        writable ? styles.promoApplyBtnActive : styles.promoApplyBtn
                      }
                      disabled={!writable || submitting}
                      title={
                        promo.pool_applied
                          ? 'Ya está aplicada en ML'
                          : !canWrite
                            ? 'Requiere permiso promos.escribir'
                            : !writable
                              ? 'Falta precio sugerido o precio ML para enroll'
                              : 'Inscribe con el mismo POST que Productos'
                      }
                      onClick={() => handleApplyClick(promo)}
                    >
                      {promo.pool_applied ? 'Aplicada' : 'Aplicar'}
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
