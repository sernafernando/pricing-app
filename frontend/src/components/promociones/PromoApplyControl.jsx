import { useEffect, useRef, useState } from 'react';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { ML_PRICED_TYPES, promoDisplayPrice } from './promoDisplayPrice';
import styles from './promociones.module.css';

function formatMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
  return `$${Number(value).toLocaleString('es-AR')}`;
}

function formatMarkupPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
  return `${Number(value).toFixed(1)}%`;
}

function markupClass(value) {
  return value !== null && value !== undefined && Number(value) < 0 ? styles.markupNegative : styles.markupNeutral;
}

// Same writable-type contract as MlaPromocionesPanel's APPLICABLE_TYPES.
const WRITABLE_TYPES = new Set(['SELLER_CAMPAIGN', 'DEAL', 'SMART', 'PRE_NEGOTIATED', 'PRICE_MATCHING']);

// Debounce delay (ms) for the manual-price -> markup lookup.
const MARKUP_DEBOUNCE_MS = 400;

// Same client-side gate the server uses for its immediate/queued refresh
// (spec's original state-changing definition — the FE intentionally does
// NOT widen this to include `ambiguous`, unlike the server's refresh trigger
// set, since the FE can't know the server reconciled it as applied).
const PROVISIONAL_TRIGGER_STATUSES = new Set(['submitted', 'reconciled_applied']);

// Safety timeout so a provisional indicator never lingers forever if the
// table is never freshened (e.g. the ml-webhook /refresh route is absent).
const PROVISIONAL_SAFETY_TIMEOUT_MS = 90000;

