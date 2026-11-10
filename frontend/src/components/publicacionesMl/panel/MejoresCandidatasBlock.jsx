import { useEffect, useRef, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { formatAmount } from '../../../utils/ventasMlFormat';
import { errorText } from '../../pricing/priceWrites';
import { promocionesAPI } from '../../../services/api';
import { resolvePromoName } from '../../promociones/resolvePromoName';
import { ML_PRICED_TYPES, promoDisplayPrice } from '../../promociones/promoDisplayPrice';
import PromoApplyControl from '../../promociones/PromoApplyControl';
import SellInOutMarkupExtra from '../../promociones/SellInOutMarkupExtra';
import { sellInOutText } from '../../promociones/sellInOutMarkup';
import {
  CHOOSER_SLOT_LABELS,
  baselineMarkupFromPromos,
  baselineSellInOutFromPromos,
  hasPickedSlot,
  pickMejoresCandidatas,
  slotEntries,
} from './pickPonerPreciosPromos';
import promoStyles from '../../promociones/promociones.module.css';
import styles from './panel.module.css';

// Same per-type badge hue as the Promos tab rows (MlaPromocionesPanel TYPE_BADGE_CLASS).
const SLOT_BADGE = {
  SMART: promoStyles.badgeTypeSmart,
  DEAL: promoStyles.badgeTypeDeal,
  PRE_NEGOTIATED: promoStyles.badgeTypePreNegotiated,
  PRICE_MATCHING: promoStyles.badgeTypePriceMatching,
  LIGHTNING: promoStyles.badgeTypeLightning,
  SMART_LIGHTNING: promoStyles.badgeTypeSmartLightning,
  SELLER_CAMPAIGN: promoStyles.badgeTypeSellerCampaign,
};

const pct = (value) => `${formatAmount(value)}%`;

function markupTone(value) {
  return value != null && Number(value) < 0 ? styles.mejoresMarkupNegative : styles.mejoresMarkupPositive;
}

/**
 * An apply went through cleanly: sent or confirmed, and (for an ML-priced offer) ML applied the
 * price the operator confirmed. Anything else keeps the pub open so its feedback stays visible.
 */
function appliedCleanly(promo, data) {
  if (data?.status === 'reconciled_applied') return true;
  if (data?.status !== 'submitted') return false;
  return !ML_PRICED_TYPES.has(promo.promotion_type) || data.precio_difiere === false;
}

/**
 * The best candidate per writable MeLi type for a pub already flagged hay_mejores, as cards.
 * Mount only when the operator can write promos (discard/apply need it).
 * "Aplicar sugerencia" is the row's PromoApplyControl (same confirmation, guards and body; a
 * LIGHTNING opens its irreversible-offer card with the stock prefilled at ML's minimum);
 * `onLeavePub` runs only after a clean apply; without it, a clean apply reloads the candidates
 * so the applied promo drops out. `onSuggested(ids)` reports the suggested promotion ids so the
 * Promos tab can mark them. Calls onUnavailable only when baseline markup cannot be computed
 * (optional parent signal). A hard load failure stays mounted with the error and
 * "Descartar sugerencia" and does not call onUnavailable. MODO unlocks Nuevo precio only via
 * onDismissed (Descartar), so neither path can hide the failure by unmounting early.
 */
export default function MejoresCandidatasBlock({
  itemId,
  baselinePrice,
  onWritten,
  onLeavePub,
  onDismissed,
  onUnavailable,
  onSuggested,
}) {
  const [loading, setLoading] = useState(true);
  const [slots, setSlots] = useState(null);
  const [baselineMarkup, setBaselineMarkup] = useState(null);
  const [baselineSellInOut, setBaselineSellInOut] = useState(null);
  const [message, setMessage] = useState(null);
  const [descartando, setDescartando] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  // Bumped after a clean apply that stays on the pub: re-reads the candidates.
  const [reloadToken, setReloadToken] = useState(0);
  const onUnavailableRef = useRef(onUnavailable);
  onUnavailableRef.current = onUnavailable;
  const onSuggestedRef = useRef(onSuggested);
  onSuggestedRef.current = onSuggested;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setMessage(null);
      setUnavailable(false);
      try {
        const promoRes = await promocionesAPI.getPromocionesItem(itemId);
        if (cancelled) return;
        const promotions = promoRes?.data?.promotions ?? promoRes?.data?.promociones ?? [];
        // Co-funded started (SMART / PRE_NEGOTIATED / PRICE_MATCHING) matching
        // sale → same markup as the promo card; else plain getMarkupParaPrecio.
        let markup = baselineMarkupFromPromos(promotions, baselinePrice);
        let sellInOut = baselineSellInOutFromPromos(promotions, baselinePrice);
        if (markup == null && baselinePrice != null && Number.isFinite(Number(baselinePrice))) {
          try {
            const res = await promocionesAPI.getMarkupParaPrecio(itemId, Number(baselinePrice));
            markup = res?.data?.nuestro_markup ?? null;
            sellInOut = res?.data?.markup_sell_in_out ?? null;
          } catch {
            markup = null;
          }
        }
        if (cancelled) return;
        if (markup == null) {
          setUnavailable(true);
          // Nothing is suggested any more: no row in the Promos tab stays marked Sugerida.
          onSuggestedRef.current?.([]);
          onUnavailableRef.current?.();
          return;
        }
        setBaselineMarkup(markup);
        setBaselineSellInOut(sellInOut);
        const picked = pickMejoresCandidatas(promotions, {
          baselinePrice: Number(baselinePrice),
          // Compared like the backend flag (S5): with sell in / sell out only when both sides have it.
          baselineMarkup: markup,
          baselineSellInOut: sellInOut,
        });
        setSlots(hasPickedSlot(picked) ? picked : null);
        onSuggestedRef.current?.(slotEntries(picked).map(([, promo]) => promo.promotion_id));
      } catch (err) {
        if (!cancelled) {
          // Keep mounted with the error: do not call onUnavailable (MODO would unmount and hide it).
          setMessage({ tone: 'error', text: errorText(err, 'No se pudieron cargar las candidatas.') });
          setUnavailable(true);
          onSuggestedRef.current?.([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [itemId, baselinePrice, reloadToken]);

  const discard = async () => {
    if (descartando) return;
    setDescartando(true);
    setMessage(null);
    try {
      await promocionesAPI.descartarHayMejores(itemId);
      onWritten?.();
      onDismissed?.();
    } catch (err) {
      setMessage({ tone: 'error', text: errorText(err, 'No se pudo descartar.') });
    } finally {
      setDescartando(false);
    }
  };

  const entries = slotEntries(slots);
  const lead = (extra) => (
    <p className={styles.ponerPreciosMejoresLead}>
      <Sparkles size={14} aria-hidden="true" className={styles.mejoresIcon} />
      <span>
        Hay candidatas mejores que el precio vigente en MeLi.
        {extra}
      </span>
    </p>
  );
  const vigente =
    baselineMarkup != null ? (
      <>
        {' '}
        Markup vigente ~ <span className={markupTone(baselineMarkup)}>{formatAmount(baselineMarkup)}%</span>
        {sellInOutText(baselineSellInOut, pct)}.
      </>
    ) : null;
  const discardButton = (
    <button type="button" className="btn-tesla ghost sm" disabled={descartando} onClick={discard}>
      {descartando ? 'Descartando…' : 'Descartar sugerencia'}
    </button>
  );

  return (
    <div className={styles.ponerPreciosMejores} role="region" aria-label="Candidatas mejores">
      {loading ? (
        <p className={styles.ponerPreciosOk} role="status">
          Cargando candidatas…
        </p>
      ) : unavailable ? (
        <>
          {lead(null)}
          <span>{discardButton}</span>
        </>
      ) : entries.length > 0 ? (
        <>
          {lead(vigente)}
          <ul className={styles.ponerPreciosChoices}>
            {entries.map(([slot, promo], index) => {
              const price = promoDisplayPrice(promo);
              return (
                <li key={slot} className={styles.mejoresCard} role="group" aria-label={`Promo sugerida ${CHOOSER_SLOT_LABELS[slot] || slot}`}>
                  <span className={`${promoStyles.badge} ${SLOT_BADGE[slot] || promoStyles.badgeTypeNeutral}`}>
                    {CHOOSER_SLOT_LABELS[slot] || slot}
                  </span>
                  <span className={styles.mejoresMain}>
                    <span className={styles.mejoresEyebrow}>Promo sugerida</span>
                    <span className={styles.mejoresName}>{resolvePromoName(promo) || promo.promotion_id}</span>
                  </span>
                  <span className={styles.mejoresFigure}>
                    <span className={styles.mejoresEyebrow}>Precio</span>
                    <span className={styles.mejoresValue}>{price != null ? `$ ${formatAmount(price)}` : '—'}</span>
                  </span>
                  <span className={styles.mejoresFigure}>
                    <span className={styles.mejoresEyebrow}>Markup</span>
                    <span className={`${styles.mejoresValue} ${markupTone(promo.nuestro_markup)}`}>
                      {promo.nuestro_markup != null ? `${formatAmount(promo.nuestro_markup)}%` : '—'}
                    </span>
                    <SellInOutMarkupExtra value={promo.markup_sell_in_out} format={pct} />
                  </span>
                  <span className={styles.mejoresActions}>
                    {index === 0 && discardButton}
                    <PromoApplyControl
                      mla={itemId}
                      promotion={promo}
                      label="Aplicar sugerencia"
                      initialStock={slot === 'LIGHTNING' ? promo.payload?.stock?.min : undefined}
                      onApplied={(data) => {
                        onWritten?.();
                        if (!appliedCleanly(promo, data)) return;
                        if (onLeavePub) onLeavePub();
                        else setReloadToken((token) => token + 1);
                      }}
                      onReloadNeeded={onWritten}
                    />
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      ) : (
        <>
          <p className={styles.ponerPreciosOk} role="status">
            No hay candidatas aplicables (SMART, DEAL, PRE_NEGOTIATED, PRICE_MATCHING, LIGHTNING, SELLER_CAMPAIGN
            Premium del mes) que superen el precio vigente
            {baselineMarkup != null
              ? ` (markup vigente ~ ${formatAmount(baselineMarkup)}%${sellInOutText(baselineSellInOut, pct)})`
              : ''}
            .
            Podés descartar el aviso si quedó desactualizado.
          </p>
          <span>{discardButton}</span>
        </>
      )}
      {message && (
        <p className={message.tone === 'error' ? styles.ponerPreciosError : styles.ponerPreciosOk} role="status">
          {message.text}
        </p>
      )}
    </div>
  );
}
