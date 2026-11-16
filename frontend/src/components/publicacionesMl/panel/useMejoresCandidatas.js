import { useEffect, useRef, useState } from 'react';
import { errorText } from '../../pricing/priceWrites';
import { promocionesAPI } from '../../../services/api';
import { promoDisplayPrice } from '../../promociones/promoDisplayPrice';
import {
  baselinePromo,
  hasPickedSlot,
  pickMejoresCandidatas,
  slotEntries,
} from './pickPonerPreciosPromos';

/** Load / discard state for the hay_mejores candidatas block. */
export function useMejoresCandidatas({
  itemId,
  baselinePrice,
  onWritten,
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
        // Activa ahora = ML-applied started (lowest price / application_status active).
        const statusQuoPromo = baselinePromo(promotions);
        let markup = statusQuoPromo?.nuestro_markup ?? null;
        let sellInOut = statusQuoPromo?.markup_sell_in_out ?? null;
        if (markup == null && baselinePrice != null && Number.isFinite(Number(baselinePrice))) {
          try {
            const res = await promocionesAPI.getMarkupParaPrecio(itemId, Number(baselinePrice));
            markup = res?.data?.nuestro_markup ?? null;
            sellInOut = res?.data?.markup_sell_in_out ?? null;
          } catch {
            // Soft-fail: UI already treats null markup as unavailable (no console — team rule).
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
        // Same gate as baselinePromo: only a started + active row is "Promo aplicada".
        setApplied(
          promotions.find(
            (promo) => promo?.status === 'started' && promo?.application_status === 'active',
          ) ?? null,
        );
        const comparePrice =
          statusQuoPromo != null ? Number(promoDisplayPrice(statusQuoPromo)) : Number(baselinePrice);
        const picked = pickMejoresCandidatas(promotions, {
          baselinePrice: comparePrice,
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

  return {
    loading,
    slots,
    baselineMarkup,
    baselineSellInOut,
    applied,
    unavailable,
    message,
    descartando,
    discard,
    bumpReload: () => setReloadToken((token) => token + 1),
  };
}
