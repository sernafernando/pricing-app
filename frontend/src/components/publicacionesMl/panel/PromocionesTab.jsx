import { useState } from 'react';
import MlaPromocionesPanel from '../../promociones/MlaPromocionesPanel';
import { markPromoPulled, promoPulledRecently } from '../../promociones/promoPullTtl';

/** One MLA's promotions; mounted per MLA, so its pull decision is that MLA's. */
function ItemPromotions({ itemId, promosCacheRef, onPromoApplied }) {
  // Read once per mount: the pull this mount starts must not switch itself off when it succeeds.
  const [pullOnOpen] = useState(() => !promoPulledRecently(itemId));
  return (
    <MlaPromocionesPanel
      mla={itemId}
      promosCacheRef={promosCacheRef}
      pullOnOpen={pullOnOpen}
      ignoreGlobalFilter
      sections
      onApplied={onPromoApplied}
      onPulled={markPromoPulled}
    />
  );
}

/**
 * Promociones tab: the promotions of the selected publication, through the
 * panel the Productos page already uses.
 *
 * It mounts only while the tab is open (the panel renders the active tab and
 * nothing else). It is the panel's first tab (owner, 2026-11-02), so opening a
 * publication opens it: to keep a click through rows from costing an ML pull
 * per click on a throttle shared with sales-webhook processing, an MLA pulled
 * successfully in the last 5 minutes shows its mirror without pulling again
 * (`promoPullTtl`); an apply or remove forgets it (inside `MlaPromocionesPanel`). `MlaPromocionesPanel`
 * itself gates the pull and the apply/remove controls on `promos.ver` /
 * `promos.escribir`.
 *
 * The promotions come in sections (S3): Activa ahora, Disponibles para activar (with the markup each would leave),
 * Otras promociones and, last and quieter, the coupons, read-only with a link to Mercado Libre.
 *
 * `onPromoApplied` fires after an apply or remove, so the panel can re-read
 * the price and markup it shows.
 *
 * `key={itemId}` makes a new selection start from scratch, so one
 * publication's promotions are never shown under the next. The cache is
 * private to this tab: the Productos filter bar that reads its entries is not
 * on this page, and the global promo filter is ignored for the same reason.
 */
export default function PromocionesTab({ itemId, onPromoApplied }) {
  const [promosCacheRef] = useState(() => ({ current: new Map() }));
  return <ItemPromotions key={itemId} itemId={itemId} promosCacheRef={promosCacheRef} onPromoApplied={onPromoApplied} />;
}
