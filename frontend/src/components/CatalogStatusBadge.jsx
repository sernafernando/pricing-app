import { AlertCircle, Handshake, Trophy } from 'lucide-react';
import { CATALOG_STATES, catalogTooltip } from './catalogStatus';
import styles from './CatalogStatusBadge.module.css';

// Productos' marks (trophy, handshake, "!") as icons, one per state of `CATALOG_STATES`.
const ICONS = { winning: Trophy, sharing_first_place: Handshake, competing: AlertCircle };

/**
 * A product's catalog competition at a glance, as the catalog badge beside the description in Productos' product
 * rows (`pages/Productos.jsx`, the `has_catalog` / `catalog_status` span): a trophy winning, a handshake
 * sharing first place, an alert competing (any other status, an empty neutral badge), with the price in its tooltip.
 * Both pages share the states and the tooltip (`catalogStatus.js`); only the marks differ, emoji in Productos and
 * icons here. A status
 * this component has no word for (a new one from ML) is announced by its own key: it says which state it is, where a
 * generic word would hide it.
 * Reads the Productos listing's `has_catalog`, `catalog_status`, `catalog_winner_price` and `catalog_price_to_win`;
 * nothing without a catalog or a status.
 *
 * @param {{ product: object | null | undefined }} props
 */
export default function CatalogStatusBadge({ product }) {
  if (!product?.has_catalog || !product.catalog_status) return null;
  const state = CATALOG_STATES[product.catalog_status];
  const Icon = ICONS[product.catalog_status];
  const title = catalogTooltip(product);
  const label = `Catálogo: ${state?.label ?? product.catalog_status}${title ? ` (${title})` : ''}`;
  return (
    <span className={styles.badge} data-status={product.catalog_status} title={title} aria-label={label} role="img">
      {Icon && <Icon size={11} aria-hidden="true" />}
    </span>
  );
}
