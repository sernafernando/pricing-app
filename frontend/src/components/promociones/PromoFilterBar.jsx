import { useState, useMemo } from 'react';
import { usePromoFilterStore } from '../../store/promoFilterStore';
import styles from './promociones.module.css';
import { PROMO_TYPES } from '../../constants/promoTypes';
import PromoNameFilterModal from './PromoNameFilterModal';
import { derivePromosByType } from './derivePromosByType';

/**
 * GLOBAL filter bar — rendered at the page level in Productos, and in the
 * header of each Publicaciones ML Promos tab (one per open publication in a
 * product panel); every copy reads and writes the same store.
 * Toggling a chip filters the promo list of EVERY MLA panel that shows promos.
 * `promosCacheRef` (optional) is the host-owned promos cache; it's read
 * open-time only, to build the name universe for the "Nombres" mini-modal.
 * `showLabel={false}` drops the "Filtrar promos:" label, for a host whose own
 * toggle already names the filter.
 */
function PromoFilterBar({ promosCacheRef, showLabel = true }) {
  const selectedTypes = usePromoFilterStore((state) => state.selectedTypes);
  const selectedNames = usePromoFilterStore((state) => state.selectedNames);
  const toggleType = usePromoFilterStore((state) => state.toggleType);
  const clear = usePromoFilterStore((state) => state.clear);
  const [nameModalOpen, setNameModalOpen] = useState(false);

  const namesActiveCount = Object.values(selectedNames).reduce((sum, names) => sum + names.length, 0);
  const noFilterActive = selectedTypes.length === 0 && namesActiveCount === 0;

  // Local (component-specific) modal visibility; the snapshot is derived
  // only while the modal is open, since promosCacheRef is not reactive.
  // The filter is persisted, so a chosen name may belong to no promotion
  // loaded right now: it is listed too, so it can still be unchecked.
  const promosByType = useMemo(() => {
    if (!nameModalOpen) return {};
    const byType = derivePromosByType(promosCacheRef);
    for (const [type, names] of Object.entries(selectedNames)) {
      const loaded = byType[type] || [];
      byType[type] = [...loaded, ...names.filter((name) => !loaded.includes(name))];
    }
    return byType;
  }, [nameModalOpen, promosCacheRef, selectedNames]);

  return (
    <div className={styles.filterBar}>
      {showLabel && <span className={styles.filterBarLabel}>Filtrar promos:</span>}
      <button
        type="button"
        className={styles.filterChip}
        aria-pressed={noFilterActive}
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
      <button
        type="button"
        className={`${styles.filterChip} ${namesActiveCount > 0 ? styles.filterChipActive : ''}`}
        onClick={() => setNameModalOpen(true)}
      >
        Nombres{namesActiveCount > 0 ? ` (${namesActiveCount})` : ''}
      </button>
      <PromoNameFilterModal
        open={nameModalOpen}
        onClose={() => setNameModalOpen(false)}
        promosByType={promosByType}
      />
    </div>
  );
}

export default PromoFilterBar;
