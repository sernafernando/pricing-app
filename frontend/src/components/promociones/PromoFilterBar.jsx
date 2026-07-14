import { usePromoFilterStore } from '../../store/promoFilterStore';
import styles from './promociones.module.css';
import { PROMO_TYPES } from '../../constants/promoTypes';

/**
 * GLOBAL filter bar — rendered once at the page level (not per-panel).
 * Toggling a chip filters the promo list of EVERY expanded MLA panel.
 */
function PromoFilterBar() {
  const selectedTypes = usePromoFilterStore((state) => state.selectedTypes);
  const toggleType = usePromoFilterStore((state) => state.toggleType);
  const clear = usePromoFilterStore((state) => state.clear);

  return (
    <div className={styles.filterBar}>
      <span className={styles.filterBarLabel}>Filtrar promos:</span>
      <button
        type="button"
        className={styles.filterChip}
        aria-pressed={selectedTypes.length === 0}
        onClick={clear}
      >
        Todas
      </button>
      {PROMO_TYPES.map(({ type, label }) => {
        const selected = selectedTypes.includes(type);
        return (
          <button
            key={type}
            type="button"
            className={`${styles.filterChip} ${selected ? styles.filterChipActive : ''}`}
            aria-pressed={selected}
            onClick={() => toggleType(type)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

export default PromoFilterBar;
