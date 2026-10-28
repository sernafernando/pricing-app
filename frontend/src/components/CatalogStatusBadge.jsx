import { AlertCircle, Handshake, Trophy } from 'lucide-react';
import styles from './CatalogStatusBadge.module.css';

// Productos' marks (trophy, handshake, "!") as icons, with the state in words for whoever cannot see them.
const STATES = {
  winning: { Icon: Trophy, label: 'ganando' },
  sharing_first_place: { Icon: Handshake, label: 'compartiendo el primer lugar' },
  competing: { Icon: AlertCircle, label: 'compitiendo' },
};

/** Productos' tooltip per status: the price it wins or ties at, or the price to win; none without that price. */
function tooltip(product) {
  const { catalog_status: status, catalog_winner_price: winner, catalog_price_to_win: toWin } = product;
  if (status === 'winning' && winner) return `Ganando a $${winner.toFixed(2)}`;
  if (status === 'competing' && toWin) return `Precio para ganar: $${toWin.toFixed(2)}`;
  if (status === 'sharing_first_place' && winner) return `Empatando a $${winner.toFixed(2)}`;
  return undefined;
}

/**
 * A product's catalog competition at a glance, as Productos' row badge (P:1716-1747): a trophy winning, a handshake
 * sharing first place, an alert competing (any other status, an empty neutral badge), with the price in its tooltip.
 * Reads the Productos listing's `has_catalog`, `catalog_status`, `catalog_winner_price` and `catalog_price_to_win`;
 * nothing without a catalog or a status.
 *
 * @param {{ product: object | null | undefined }} props
 */
export default function CatalogStatusBadge({ product }) {
  if (!product?.has_catalog || !product.catalog_status) return null;
  const state = STATES[product.catalog_status];
  const title = tooltip(product);
  const label = `Catálogo: ${state?.label ?? product.catalog_status}${title ? ` (${title})` : ''}`;
  return (
    <span className={styles.badge} data-status={product.catalog_status} title={title} aria-label={label} role="img">
      {state && <state.Icon size={11} aria-hidden="true" />}
    </span>
  );
}
