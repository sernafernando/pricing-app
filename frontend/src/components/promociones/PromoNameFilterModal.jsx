import ModalTesla from '../ModalTesla';
import { usePromoFilterStore } from '../../store/promoFilterStore';
import { PROMO_TYPES } from '../../constants/promoTypes';
import styles from './promoNameFilterModal.module.css';

/**
 * Mini-modal: narrows the VISIBLE promos by NAME, grouped by TYPE.
 * Presentational — reads/writes selectedNames on the global store directly,
 * same pattern as PromoFilterBar. `promosByType` ({ [type]: string[] }) is
 * an open-time snapshot of the already-fetched promos, passed by the caller.
 */
function PromoNameFilterModal({ open, onClose, promosByType }) {
  const selectedNames = usePromoFilterStore((state) => state.selectedNames);
  const toggleName = usePromoFilterStore((state) => state.toggleName);
  const clearNamesForType = usePromoFilterStore((state) => state.clearNamesForType);

  const groups = PROMO_TYPES.filter(({ type }) => (promosByType?.[type] || []).length > 0);

  return (
    <ModalTesla isOpen={open} onClose={onClose} title="Filtrar promos por nombre" size="md">
      {groups.length === 0 ? (
        <p className={styles.emptyState}>
          No hay promociones cargadas todavía. Expandí un MLA para verlas acá.
        </p>
      ) : (
        groups.map(({ type, label }) => {
          const names = promosByType[type] || [];
          const selected = selectedNames[type] || [];
          return (
            <fieldset key={type} className={styles.group}>
              <legend className={styles.groupHeader}>
                <span>{label}</span>
                {selected.length > 0 && (
                  <button
                    type="button"
                    className={styles.groupReset}
                    onClick={() => clearNamesForType(type)}
                  >
                    Todas
                  </button>
                )}
              </legend>
              <div className={styles.nameList}>
                {names.map((name) => {
                  const checkboxId = `promo-name-${type}-${name ?? 'sin-nombre'}`;
                  return (
                    <div key={checkboxId} className={styles.nameOption}>
                      <input
                        id={checkboxId}
                        type="checkbox"
                        checked={selected.includes(name)}
                        onChange={() => toggleName(type, name)}
                      />
                      <label htmlFor={checkboxId}>{name ?? '(sin nombre)'}</label>
                    </div>
                  );
                })}
              </div>
            </fieldset>
          );
        })
      )}
    </ModalTesla>
  );
}

export default PromoNameFilterModal;
