import { pxqAPI } from '../../services/api';
import { useLazyResource } from '../../hooks/useLazyResource';
import { usePermisos } from '../../contexts/PermisosContext';
import styles from './promociones.module.css';

// Money is Decimal on the backend and arrives as a number or string here —
// this only formats it for display, it never computes or re-derives a
// markup (product decision carried over from CatalogCompetitionPanel).
function formatMoney(value) {
  if (value === null || value === undefined) return 'N/A';
  return `$${Number(value).toLocaleString('es-AR')}`;
}

/**
 * PxQ (wholesale, price-by-quantity) READ-ONLY panel (PR 4a).
 *
 * Reads `GET /pxq/{item_id}/live` on open and shows live MercadoLibre state
 * side by side with the local mirror. This is the requirement that drove the
 * whole feature's design: "no me gusta que nada suceda en silencio" — live
 * state is shown ALWAYS, not only on divergence, and it renders ABOVE where
 * PR 4b will add the tier inputs.
 *
 * `live_tiers: null` (the read failed/is unavailable) and `live_tiers: []`
 * (ML confirmed there genuinely are none) are DIFFERENT claims and must never
 * collapse into the same "0 tramos" rendering — see `live_status` handling
 * below and `backend/app/routers/pxq.py`'s `_unavailable_response` docstring.
 *
 * No tier create/edit/delete, no shipping-cost input, no sync button, no
 * divergence-resolution action — those are PR 4b. Divergences are marked
 * here purely as information.
 */
function PxqPanel({ itemId, pxqCacheRef }) {
  const { tienePermiso } = usePermisos();
  const canRead = tienePermiso('pxq.ver');

  // Gated inside the fetcher itself, not just the render: `useLazyResource`
  // fires its effect unconditionally on mount, so a plain early return after
  // the hook call would still let the fetch race the permission check.
  const fetcher = (id) => (canRead ? pxqAPI.getLive(id).then((r) => r.data) : Promise.resolve(null));
  const { data, loading, error, reload } = useLazyResource(pxqCacheRef, itemId, fetcher);

  // Invisible rather than an error/403 for a user without the permission —
  // same treatment PromoApplyControl/refresh buttons use elsewhere in this
  // tree: showing a control that only 403s helps no one.
  if (!canRead) {
    return null;
  }

  if (loading) {
    return <div className={styles.panelState}>Cargando precios mayoristas...</div>;
  }

  if (error) {
    return (
      <div className={styles.panelStateError}>
        Error al cargar precios mayoristas.{' '}
        <button type="button" className="btn-tesla ghost sm" onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  }

  const liveTiers = data?.live_tiers ?? null;
  const mirrorTiers = data?.mirror_tiers || [];
  const liveUnavailable = data?.live_status === 'unavailable' || liveTiers === null;

  // Divergence is informational only here (PR 4b owns resolution): a mirror
  // tier with a synced `ml_price_id` that either has no matching live id, or
  // whose live quantity/amount differs from the mirror, is marked divergent.
  const liveById = new Map((liveTiers || []).map((tier) => [tier.id, tier]));
  function isDivergent(mirrorTier) {
    if (!mirrorTier.ml_price_id || liveUnavailable) return false;
    const liveTier = liveById.get(mirrorTier.ml_price_id);
    if (!liveTier) return true;
    return liveTier.quantity !== mirrorTier.cantidad_minima || Number(liveTier.amount) !== Number(mirrorTier.precio_unitario);
  }

  return (
    <div>
      <div className={styles.pxqColumns}>
        <div className={styles.pxqColumn}>
          <div className={styles.pxqColumnTitle}>En MercadoLibre (en vivo)</div>
          {liveUnavailable ? (
            <div className={styles.pxqUnavailable}>No se pudo leer el estado en vivo de MercadoLibre.</div>
          ) : liveTiers.length === 0 ? (
            <div className={styles.panelState}>ML no tiene tramos mayoristas para esta publicación.</div>
          ) : (
            liveTiers.map((tier) => (
              <div key={tier.id} className={styles.pxqTierRow}>
                <span>{tier.quantity} u.</span>
                <span>{formatMoney(tier.amount)}</span>
              </div>
            ))
          )}
        </div>
        <div className={styles.pxqColumn}>
          <div className={styles.pxqColumnTitle}>Mirror local</div>
          {mirrorTiers.length === 0 ? (
            <div className={styles.panelState}>Sin tramos mayoristas locales.</div>
          ) : (
            mirrorTiers.map((tier) => {
              const divergent = isDivergent(tier);
              return (
                <div
                  key={tier.id}
                  className={`${styles.pxqTierRow} ${divergent ? styles.pxqTierRowDivergent : ''}`}
                >
                  <span>{tier.cantidad_minima} u.</span>
                  <span>{formatMoney(tier.precio_unitario)}</span>
                  <span>{tier.estado}</span>
                  {divergent && <span>Diverge de ML</span>}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

export default PxqPanel;
