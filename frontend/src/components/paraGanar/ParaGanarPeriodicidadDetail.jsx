import { useState } from 'react';
import ModalTesla from '../ModalTesla';
import {
  SCOPE_ALL,
  SCOPE_MLAS,
  SCOPE_RULES,
  TIPO_OPCIONES,
} from './periodicidadForm';
import styles from '../../pages/ParaGanarAdvisor.module.css';

function toggleId(list, id, asNumber = false) {
  const value = asNumber ? Number(id) : id;
  const next = new Set(list.map((item) => (asNumber ? Number(item) : item)));
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return [...next];
}

export default function ParaGanarPeriodicidadDetail({
  selectedEan,
  isNew,
  form,
  setForm,
  canWrite,
  saving,
  deleting,
  formError,
  formOk,
  pricelists,
  tiendasGrupos,
  getLabel,
  onSave,
  onDelete,
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);

  if (!selectedEan) {
    return (
      <aside className={styles.detail} aria-label="Detalle de suscripción">
        <div className={styles.panelTitle}>Detalle</div>
        <div className={styles.emptyState}>
          <p className={styles.emptyTitle}>Seleccioná un EAN</p>
          <p className={styles.emptyBody}>
            O ingresá uno arriba para crear la suscripción a la revisión periódica.
          </p>
        </div>
      </aside>
    );
  }

  return (
    <aside className={styles.detail} aria-label="Detalle de suscripción">
      <div className={styles.panelTitle}>Detalle</div>
      <div className={styles.criteriaPanel}>
        <div className={styles.criteriaIdentity}>
          <div className={styles.mla}>{selectedEan}</div>
          <div className={styles.criteriaIdentityMeta}>
            {isNew ? 'Nueva suscripción' : 'Suscripción guardada'}
          </div>
        </div>

        <form
          className={styles.criteriaForm}
          onSubmit={(event) => {
            event.preventDefault();
            onSave();
          }}
        >
          <label className={styles.criteriaCheck}>
            <input
              type="checkbox"
              checked={form.enabled}
              disabled={!canWrite}
              onChange={(e) => setForm((prev) => ({ ...prev, enabled: e.target.checked }))}
            />
            Activa en revisión periódica
          </label>

          <label className={styles.criteriaField}>
            Alcance
            <select
              className={styles.criteriaInput}
              value={form.scope_mode}
              disabled={!canWrite}
              onChange={(e) => setForm((prev) => ({ ...prev, scope_mode: e.target.value }))}
            >
              <option value={SCOPE_ALL}>Todo el EAN</option>
              <option value={SCOPE_MLAS}>MLAs seleccionados</option>
              <option value={SCOPE_RULES}>Por lista / tipo / tienda</option>
            </select>
          </label>

          {form.scope_mode === SCOPE_MLAS && (
            <label className={styles.criteriaField}>
              MLAs (coma o espacio)
              <textarea
                className={styles.criteriaInput}
                rows={3}
                value={form.mlasText}
                disabled={!canWrite}
                onChange={(e) => setForm((prev) => ({ ...prev, mlasText: e.target.value }))}
                placeholder="MLA123, MLA456"
              />
            </label>
          )}

          {form.scope_mode === SCOPE_RULES && (
            <>
              <fieldset className={styles.periodicidadFieldset}>
                <legend>Tipos de publicación</legend>
                {TIPO_OPCIONES.map((tipo) => (
                  <label key={tipo.id} className={styles.criteriaCheck}>
                    <input
                      type="checkbox"
                      disabled={!canWrite}
                      checked={form.tipos_publicacion.includes(tipo.id)}
                      onChange={() =>
                        setForm((prev) => ({
                          ...prev,
                          tipos_publicacion: toggleId(prev.tipos_publicacion, tipo.id),
                        }))
                      }
                    />
                    {tipo.nombre}
                  </label>
                ))}
              </fieldset>

              <fieldset className={styles.periodicidadFieldset}>
                <legend>Listas de precios</legend>
                {pricelists.length === 0 && (
                  <p className={styles.emptyBody}>Sin listas disponibles.</p>
                )}
                {pricelists.map((lista) => (
                  <label key={lista.id} className={styles.criteriaCheck}>
                    <input
                      type="checkbox"
                      disabled={!canWrite}
                      checked={form.pricelist_ids.includes(Number(lista.id))}
                      onChange={() =>
                        setForm((prev) => ({
                          ...prev,
                          pricelist_ids: toggleId(prev.pricelist_ids, lista.id, true),
                        }))
                      }
                    />
                    {lista.nombre || `Lista ${lista.id}`}
                  </label>
                ))}
              </fieldset>

              <fieldset className={styles.periodicidadFieldset}>
                <legend>Tiendas oficiales</legend>
                {tiendasGrupos.length === 0 && (
                  <p className={styles.emptyBody}>Sin tiendas cargadas.</p>
                )}
                {tiendasGrupos.map((grupo) => {
                  const ids = (grupo.ids || []).map(Number).filter((n) => n > 0);
                  const checked = ids.some((id) => form.tienda_oficial_ids.includes(id));
                  return (
                    <label key={grupo.value} className={styles.criteriaCheck}>
                      <input
                        type="checkbox"
                        disabled={!canWrite}
                        checked={checked}
                        onChange={() => {
                          setForm((prev) => {
                            const set = new Set(prev.tienda_oficial_ids.map(Number));
                            if (checked) ids.forEach((id) => set.delete(id));
                            else ids.forEach((id) => set.add(id));
                            return { ...prev, tienda_oficial_ids: [...set] };
                          });
                        }}
                      />
                      {grupo.label || ids.map((id) => getLabel(id)).join(' / ')}
                    </label>
                  );
                })}
              </fieldset>
            </>
          )}

          {formError && (
            <p className={styles.criteriaFeedbackError} role="alert">
              {formError}
            </p>
          )}
          {formOk && (
            <p className={styles.criteriaFeedbackOk} role="status">
              Suscripción guardada.
            </p>
          )}

          <button type="submit" className={styles.saveCriteriaBtn} disabled={!canWrite || saving}>
            {saving ? 'Guardando…' : 'Guardar'}
          </button>
          {!isNew && (
            <button
              type="button"
              className={styles.secondaryActionBtn}
              disabled={!canWrite || deleting}
              onClick={() => setConfirmOpen(true)}
            >
              Quitar de periodicidad
            </button>
          )}
        </form>
      </div>

      <ModalTesla
        isOpen={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Quitar de periodicidad"
        size="sm"
        closeOnOverlay={false}
        footer={
          <div className={styles.massModalFooter}>
            <button
              type="button"
              className={styles.massModalCancel}
              disabled={deleting}
              onClick={() => setConfirmOpen(false)}
            >
              Cancelar
            </button>
            <button
              type="button"
              className={styles.bulkBtn}
              disabled={deleting}
              onClick={async () => {
                await onDelete();
                setConfirmOpen(false);
              }}
            >
              {deleting ? 'Quitando…' : 'Quitar'}
            </button>
          </div>
        }
      >
        <p className={styles.massModalLead}>
          ¿Sacar el EAN <strong>{selectedEan}</strong> de la revisión periódica? Seguirá
          consultable a mano desde Advisor.
        </p>
      </ModalTesla>
    </aside>
  );
}
