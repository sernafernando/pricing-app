import { useEffect, useRef, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { ML_PRICED_TYPES, promoDisplayPrice } from './promoDisplayPrice';
import SellInOutMarkupExtra from './SellInOutMarkupExtra';
import { sellInOutText } from './sellInOutMarkup';
import styles from './promociones.module.css';

function formatMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
  return `$${Number(value).toLocaleString('es-AR')}`;
}

// "$17.307,81": always two decimals, for the LIGHTNING allowed range.
function formatRangeMoney(value) {
  return `$${Number(value).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatMarkupPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
  return `${Number(value).toFixed(1)}%`;
}

function markupClass(value) {
  return value !== null && value !== undefined && Number(value) < 0 ? styles.markupNegative : styles.markupNeutral;
}

// Same writable-type contract as MlaPromocionesPanel's APPLICABLE_TYPES.
const WRITABLE_TYPES = new Set(['SELLER_CAMPAIGN', 'DEAL', 'SMART', 'PRE_NEGOTIATED', 'PRICE_MATCHING', 'LIGHTNING']);

// Ofertas relámpago: the operator sets the price and the stock to reserve.
const LIGHTNING = 'LIGHTNING';

// Default LIGHTNING price: the price its row shows (promoDisplayPrice: a candidate's
// `suggested_discounted_price` within [min, max], else `price`). Clamped to [min, max] again
// only as a guard; with no max, only the min.
function lightningDefaultPrice(promotion) {
  const price = Number(promoDisplayPrice(promotion));
  if (!(price > 0)) return '';
  const { min_discounted_price: min, max_discounted_price: max } = promotion;
  if (max != null && price > max) return max;
  if (min != null && price < min) return min;
  return price;
}

// Default price of the other range types. A DEAL starts at the price its row shows
// (promoDisplayPrice: its max for a candidate); the rest at ML's suggestion. A typed
// price above the max is flagged and blocked by the range check below.
function rangeDefaultPrice(promotion) {
  const start =
    promotion.promotion_type === 'DEAL'
      ? promoDisplayPrice(promotion)
      : (promotion.suggested_discounted_price ?? promotion.price);
  return start ?? promotion.min_discounted_price ?? '';
}

// ML's `stock: {min, max}` for the units to reserve, or null when it does not report it.
function lightningStockRange(promotion) {
  const stock = promotion.payload?.stock;
  if (!Number.isInteger(stock?.min) || !Number.isInteger(stock?.max)) return null;
  return { min: stock.min, max: stock.max };
}

// "10/11 09:00" in Argentina time, or null when the date is missing or unparseable.
function formatDateTime(iso) {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('es-AR', {
      timeZone: 'America/Argentina/Buenos_Aires',
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(date)
      .map((part) => [part.type, part.value]),
  );
  return `${parts.day}/${parts.month} ${parts.hour}:${parts.minute}`;
}

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
 * `label` (optional) renames only the Aplicar trigger (e.g. "Aplicar sugerencia");
 * confirmation, guards and request body stay the same.
 */
function PromoApplyControl({ mla, promotion, onApplied, onReloadNeeded, label }) {
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
  const isLightning = promotion.promotion_type === LIGHTNING;
  // LIGHTNING always takes a typed price, even when ML sends no max (only the min applies then).
  const showsPriceInput = isRangeType || isLightning;
  const stockRange = isLightning ? lightningStockRange(promotion) : null;
  const defaultPrice = isLightning
    ? lightningDefaultPrice(promotion)
    : rangeDefaultPrice(promotion);
  const [stock, setStock] = useState('');
  const [dealPrice, setDealPrice] = useState(defaultPrice);
  const [markup, setMarkup] = useState(null);
  // The same lookup's markup with today's sell in / sell out (promos-markup-sell-in-out); null hides it.
  const [markupSellInOut, setMarkupSellInOut] = useState(null);
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
    // The manual-price markup lookup runs only while the price input is shown:
    // range-type and LIGHTNING enrolls (`showsPriceInput && !isEnrolled`).
    // Skip it entirely for the Desaplicar flow, where no price is submitted.
    if (!showsPriceInput || isEnrolled || phase !== 'confirming') return undefined;

    setMarkupLoading(true);
    const priceForLookup = dealPrice;
    const timer = setTimeout(() => {
      const numericPrice = Number(priceForLookup);
      // Don't query the backend for a price the user can't submit anyway
      // (out of [min,max] or non-numeric) — same bound as `priceOutOfRange`.
      if (
        !Number.isFinite(numericPrice) ||
        numericPrice < promotion.min_discounted_price ||
        (promotion.max_discounted_price != null && numericPrice > promotion.max_discounted_price)
      ) {
        setMarkup(null);
        setMarkupSellInOut(null);
        setMarkupLoading(false);
        return;
      }
      promocionesAPI
        .getMarkupParaPrecio(mla, numericPrice)
        .then((res) => {
          setMarkup(res?.data?.nuestro_markup ?? null);
          setMarkupSellInOut(res?.data?.markup_sell_in_out ?? null);
        })
        .catch(() => {
          setMarkup(null);
          setMarkupSellInOut(null);
        })
        .finally(() => setMarkupLoading(false));
    }, MARKUP_DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [
    dealPrice,
    phase,
    showsPriceInput,
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
    showsPriceInput &&
    (!Number.isFinite(numericDealPrice) ||
      numericDealPrice < promotion.min_discounted_price ||
      (promotion.max_discounted_price != null && numericDealPrice > promotion.max_discounted_price));
  const needsStock = isLightning && !isEnrolled;
  const stockValid =
    stockRange != null && /^\d+$/.test(String(stock)) && Number(stock) >= stockRange.min && Number(stock) <= stockRange.max;
  // A stored row without a max (MLA1865080493 came from another listing, 2026-11-06) does not decide:
  // the backend re-reads the live entry and refuses only if that one has no max either.
  const lightningMaxUnknown = needsStock && promotion.max_discounted_price == null;
  const lightningBlocked = needsStock && !stockValid;

  if (isLightning && promotion.status === 'started') {
    return (
      <span className={styles.applySlot}>ML no permite quitarla una vez iniciada; pausá la publicación para frenarla.</span>
    );
  }

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
    setStock('');
    setMarkup(null);
    setMarkupSellInOut(null);
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
      // No result to report, but the panel should still re-read the mirror:
      // the truth lives there.
      if (onReloadNeeded) onReloadNeeded();
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
    if (showsPriceInput && !isEnrolled && priceOutOfRange) return;
    if (lightningBlocked) return;
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
              ...(showsPriceInput ? { deal_price: numericDealPrice } : {}),
              ...(isLightning ? { stock: Number(stock) } : {}),
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

  const priceInputId = `deal-price-${mla}-${promotion.promotion_id}`;

  // LIGHTNING enroll: a card under its row (approved S9 design), while the row's trigger reads "Cerrar".
  if (phase === 'confirming' && needsStock) {
    const stockInputId = `stock-${mla}-${promotion.promotion_id}`;
    const titleId = `lightning-title-${mla}-${promotion.promotion_id}`;
    const markupLabelId = `lightning-markup-${mla}-${promotion.promotion_id}`;
    const lightningStart = formatDateTime(promotion.start_date);
    const lightningFinish = formatDateTime(promotion.finish_date);
    // ML's optional boost fields live in the stored entry (`payload`), only when boosted_offer is true.
    const mlEntry = promotion.payload || {};
    const boostLine =
      mlEntry.boosted_offer === true && mlEntry.total_price_for_boosted_offer != null
        ? `ML suma ${mlEntry.discount_meli_boosted_percentage ?? '?'}% de descuento extra · el comprador paga ${formatMoney(
            mlEntry.total_price_for_boosted_offer,
          )}`
        : null;
    const rangeText =
      promotion.max_discounted_price != null
        ? `Rango permitido: ${formatRangeMoney(promotion.min_discounted_price)} - ${formatRangeMoney(promotion.max_discounted_price)}`
        : promotion.min_discounted_price != null
          ? `Mínimo permitido: ${formatRangeMoney(promotion.min_discounted_price)}`
          : null;
    return (
      <>
        <button type="button" className={`${styles.applyBtn} ${styles.lightningClose}`} onClick={handleCancel}>
          Cerrar
        </button>
        <div role="group" aria-labelledby={titleId} className={styles.lightningCard}>
          <h5 id={titleId} className={styles.lightningTitle}>
            Aplicar LIGHTNING
          </h5>
          <div className={styles.lightningFields}>
            <div className={styles.lightningField}>
              <label htmlFor={priceInputId} className={styles.lightningLabel}>
                Precio
              </label>
              <span className={styles.lightningInputWrap}>
                <span className={styles.lightningPrefix} aria-hidden="true">
                  $
                </span>
                <input
                  id={priceInputId}
                  type="number"
                  className={styles.lightningInput}
                  value={dealPrice}
                  onChange={handlePriceChange}
                  min={promotion.min_discounted_price}
                  max={promotion.max_discounted_price}
                />
              </span>
              {rangeText && <span className={styles.lightningHint}>{rangeText}</span>}
              {priceOutOfRange && (
                <span className={styles.feedbackError}>
                  {promotion.max_discounted_price != null
                    ? `Precio fuera de rango ($${promotion.min_discounted_price} - $${promotion.max_discounted_price}).`
                    : `Precio fuera de rango (mínimo $${promotion.min_discounted_price}).`}
                </span>
              )}
              {lightningMaxUnknown && (
                <span className={styles.lightningHint}>
                  ML no informó el precio máximo; se confirma con ML al aplicar.
                </span>
              )}
            </div>
            <div className={styles.lightningMarkup}>
              <span id={markupLabelId} className={styles.lightningMarkupLabel}>
                Tu markup
              </span>
              <output aria-labelledby={markupLabelId} className={`${styles.lightningMarkupValue} ${markupClass(markup)}`}>
                {markupLoading ? 'Calculando...' : markup != null ? `${markup.toFixed(1)}%` : '—'}
              </output>
              {!markupLoading && markup != null && <SellInOutMarkupExtra value={markupSellInOut} />}
            </div>
            <div className={styles.lightningField}>
              <label htmlFor={stockInputId} className={styles.lightningLabel}>
                Stock a reservar
              </label>
              <span className={styles.lightningInputWrap}>
                <input
                  id={stockInputId}
                  type="number"
                  step="1"
                  className={styles.lightningInput}
                  value={stock}
                  onChange={(e) => setStock(e.target.value)}
                  min={stockRange?.min}
                  max={stockRange?.max}
                  placeholder="unidades"
                />
              </span>
              {stockRange ? (
                <span className={styles.lightningHint}>
                  Entre {stockRange.min} y {stockRange.max} unidades
                </span>
              ) : (
                <span className={styles.feedbackError}>
                  ML no informa el stock a reservar de esta oferta; no se puede aplicar.
                </span>
              )}
            </div>
          </div>
          {lightningStart && lightningFinish && (
            <span className={styles.lightningHint}>
              Empieza {lightningStart} · termina {lightningFinish}
            </span>
          )}
          {boostLine && <span className={styles.lightningHint}>{boostLine}</span>}
          <div role="note" className={styles.lightningWarning}>
            <AlertTriangle size={16} aria-hidden="true" className={styles.lightningWarningIcon} />
            <span>
              Una vez que empieza no se puede quitar (solo pausando la publicación). La oferta termina cuando se vende el
              stock reservado.
            </span>
          </div>
          <div className={styles.lightningActions}>
            <button type="button" className={styles.lightningCancelBtn} onClick={handleCancel}>
              Cancelar
            </button>
            <button
              type="button"
              className={styles.lightningConfirmBtn}
              onClick={() => handleConfirm()}
              disabled={priceOutOfRange || lightningBlocked}
            >
              Sí, aplicar
            </button>
          </div>
        </div>
      </>
    );
  }

  // Every other confirmation (and a LIGHTNING Desaplicar): an inline line under the row.
  if (phase === 'confirming') {
    return (
      <span className={styles.applyConfirm}>
        <span>¿{actionLabelCapitalized} esta promoción?</span>
        {showsPriceInput && !isEnrolled && (
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
                  ? `Tu markup: ${markup.toFixed(1)}%${sellInOutText(markupSellInOut)}`
                  : null}
            </span>
            {priceOutOfRange && (
              <span className={styles.feedbackError}>
                {promotion.max_discounted_price != null
                  ? `Precio fuera de rango ($${promotion.min_discounted_price} - $${promotion.max_discounted_price}).`
                  : `Precio fuera de rango (mínimo $${promotion.min_discounted_price}).`}
              </span>
            )}
          </span>
        )}
        <button
          type="button"
          className={`${styles.applyConfirmBtn} ${isEnrolled ? styles.removeConfirmBtn : ''}`}
          onClick={() => handleConfirm()}
          disabled={showsPriceInput && !isEnrolled && priceOutOfRange}
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
        {!isEnrolled && label ? label : actionLabelCapitalized}
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
