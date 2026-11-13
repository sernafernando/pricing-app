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
  comparableMarkups,
  hasPickedSlot,
  parsePromoInstant,
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

// dd/mm of an ML promotion date; naive values are UTC (parsePromoInstant), shown in the operator's time zone.
function shortDate(value) {
  const ms = parsePromoInstant(value);
  if (ms == null) return null;
  const date = new Date(ms);
  return `${String(date.getDate()).padStart(2, '0')}/${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function dateRange(promo) {
  const start = shortDate(promo?.start_date);
  const finish = shortDate(promo?.finish_date);
  if (start && finish) return `${start} – ${finish}`;
  if (finish) return `hasta ${finish}`;
  if (start) return `desde ${start}`;
  return 'Sin fecha';
}

function shares(promo) {
  const seller = promo?.payload?.seller_percentage;
  const meli = promo?.payload?.meli_percentage;
  if (seller == null && meli == null) return '—';
  return `${seller != null ? pct(seller) : '—'} / ${meli != null ? pct(meli) : '—'}`;
}

/** Markup delta of a candidate vs the applied promo (or the sale price), on the basis `comparableMarkups` picks. */
function markupDelta(promo, statusQuo) {
  const [candidate, current] = comparableMarkups(promo, statusQuo);
  if (candidate == null || current == null) return null;
  const delta = candidate - current;
  return `${delta >= 0 ? '+' : '−'}${formatAmount(Math.abs(delta))} pp`;
}

/** The figures every row shows, the applied promo and each candidate alike, so they compare like for like. */
function PromoFigures({ price, markup, sellInOut, sharesText, dates, delta, deltaLabel }) {
  return (
    <>
      <span className={styles.mejoresFigure}>
        <span className={styles.mejoresEyebrow}>Precio</span>
        <span className={styles.mejoresValue}>{price != null ? `$ ${formatAmount(price)}` : '—'}</span>
      </span>
      <span className={styles.mejoresFigure}>
        <span className={styles.mejoresEyebrow}>Markup</span>
        <span className={`${styles.mejoresValue} ${markupTone(markup)}`}>{markup != null ? pct(markup) : '—'}</span>
        <SellInOutMarkupExtra value={sellInOut} format={pct} />
        {delta && (
          <span className={styles.mejoresDelta} aria-label={`${delta} ${deltaLabel}`}>
            {delta} {deltaLabel}
          </span>
        )}
      </span>
      <span className={styles.mejoresFigure}>
        <span className={styles.mejoresEyebrow}>Vend. / ML</span>
        <span className={styles.mejoresValue}>{sharesText}</span>
      </span>
      <span className={styles.mejoresFigure}>
        <span className={styles.mejoresEyebrow}>Vigencia</span>
        <span className={styles.mejoresValue}>{dates}</span>
      </span>
    </>
  );
}

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
  // The promo ML applies today (`application_status === 'active'`), null when none: the comparison's left side.
  const [applied, setApplied] = useState(null);
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
        setApplied(promotions.find((promo) => promo?.application_status === 'active') ?? null);
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
  // What each candidate is compared against: the applied promo, else today's sale price with its markup.
  const statusQuo = applied
    ? { nuestro_markup: applied.nuestro_markup, markup_sell_in_out: applied.markup_sell_in_out }
    : { nuestro_markup: baselineMarkup, markup_sell_in_out: baselineSellInOut };
  const deltaLabel = applied ? 'vs aplicada' : 'vs actual';
  const appliedCard = applied ? (
    <li className={`${styles.mejoresCard} ${styles.mejoresCardApplied}`} role="group" aria-label="Promo aplicada">
      <span className={styles.mejoresHead}>
        <span className={`${promoStyles.badge} ${SLOT_BADGE[applied.promotion_type] || promoStyles.badgeTypeNeutral}`}>
          {applied.promotion_type}
        </span>
        <span className={styles.mejoresMain}>
          <span className={styles.mejoresEyebrow}>Promo aplicada</span>
          <span className={styles.mejoresName}>{resolvePromoName(applied) || applied.promotion_id}</span>
        </span>
      </span>
      <PromoFigures
        price={promoDisplayPrice(applied)}
        markup={applied.nuestro_markup}
        sellInOut={applied.markup_sell_in_out}
        sharesText={shares(applied)}
        dates={dateRange(applied)}
      />
    </li>
  ) : (
    <li className={`${styles.mejoresCard} ${styles.mejoresCardApplied}`} role="group" aria-label="Sin promo aplicada">
      <span className={styles.mejoresHead}>
        <span className={`${promoStyles.badge} ${promoStyles.badgeTypeNeutral}`}>Actual</span>
        <span className={styles.mejoresMain}>
          <span className={styles.mejoresEyebrow}>Sin promo aplicada</span>
          <span className={styles.mejoresName}>Precio de venta actual</span>
        </span>
      </span>
      <PromoFigures
        price={baselinePrice != null && Number.isFinite(Number(baselinePrice)) ? Number(baselinePrice) : null}
        markup={baselineMarkup}
        sellInOut={baselineSellInOut}
        sharesText="—"
        dates="—"
      />
    </li>
  );

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
            {appliedCard}
            {entries.map(([slot, promo], index) => {
              const price = promoDisplayPrice(promo);
              return (
                <li key={slot} className={styles.mejoresCard} role="group" aria-label={`Promo sugerida ${CHOOSER_SLOT_LABELS[slot] || slot}`}>
                  <span className={styles.mejoresHead}>
                    <span className={`${promoStyles.badge} ${SLOT_BADGE[slot] || promoStyles.badgeTypeNeutral}`}>
                      {CHOOSER_SLOT_LABELS[slot] || slot}
                    </span>
                    <span className={styles.mejoresMain}>
                      <span className={styles.mejoresEyebrow}>Promo sugerida</span>
                      <span className={styles.mejoresName}>{resolvePromoName(promo) || promo.promotion_id}</span>
                    </span>
                  </span>
                  <PromoFigures
                    price={price}
                    markup={promo.nuestro_markup}
                    sellInOut={promo.markup_sell_in_out}
                    sharesText={shares(promo)}
                    dates={dateRange(promo)}
                    delta={markupDelta(promo, statusQuo)}
                    deltaLabel={deltaLabel}
                  />
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
