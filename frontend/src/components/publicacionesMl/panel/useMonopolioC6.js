import { useEffect, useState } from 'react';
import { promocionesAPI } from '../../../services/api';
import { monopolioFromSnapshotAndCriterios } from './monopolioC6';
import { currentMonthNameEs, isPremiumCurrentMonth } from './pickPonerPreciosPromos';

/**
 * Loads criterios + latest catalog snapshot and returns a C6 opportunity (or null).
 * ``salePrice``: live sale/status-quo ARS (preferred over snapshot our price).
 * Also resolves markup at precio_objetivo and the Premium-of-month candidate for apply UI.
 */
export function useMonopolioC6(itemId, { salePrice = null } = {}) {
  const [loading, setLoading] = useState(Boolean(itemId));
  const [oportunidad, setOportunidad] = useState(null);
  const [markupPct, setMarkupPct] = useState(null);
  const [premiumPromo, setPremiumPromo] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!itemId) {
      setLoading(false);
      setOportunidad(null);
      setMarkupPct(null);
      setPremiumPromo(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const criteriosRes = await promocionesAPI.getHayMejoresCriterios(itemId);
        const criterios = criteriosRes.data;
        if (cancelled) return;
        if (!criterios?.c6_activo) {
          setOportunidad(null);
          setMarkupPct(null);
          setPremiumPromo(null);
          return;
        }
        let snapshot = null;
        try {
          const snapRes = await promocionesAPI.getCompetenciaCatalogo(itemId);
          snapshot = snapRes.data;
        } catch {
          if (!cancelled) {
            setOportunidad(null);
            setMarkupPct(null);
            setPremiumPromo(null);
            setError('No se pudo cargar el ranking de catálogo para monopolio');
          }
          return;
        }
        if (cancelled) return;
        const opp = monopolioFromSnapshotAndCriterios(itemId, snapshot, criterios, { salePrice });
        setOportunidad(opp);

        if (opp?.precio_objetivo != null && Number.isFinite(Number(opp.precio_objetivo))) {
          try {
            const markupRes = await promocionesAPI.getMarkupParaPrecio(itemId, Number(opp.precio_objetivo));
            if (!cancelled) {
              const raw = markupRes?.data?.nuestro_markup;
              setMarkupPct(raw != null && Number.isFinite(Number(raw)) ? Number(raw) : null);
            }
          } catch {
            if (!cancelled) setMarkupPct(null);
          }
        } else if (!cancelled) {
          setMarkupPct(null);
        }

        if (!opp?.solo_via_promo) {
          try {
            const promosRes = await promocionesAPI.getPromocionesItem(itemId);
            const list = Array.isArray(promosRes?.data)
              ? promosRes.data
              : promosRes?.data?.promotions || promosRes?.data?.promociones || [];
            const monthName = currentMonthNameEs();
            const premium = list.find(
              (p) =>
                (p?.promotion_type || p?.type) === 'SELLER_CAMPAIGN' &&
                (p?.status === 'candidate' || p?.status === 'pending') &&
                isPremiumCurrentMonth(p, monthName),
            );
            if (!cancelled) setPremiumPromo(premium || null);
          } catch {
            if (!cancelled) setPremiumPromo(null);
          }
        } else if (!cancelled) {
          setPremiumPromo(null);
        }
      } catch {
        if (!cancelled) {
          setOportunidad(null);
          setMarkupPct(null);
          setPremiumPromo(null);
          setError('No se pudo evaluar monopolio');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [itemId, salePrice]);

  return { loading, oportunidad, markupPct, premiumPromo, error };
}
