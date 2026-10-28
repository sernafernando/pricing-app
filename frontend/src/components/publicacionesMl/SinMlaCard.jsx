import { PackageX } from 'lucide-react';
import styles from './SinMlaCard.module.css';

const HELP =
  'Productos del ERP sin ninguna publicación vinculada (fuera de los banlists). Solo aplican los filtros de producto.';

/**
 * Productos' "Sin MLA" card in the Producto view: how many products the product filters keep that no publication is
 * linked to, and the switch that lists them. `count` is null when unknown (a publication filter is on).
 */
export default function SinMlaCard({ count, active, onChange }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={`${styles.card} ${active ? styles.active : ''}`}
      title={HELP}
      onClick={() => onChange(!active)}
    >
      <PackageX size={14} aria-hidden="true" />
      <span className={styles.label}>Sin MLA</span>
      <span className={styles.count}>{count == null ? '–' : count.toLocaleString('es-AR')}</span>
    </button>
  );
}
