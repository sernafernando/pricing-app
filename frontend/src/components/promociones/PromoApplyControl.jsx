import { useEffect, useState } from 'react';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import styles from './promociones.module.css';

// Same writable-type contract as MlaPromocionesPanel's APPLICABLE_TYPES.
const WRITABLE_TYPES = new Set(['SELLER_CAMPAIGN', 'DEAL', 'SMART', 'PRE_NEGOTIATED']);

// Debounce delay (ms) for the manual-price -> markup lookup.
const MARKUP_DEBOUNCE_MS = 400;

// EnrollResult/RemoveResult.status -> feedback message + tone. Eventual-
// consistency-safe: never claim a confirmed state from the immediate response.
// The success verb depends on the action (aplicada vs desaplicada).
function feedbackFor(status, isApplied) {
  const verb = isApplied ? 'desaplicada' : 'aplicada';
  const map = {
    submitted: { tone: 'info', message: 'Enviado — puede tardar en reflejarse (la tabla es la fuente de verdad).' },
    ambiguous: { tone: 'warn', message: 'Enviado, estado por confirmar — verificá en ML.' },
    reconciled_applied: { tone: 'success', message: `Promoción ${verb}.` },
    reconciled_not_applied: { tone: 'warn', message: 'Enviado pero aún no reflejado — verificá en ML.' },
    disabled: { tone: 'error', message: 'Escritura deshabilitada.' },
    rejected_out_of_range: { tone: 'error', message: 'Precio fuera de rango.' },
    rejected_unsupported_type: { tone: 'error', message: 'Tipo de promoción no soportado.' },
    rejected_price_unresolved: { tone: 'error', message: 'No se pudo resolver el precio.' },
    rejected_promotion_not_found: { tone: 'error', message: 'Promoción no encontrada.' },
    rejected_read_unavailable: { tone: 'error', message: 'Servicio de ML no disponible, reintentá.' },
    rejected_by_proxy: { tone: 'error', message: 'Rechazado por ML.' },
  };
  return map[status] || { tone: 'error', message: 'No se pudo confirmar el resultado.' };
}

function feedbackForError(err, actionLabel = 'aplicar') {
  const httpStatus = err?.response?.status;
  const detail = err?.response?.data?.detail;
  if (httpStatus === 403) {
    return { tone: 'error', message: detail || 'No autorizado o función deshabilitada.' };
  }
  if (httpStatus === 404 || httpStatus === 405 || httpStatus === 501) {
    return { tone: 'unavailable', message: `${actionLabel === 'aplicar' ? 'Aplicar' : 'Desaplicar'} no disponible.` };
  }
  if (httpStatus === 422) {
    return { tone: 'error', message: detail || 'Solicitud rechazada.' };
  }
  if (httpStatus === 503) {
    return { tone: 'error', message: 'Servicio de ML no disponible, reintentá.' };
  }
  return { tone: 'error', message: `Error al ${actionLabel} la promoción.` };
}

/**
 * Apply control for a single writable promotion row (SELLER_CAMPAIGN, DEAL, SMART, PRE_NEGOTIATED).
 * Renders inline inside `MlaPromocionesPanel`. Triggers a REAL ML price write:
 * requires explicit confirmation, never auto-retries, never claims a confirmed
 * "aplicado" state from the immediate response (eventual consistency).
 */
