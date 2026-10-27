import { CRITERIA_STUB } from './criteriaFields';
import styles from '../../pages/ParaGanarAdvisor.module.css';

export default function ParaGanarCriteriosDetail({ selected }) {
  return (
    <aside className={styles.detail} aria-label="Criterios de la MLA">
      <div className={styles.panelTitle}>Criterios MLA</div>
      {!selected && (
        <div className={styles.emptyState}>
          <p className={styles.emptyTitle}>Seleccioná un MLA</p>
          <p className={styles.emptyBody}>
            Acá vas a editar los criterios de esa publicación (y ver si vienen de MLA,
            producto o default PM).
          </p>
        </div>
      )}
      {selected && (
        <div className={styles.criteriaPanel}>
          <div className={styles.criteriaIdentity}>
            <div className={styles.mla}>{selected.mla}</div>
            <div className={styles.criteriaIdentityMeta}>
              {selected.codigo || '—'} · {selected.lista_nombre || 'Sin lista'}
            </div>
            <div className={styles.criteriaSource}>
              Origen efectivo: <strong>default</strong> (aún no hay criterios guardados)
            </div>
          </div>

          <form
            className={styles.criteriaForm}
            onSubmit={(e) => e.preventDefault()}
            aria-label={`Criterios de ${selected.mla}`}
          >
            {CRITERIA_STUB.map((field) => (
              <label key={field.key} className={styles.criteriaField}>
                <span>{field.label}</span>
                <input
                  className={styles.criteriaInput}
                  type="text"
                  inputMode="decimal"
                  placeholder={field.placeholder}
                  disabled
                  aria-disabled="true"
                />
              </label>
            ))}
            <label className={styles.criteriaCheck}>
              <input type="checkbox" disabled />
              Ignorar competidores internacionales
            </label>
            <label className={styles.criteriaCheck}>
              <input type="checkbox" disabled />
              Descartar stock residual
            </label>
            <label className={styles.criteriaCheck}>
              <input type="checkbox" disabled />
              Descartar reputación baja
            </label>
            <label className={styles.criteriaCheck}>
              <input type="checkbox" disabled />
              Techo por monopolio
            </label>
            <button type="submit" className={styles.saveCriteriaBtn} disabled>
              Guardar criterios de esta MLA
            </button>
          </form>
        </div>
      )}
    </aside>
  );
}
