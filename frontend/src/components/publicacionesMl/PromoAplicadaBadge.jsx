import { Tag } from 'lucide-react';
import styles from './PromoAplicadaBadge.module.css';

/**
 * "Promo aplicada" (auditoria-stock S9, L4): a green chip on a publication with a started promotion in Mercado
 * Libre. Only `true` draws it: no chip means no applied promotion (candidates do not count), and an unknown state
 * (the promotions database could not be read, the field absent) draws nothing either.
 */
export default function PromoAplicadaBadge({ applied }) {
  if (applied !== true) return null;
  return (
    <span className={styles.badge} title="Tiene una promoción aplicada en Mercado Libre">
      <Tag size={11} aria-hidden="true" />
      Promo aplicada
    </span>
  );
}
