import { NEUTRAL_TONE, catalogState, catalogTooltip } from './catalogStatus';
import styles from './CatalogStatusBadge.module.css';


/**
 * A product's catalog competition at a glance, beside its name in Publicaciones ML's product rows. It mirrors the
 * catalog badge of Productos' product rows (`pages/Productos.jsx`), and both read the same states and tooltip
 * (`catalogStatus.js`).
 *
 * - Winning shows a trophy, sharing first place a handshake, competing an alert, each in its state's tone.
 * - Any other status shows an empty neutral badge, announced by its own key: it says which state it is, where a
 *   generic word would hide it.
 * - The tooltip has the price it wins or ties at, or the price to win; none without that price.
 * - Nothing shows without a catalog or a status.
 *
 * Reads the Productos listing's `has_catalog`, `catalog_status`, `catalog_winner_price` and `catalog_price_to_win`.
 *
 * @param {{ product: object | null | undefined }} props
 */
export default function CatalogStatusBadge({ product }) {
  if (!product?.has_catalog || !product.catalog_status) return null;
  const state = catalogState(product.catalog_status);
  const title = catalogTooltip(product);
  const label = `Catálogo: ${state?.label ?? product.catalog_status}${title ? ` (${title})` : ''}`;
  return (
    <span
      className={styles.badge}
      data-status={product.catalog_status}
      style={{ '--catalog-tone': state?.tone ?? NEUTRAL_TONE }}
      title={title}
      aria-label={label}
      role="img"
    >
      {state && <state.Icon size={11} aria-hidden="true" />}
    </span>
  );
}
