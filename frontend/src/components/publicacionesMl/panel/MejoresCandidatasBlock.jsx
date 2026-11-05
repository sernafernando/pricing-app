import { useEffect, useRef, useState } from 'react';
import { formatAmount } from '../../../utils/ventasMlFormat';
import { errorText } from '../../pricing/priceWrites';
import { promocionesAPI } from '../../../services/api';
import { resolvePromoName } from '../../promociones/resolvePromoName';
import { promoDisplayPrice } from '../../promociones/promoDisplayPrice';
import {
  baselineMarkupFromPromos,
  enrollBodyForPromo,
  hasPickedSlot,
  pickMejoresCandidatas,
} from './pickPonerPreciosPromos';
import styles from './panel.module.css';

const SLOT_LABELS = { smart: 'SMART', deal: 'DEAL', premium: 'Premium' };

function slotEntries(picked) {
  if (!picked) return [];
  return [
    ['smart', picked.smart],
    ['deal', picked.deal],
    ['premium', picked.premium],
  ].filter(([, promo]) => promo);
}

/**
 * Inline SMART/DEAL/Premium chooser for a pub already flagged hay_mejores.
 * Mount only when the operator can write promos (discard/apply need it).
 * Calls onUnavailable when baseline markup is missing or load fails hard.
 */
export default function MejoresCandidatasBlock({
  itemId,
  baselinePrice,
  onWritten,
  onLeavePub,
  onDismissed,
  onUnavailable,
}) {
  const [loading, setLoading] = useState(true);
  const [slots, setSlots] = useState(null);
  const [baselineMarkup, setBaselineMarkup] = useState(null);
  const [message, setMessage] = useState(null);
  const [enrolling, setEnrolling] = useState(false);
  const [descartando, setDescartando] = useState(false);
  const onUnavailableRef = useRef(onUnavailable);
  onUnavailableRef.current = onUnavailable;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setMessage(null);
      try {
        const promoRes = await promocionesAPI.getPromocionesItem(itemId);
        if (cancelled) return;
        const promotions = promoRes?.data?.promotions ?? promoRes?.data?.promociones ?? [];
        // Co-funded started (SMART / PRE_NEGOTIATED / PRICE_MATCHING) matching
        // sale → same markup as the promo card; else plain getMarkupParaPrecio.
        let markup = baselineMarkupFromPromos(promotions, baselinePrice);
        if (markup == null && baselinePrice != null && Number.isFinite(Number(baselinePrice))) {
          try {
            const res = await promocionesAPI.getMarkupParaPrecio(itemId, Number(baselinePrice));
            markup = res?.data?.nuestro_markup ?? null;
          } catch {
            markup = null;
          }
        }
        if (cancelled) return;
        if (markup == null) {
          onUnavailableRef.current?.();
          return;
        }
        setBaselineMarkup(markup);
        const picked = pickMejoresCandidatas(promotions, {
          baselinePrice: Number(baselinePrice),
          baselineMarkup: markup,
        });
        setSlots(hasPickedSlot(picked) ? picked : null);
      } catch (err) {
        if (!cancelled) {
          setMessage({ tone: 'error', text: errorText(err, 'No se pudieron cargar las candidatas.') });
          onUnavailableRef.current?.();
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [itemId, baselinePrice]);

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

  const accept = async (slot) => {
    const promo = slots?.[slot];
    if (!promo || enrolling) return;
    setEnrolling(true);
    setMessage(null);
    try {
      await promocionesAPI.postPromocionItem(itemId, enrollBodyForPromo(promo));
      onWritten?.();
      onLeavePub?.();
    } catch (err) {
      setMessage({ tone: 'error', text: errorText(err, 'No se pudo activar la promoción.') });
      setEnrolling(false);
    }
  };

  const entries = slotEntries(slots);

  return (
    <div className={styles.ponerPreciosMejores} role="region" aria-label="Candidatas mejores">
      {loading ? (
        <p className={styles.ponerPreciosOk} role="status">
          Cargando candidatas…
          {baselineMarkup != null ? ` Markup vigente ~ ${formatAmount(baselineMarkup)}%.` : ''}
        </p>
      ) : entries.length > 0 ? (
        <>
          <p className={styles.ponerPreciosMejoresLead}>
            Hay candidatas mejores que el precio vigente en MeLi.
            {baselineMarkup != null ? ` Markup vigente ~ ${formatAmount(baselineMarkup)}%.` : ''}
          </p>
          <ul className={styles.ponerPreciosChoices}>
            {entries.map(([slot, promo]) => (
              <li key={slot}>
                <button
                  type="button"
                  className="btn-tesla outline sm"
                  disabled={enrolling}
                  onClick={() => accept(slot)}
                >
                  <span className={styles.ponerPreciosChoiceLabel}>{SLOT_LABELS[slot]}</span>
                  <span className={styles.ponerPreciosChoiceMeta}>
                    {resolvePromoName(promo) || promo.promotion_id}
                    {promoDisplayPrice(promo) != null ? ` · $ ${formatAmount(promoDisplayPrice(promo))}` : ''}
                    {promo.nuestro_markup != null ? ` · markup ${formatAmount(promo.nuestro_markup)}%` : ''}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className={styles.ponerPreciosOk} role="status">
          No hay candidatas SMART / DEAL / Premium que superen el precio vigente
          {baselineMarkup != null ? ` (markup vigente ~ ${formatAmount(baselineMarkup)}%)` : ''}.
          Podés descartar el aviso si quedó desactualizado.
        </p>
      )}
      <button
        type="button"
        className="btn-tesla ghost sm"
        disabled={descartando || enrolling}
        onClick={discard}
      >
        {descartando ? 'Descartando…' : 'Descartar sugerencia'}
      </button>
      {message && (
        <p className={message.tone === 'error' ? styles.ponerPreciosError : styles.ponerPreciosOk} role="status">
          {message.text}
        </p>
      )}
    </div>
  );
}
