import { useRef } from 'react';
import MlaPromocionesPanel from '../../promociones/MlaPromocionesPanel';

/**
 * Promociones tab: the promotions of the selected publication, through the
 * panel the Productos page already uses.
 *
 * It mounts only while the tab is open (the panel renders the active tab and
 * nothing else), so nothing is asked of ML until somebody looks: the ML
 * throttle is shared with sales-webhook processing. Opening pulls fresh state
 * first (`pullOnOpen`); `MlaPromocionesPanel` itself gates the pull and the
 * apply/remove controls on `promos.ver` / `promos.escribir`.
 *
 * `key={itemId}` makes a new selection start from scratch, so one
 * publication's promotions are never shown under the next. The cache is
 * private to this tab: the Productos filter bar that reads its entries is not
 * on this page, and the global promo filter is ignored for the same reason.
 */
export default function PromocionesTab({ itemId }) {
  const promosCacheRef = useRef(new Map());
  return <MlaPromocionesPanel key={itemId} mla={itemId} promosCacheRef={promosCacheRef} pullOnOpen ignoreGlobalFilter />;
}