function PromoApplyControl({ mla, promotion, onApplied }) {
  const { tienePermiso } = usePermisos();
  const [phase, setPhase] = useState('idle'); // idle | confirming | submitting | done
  const [feedback, setFeedback] = useState(null); // { tone, message } | null
  const [unavailable, setUnavailable] = useState(false);

  // Manual price input — only for range-based writable types (SELLER_CAMPAIGN,
  // DEAL). SMART/PRE_NEGOTIATED have their price fixed/derived by ML.
  const isRangeType =
    promotion.min_discounted_price != null && promotion.max_discounted_price != null;
  const defaultPrice = promotion.suggested_discounted_price ?? promotion.price ?? promotion.min_discounted_price ?? '';
  const [dealPrice, setDealPrice] = useState(defaultPrice);
  const [markup, setMarkup] = useState(null);
  const [markupLoading, setMarkupLoading] = useState(false);

  useEffect(() => {
    if (!isRangeType || phase !== 'confirming') return undefined;

    setMarkupLoading(true);
    const priceForLookup = dealPrice;
    const timer = setTimeout(() => {
      const numericPrice = Number(priceForLookup);
      if (!Number.isFinite(numericPrice) || numericPrice <= 0) {
        setMarkup(null);
        setMarkupLoading(false);
        return;
      }
      promocionesAPI
        .getMarkupParaPrecio(mla, numericPrice)
        .then((res) => setMarkup(res?.data?.nuestro_markup ?? null))
        .catch(() => setMarkup(null))
        .finally(() => setMarkupLoading(false));
    }, MARKUP_DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [dealPrice, phase, isRangeType, mla]);

  const hasPermission = tienePermiso('promos.escribir');
  const isWritableType = WRITABLE_TYPES.has(promotion.promotion_type);
  const isApplied = promotion.status === 'started';
  const actionLabel = isApplied ? 'desaplicar' : 'aplicar';
  const actionLabelCapitalized = isApplied ? 'Desaplicar' : 'Aplicar';

  const numericDealPrice = Number(dealPrice);
  const priceOutOfRange =
    isRangeType &&
    (!Number.isFinite(numericDealPrice) ||
      numericDealPrice < promotion.min_discounted_price ||
      numericDealPrice > promotion.max_discounted_price);

  if (!isWritableType) {
    return <span className={styles.applySlot}>Lo maneja ML</span>;
  }

  if (!hasPermission) {
    return (
      <span className={styles.applySlot} title="Sin permiso para aplicar promociones">
        Sin permiso
      </span>
    );
  }

  if (unavailable) {
    return <span className={styles.applySlot}>{actionLabelCapitalized} no disponible</span>;
  }

  const handleActionClick = () => {
    setFeedback(null);
    setDealPrice(defaultPrice);
    setMarkup(null);
    setPhase('confirming');
  };

  const handleCancel = () => {
    setPhase('idle');
  };

  const handlePriceChange = (e) => {
    setDealPrice(e.target.value);
  };

  const handleConfirm = async () => {
    if (isRangeType && priceOutOfRange) return;

    setPhase('submitting');
    try {
      const data = isApplied
        ? await promocionesAPI
            .deletePromocionItem(mla, {
              promotion_id: promotion.promotion_id,
              promotion_type: promotion.promotion_type,
            })
            .then((res) => res.data)
        : await promocionesAPI
            .postPromocionItem(mla, {
              promotion_id: promotion.promotion_id,
              promotion_type: promotion.promotion_type,
              ...(isRangeType ? { deal_price: numericDealPrice } : {}),
            })
            .then((res) => res.data);
      setFeedback(feedbackFor(data?.status, isApplied));
      setPhase('done');
      if (onApplied) onApplied(data);
    } catch (err) {
      const fb = feedbackForError(err, actionLabel);
      if (fb.tone === 'unavailable') {
        setUnavailable(true);
        setPhase('idle');
        return;
      }
      setFeedback(fb);
      setPhase('done');
    }
  };

  if (phase === 'confirming') {
    const priceInputId = `deal-price-${mla}-${promotion.promotion_id}`;
    return (
      <span className={styles.applyConfirm}>
        <span>¿{actionLabelCapitalized} esta promoción?</span>
        {isRangeType && !isApplied && (
          <span className={styles.priceInput}>
            <label htmlFor={priceInputId}>Precio</label>
            <input
              id={priceInputId}
              type="number"
              value={dealPrice}
              onChange={handlePriceChange}
              min={promotion.min_discounted_price}
              max={promotion.max_discounted_price}
            />
            <span className={styles.priceMarkup}>
              {markupLoading
                ? 'Calculando markup...'
                : markup != null
                  ? `Tu markup: ${markup.toFixed(1)}%`
                  : null}
            </span>
            {priceOutOfRange && (
              <span className={styles.feedbackError}>
                Precio fuera de rango (${promotion.min_discounted_price} - ${promotion.max_discounted_price}).
              </span>
            )}
          </span>
        )}
        <button
          type="button"
          className={styles.applyConfirmBtn}
          onClick={handleConfirm}
          disabled={isRangeType && !isApplied && priceOutOfRange}
        >
          Sí, {actionLabel}
        </button>
        <button type="button" className={styles.applyCancelBtn} onClick={handleCancel}>
          Cancelar
        </button>
      </span>
    );
  }

  if (phase === 'submitting') {
    return (
      <button type="button" className={styles.applySlot} disabled>
        {isApplied ? 'Desaplicando...' : 'Aplicando...'}
      </button>
    );
  }

  return (
    <span className={styles.applyWrapper}>
      <button type="button" className={styles.applyBtn} onClick={handleActionClick}>
        {actionLabelCapitalized}
      </button>
      {feedback && (
        <span
          className={
            feedback.tone === 'success'
              ? styles.feedbackSuccess
              : feedback.tone === 'warn'
                ? styles.feedbackWarn
                : styles.feedbackError
          }
        >
          {feedback.message}
        </span>
      )}
    </span>
  );
}

export default PromoApplyControl;