// EnrollResult/RemoveResult.status -> feedback message + tone. Eventual-
// consistency-safe: never claim a confirmed state from the immediate response.
// The success verb depends on the action (aplicada vs desaplicada).
function feedbackFor(status, isEnrolled) {
  const verb = isEnrolled ? 'desaplicada' : 'aplicada';
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
  // The app-wide exception handler wraps a string detail as
  // `{error: {code, message}}` and returns a dict detail as the body root;
  // `detail` is kept for any route that still answers the FastAPI default.
  const data = err?.response?.data;
  const detail = data?.detail || data?.error?.message || data?.mensaje;
  if (httpStatus === 409) {
    return { tone: 'error', message: detail || 'La oferta cambió en ML. No se aplicó nada; actualizá el panel.' };
  }
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
  // Local, provisional-only indicator — structurally CANNOT set the
  // confirmed "Aplicada"/"Programada" badges, which live in
  // MlaPromocionesPanel and are driven solely by promo.application_status.
  // 'applying' | 'removing' | null.
  const [pendingKind, setPendingKind] = useState(null);
  // 409 "price changed": ML moved the offer since the operator saw it.
  // { precioActual, markupActual, precioVistoAnterior } | null
  const [reprice, setReprice] = useState(null);
  // Post-apply check: { kind: 'difiere' | 'sin_verificar', precioAplicado,
  // precioConfirmado, markupAplicado } | null
  const [priceAlert, setPriceAlert] = useState(null);
  const safetyTimeoutRef = useRef(null);

  const clearPendingSafetyTimeout = () => {
    if (safetyTimeoutRef.current) {
      clearTimeout(safetyTimeoutRef.current);
      safetyTimeoutRef.current = null;
    }
  };

  // Clear the provisional indicator once the reloaded props reflect the new
  // confirmed state (the panel re-maps promo data on reload -> new props
  // flow down here). This NEVER sets the confirmed badge itself — it only
  // clears our own local, non-confirming indicator.
  useEffect(() => {
    setPendingKind(null);
    clearPendingSafetyTimeout();
  }, [promotion.status, promotion.application_status]);

  // Cleanup on unmount.
  useEffect(() => () => clearPendingSafetyTimeout(), []);

  // Manual price input — only for range-based writable types (SELLER_CAMPAIGN,
  // DEAL). SMART/PRE_NEGOTIATED have their price fixed/derived by ML.
  const isRangeType =
    promotion.min_discounted_price != null && promotion.max_discounted_price != null;
  const defaultPrice = promotion.suggested_discounted_price ?? promotion.price ?? promotion.min_discounted_price ?? '';
  const [dealPrice, setDealPrice] = useState(defaultPrice);
  const [markup, setMarkup] = useState(null);
  const [markupLoading, setMarkupLoading] = useState(false);

  // `started` and `pending` both mean "already enrolled" — pending is
  // offered but not yet live at ML, so the only valid action is Desaplicar
  // (remove), same as started. Only `candidate` offers Aplicar.
  const isEnrolled = promotion.status === 'started' || promotion.status === 'pending';

  // ML-priced offers (SMART & co.) are applied only at the price the operator
  // SAW: the same value the panel row shows. The backend re-reads ML's live
  // offer and refuses (409) if it moved — incident 2026-10-05.
  const isMlPricedApply = ML_PRICED_TYPES.has(promotion.promotion_type) && !isEnrolled;
  const seenPrice = promoDisplayPrice(promotion);
  const seenMarkup = promotion.nuestro_markup ?? null;
  const missingSeenPrice = isMlPricedApply && !(Number(seenPrice) > 0);

  useEffect(() => {
    // The manual-price markup lookup only applies to the range-type enroll
    // flow — the price input is rendered only when `isRangeType && !isEnrolled`.
    // Skip it entirely for the Desaplicar flow, where no price is submitted.
    if (!isRangeType || isEnrolled || phase !== 'confirming') return undefined;

    setMarkupLoading(true);
    const priceForLookup = dealPrice;
    const timer = setTimeout(() => {
      const numericPrice = Number(priceForLookup);
      // Don't query the backend for a price the user can't submit anyway
      // (out of [min,max] or non-numeric) — same bound as `priceOutOfRange`.
      if (
        !Number.isFinite(numericPrice) ||
        numericPrice < promotion.min_discounted_price ||
        numericPrice > promotion.max_discounted_price
      ) {
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
  }, [
    dealPrice,
    phase,
    isRangeType,
    isEnrolled,
    mla,
    promotion.min_discounted_price,
    promotion.max_discounted_price,
  ]);

  const hasPermission = tienePermiso('promos.escribir');
  const isWritableType = WRITABLE_TYPES.has(promotion.promotion_type);
  const actionLabel = isEnrolled ? 'desaplicar' : 'aplicar';
  const actionLabelCapitalized = isEnrolled ? 'Desaplicar' : 'Aplicar';

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
    setPriceAlert(null);
    setDealPrice(defaultPrice);
    setMarkup(null);
    setPhase('confirming');
  };

  const handleCancel = () => {
    setReprice(null);
    setPhase('idle');
  };

  const markProvisional = (status, removing) => {
    if (!PROVISIONAL_TRIGGER_STATUSES.has(status)) return;
    setPendingKind(removing ? 'removing' : 'applying');
    clearPendingSafetyTimeout();
    safetyTimeoutRef.current = setTimeout(() => {
      safetyTimeoutRef.current = null;
      setPendingKind(null);
    }, PROVISIONAL_SAFETY_TIMEOUT_MS);
  };

  // Post-apply check result -> red alert (ML applied another price) or an
  // amber "could not verify". `precio_difiere: null` is NOT "fine".
  const priceAlertFrom = (data, confirmedPrice) => {
    if (!isMlPricedApply || data?.status !== 'submitted') return null;
    if (data.precio_difiere === true) {
      return {
        kind: 'difiere',
        precioAplicado: data.precio_aplicado,
        precioConfirmado: data.precio_confirmado ?? confirmedPrice,
        markupAplicado: data.markup_aplicado,
      };
    }
    if (data.precio_difiere === false) return null;
    return { kind: 'sin_verificar', precioConfirmado: data.precio_confirmado ?? confirmedPrice };
  };

  // One-click removal from the post-apply alert: the existing remove flow
  // (DELETE /promociones/item/{mla}), no extra confirmation step.
  const handleQuitarPromo = async () => {
    setPhase('submitting');
    try {
      const data = await promocionesAPI
        .deletePromocionItem(mla, {
          promotion_id: promotion.promotion_id,
          promotion_type: promotion.promotion_type,
        })
        .then((res) => res.data);
      setFeedback(feedbackFor(data?.status, true));
      // Only a removal that went through clears the alert. Anything else
      // (ambiguous, reconciled_not_applied, ...) may leave the promo live at
      // the wrong price, so the alert and its button stay.
      if (PROVISIONAL_TRIGGER_STATUSES.has(data?.status)) setPriceAlert(null);
      markProvisional(data?.status, true);
      if (onApplied) onApplied(data);
    } catch (err) {
      // Keep the alert: the promo may still be live at the wrong price.
      setFeedback(feedbackForError(err, 'desaplicar'));
      // Still let the panel re-read the mirror: the truth lives there.
      if (onApplied) onApplied(null);
    }
    setPhase('done');
  };

  const handlePriceChange = (e) => {
    setDealPrice(e.target.value);
  };

  // `seen` overrides the price/markup the operator confirms — used when they
  // accept ML's NEW price after a 409, so the re-send is still guarded
  // against a further change.
  const handleConfirm = async (seen = { precio: seenPrice, markup: seenMarkup }) => {
    if (isRangeType && priceOutOfRange) return;
    if (missingSeenPrice && !(Number(seen.precio) > 0)) return;

    setPhase('submitting');
    setReprice(null);
    try {
      const data = isEnrolled
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
              ...(isMlPricedApply
                ? {
                    precio_visto: Number(seen.precio),
                    ...(seen.markup !== null && seen.markup !== undefined ? { markup_visto: seen.markup } : {}),
                  }
                : {}),
            })
            .then((res) => res.data);
      setFeedback(feedbackFor(data?.status, isEnrolled));
      setPriceAlert(isEnrolled ? null : priceAlertFrom(data, Number(seen.precio)));
      setPhase('done');
      markProvisional(data?.status, isEnrolled);
      if (onApplied) onApplied(data);
    } catch (err) {
      const data = err?.response?.data;
      if (err?.response?.status === 409 && data?.status === 'rejected_price_changed') {
        // ML moved the offer. Nothing was applied: show the new price and
        // markup and ask again. Never apply silently.
        setReprice({
          precioActual: data.precio_actual,
          markupActual: data.markup_actual ?? null,
          precioVistoAnterior: data.precio_visto ?? seen.precio,
        });
        setPhase('repricing');
        return;
      }
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

  if (phase === 'repricing' && reprice) {
    const nuevoPrecio = formatMoney(reprice.precioActual);
    const nuevoMarkup = formatMarkupPct(reprice.markupActual);
    return (
      <span className={styles.applyConfirm}>
        <span className={styles.feedbackWarn}>
          ML cambió el precio: viste {formatMoney(reprice.precioVistoAnterior)}, ahora es {nuevoPrecio}{' '}
          <span data-testid="markup-actual" className={markupClass(reprice.markupActual)}>
            (markup {nuevoMarkup})
          </span>
          . No se aplicó nada.
        </span>
        <span>
          ¿Aplicar igual a {nuevoPrecio} (markup {nuevoMarkup})?
        </span>
        <button
          type="button"
          className={styles.applyConfirmBtn}
          onClick={() => handleConfirm({ precio: reprice.precioActual, markup: reprice.markupActual })}
        >
          Sí, aplicar a {nuevoPrecio}
        </button>
        <button type="button" className={styles.applyCancelBtn} onClick={handleCancel}>
          Cancelar
        </button>
      </span>
    );
  }

  if (phase === 'confirming' && missingSeenPrice) {
    return (
      <span className={styles.applyConfirm}>
        <span className={styles.feedbackError}>
          No hay un precio para confirmar en esta oferta; actualizá el panel antes de aplicarla.
        </span>
        <button type="button" className={styles.applyCancelBtn} onClick={handleCancel}>
          Cancelar
        </button>
      </span>
    );
  }

  if (phase === 'confirming') {
    const priceInputId = `deal-price-${mla}-${promotion.promotion_id}`;
    return (
      <span className={styles.applyConfirm}>
        <span>¿{actionLabelCapitalized} esta promoción?</span>
        {isRangeType && !isEnrolled && (
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
          className={`${styles.applyConfirmBtn} ${isEnrolled ? styles.removeConfirmBtn : ''}`}
          onClick={() => handleConfirm()}
          disabled={isRangeType && !isEnrolled && priceOutOfRange}
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
        {isEnrolled ? 'Desaplicando...' : 'Aplicando...'}
      </button>
    );
  }

  return (
    <span className={styles.applyWrapper}>
      <button
        type="button"
        className={`${styles.applyBtn} ${isEnrolled ? styles.removeBtn : ''}`}
        onClick={handleActionClick}
      >
        {actionLabelCapitalized}
      </button>
      {pendingKind && (
        <span className={styles.provisionalPending} data-testid="provisional-indicator">
          {pendingKind === 'applying' ? 'Aplicando…' : 'Desaplicando…'}
        </span>
      )}
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
      {priceAlert?.kind === 'difiere' && (
        <span role="alert" className={styles.priceAlert}>
          ML aplicó {formatMoney(priceAlert.precioAplicado)}{' '}
          <span className={markupClass(priceAlert.markupAplicado)}>
            (markup {formatMarkupPct(priceAlert.markupAplicado)})
          </span>
          , distinto del precio que confirmaste ({formatMoney(priceAlert.precioConfirmado)}).
          <button type="button" className={styles.priceAlertBtn} onClick={handleQuitarPromo}>
            Quitar promo
          </button>
        </span>
      )}
      {priceAlert?.kind === 'sin_verificar' && (
        <span className={styles.feedbackWarn}>
          No se pudo verificar el precio aplicado: ML no lo devolvió. Confirmá en ML que quedó en{' '}
          {formatMoney(priceAlert.precioConfirmado)}.
        </span>
      )}
    </span>
  );
}

export default PromoApplyControl;
