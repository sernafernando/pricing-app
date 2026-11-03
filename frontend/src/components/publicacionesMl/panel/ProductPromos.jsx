import PromocionesTab from './PromocionesTab';
import PublicationDisclosures from './PublicationDisclosures';

/**
 * The promotions of a product's publications: one entry per publication, closed until opened, which mounts the
 * publication panel's Promos tab (`PromocionesTab`: the sections, coupons last, and its 5-minute pull rule), so a
 * publication's promotions read the same from either panel and only when asked.
 *
 * Gated by the caller (the product panel's Promos tab exists only with `promos.ver`). Mount it with a key unique to
 * the product so another product starts closed.
 *
 * @param {object} props
 * @param {Array<{item_id: string, title?: string}>} props.publications The product's publications the panel lists.
 * @param {() => void} [props.onPromoApplied] After an apply or remove (a promotion changes the price and markup).
 */
export default function ProductPromos({ publications, onPromoApplied }) {
  return (
    <PublicationDisclosures
      title="Promociones"
      publications={publications}
      renderOpen={(itemId) => <PromocionesTab itemId={itemId} onPromoApplied={onPromoApplied} />}
    />
  );
}
