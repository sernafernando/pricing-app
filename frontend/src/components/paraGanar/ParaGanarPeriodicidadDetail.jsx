import { useEffect, useMemo, useState } from 'react';
import ModalTesla from '../ModalTesla';
import { SCOPE_ALL, SCOPE_MLAS, SCOPE_RULES, TIPO_OPCIONES } from './periodicidadForm';
import styles from '../../pages/ParaGanarAdvisor.module.css';

function toggleId(list, id, asNumber = false) {
  const value = asNumber ? Number(id) : id;
  const next = new Set(list.map((item) => (asNumber ? Number(item) : item)));
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return [...next];
}

function matchesLocalFilters(opt, filters) {
  if (filters.tipos.length > 0) {
    if (!opt.tipo_publicacion || !filters.tipos.includes(opt.tipo_publicacion)) return false;
  }
  if (filters.pricelists.length > 0) {
    if (opt.pricelist_id == null || !filters.pricelists.includes(Number(opt.pricelist_id))) {
      return false;
    }
  }
  if (filters.tiendas.length > 0) {
    if (opt.tienda_oficial_id == null || !filters.tiendas.includes(Number(opt.tienda_oficial_id))) {
      return false;
    }
  }
  return true;
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
  mlaOptions,
  mlasLoading,
  onSave,
  onDelete,
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [filterTipos, setFilterTipos] = useState([]);
  const [filterPricelists, setFilterPricelists] = useState([]);
  const [filterTiendas, setFilterTiendas] = useState([]);

  useEffect(() => {
    setFilterTipos([]);
    setFilterPricelists([]);
    setFilterTiendas([]);
    setConfirmOpen(false);
  }, [selectedEan]);

  const isLegacyRules = form.scope_mode === SCOPE_RULES;
  const todoElEan = form.scope_mode === SCOPE_ALL;
  const selectedSet = new Set((form.mlas || []).map((m) => String(m).toUpperCase()));

  const filteredMlas = useMemo(() => {
    const filters = {
      tipos: filterTipos,
      pricelists: filterPricelists,
      tiendas: filterTiendas,
    };
    return (mlaOptions || []).filter((opt) => matchesLocalFilters(opt, filters));
  }, [mlaOptions, filterTipos, filterPricelists, filterTiendas]);

  if (!selectedEan) {
    return (
      <aside className={styles.detail} aria-label="Detalle de suscripción">
        <div className={styles.panelTitle}>Detalle</div>
        <div className={styles.emptyState}>
          <p className={styles.emptyTitle}>Seleccioná un EAN</p>
          <p className={styles.emptyBody}>
            La lista de la izquierda usa los mismos filtros de alcance. Desde acá
            suscribís o editás la periodicidad.
          </p>
        </div>
      </aside>
    );
  }

  const setTodoElEan = (checked) => {
    if (checked) {
      setForm((prev) => ({
        ...prev,
        scope_mode: SCOPE_ALL,
        mlas: [],
        tipos_publicacion: [],
        pricelist_ids: [],
        tienda_oficial_ids: [],
      }));
      return;
    }
    const allVisible = filteredMlas.map((opt) => String(opt.mla).toUpperCase());
    setForm((prev) => ({
      ...prev,
      scope_mode: SCOPE_MLAS,
      mlas: allVisible,
      tipos_publicacion: [],
      pricelist_ids: [],
      tienda_oficial_ids: [],
    }));
  };

  const toggleMla = (mla) => {
    setForm((prev) => {
      const nextMlas = toggleId(
        (prev.mlas || []).map((x) => String(x).toUpperCase()),
        String(mla).toUpperCase(),
      );
      return {
        ...prev,
        scope_mode: SCOPE_MLAS,
        mlas: nextMlas,
        tipos_publicacion: [],
        pricelist_ids: [],
        tienda_oficial_ids: [],
      };
    });
  };

  const visibleIds = filteredMlas.map((opt) => String(opt.mla).toUpperCase());
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((mla) => selectedSet.has(mla));

  const selectAllVisible = () => {
    setForm((prev) => {
      const next = new Set((prev.mlas || []).map((m) => String(m).toUpperCase()));
      visibleIds.forEach((mla) => next.add(mla));
      return {
        ...prev,
        scope_mode: SCOPE_MLAS,
        mlas: [...next],
        tipos_publicacion: [],
        pricelist_ids: [],
        tienda_oficial_ids: [],
      };
    });
  };

  const deselectAllVisible = () => {
    const drop = new Set(visibleIds);
    setForm((prev) => ({
      ...prev,
      scope_mode: SCOPE_MLAS,
      mlas: (prev.mlas || [])
        .map((m) => String(m).toUpperCase())
        .filter((mla) => !drop.has(mla)),
      tipos_publicacion: [],
      pricelist_ids: [],
      tienda_oficial_ids: [],
    }));
  };

  return (
    <aside className={styles.detail} aria-label="Detalle de suscripción">
      <div className={styles.panelTitle}>Detalle</div>
      <div className={styles.criteriaPanel}>
        <div className={styles.criteriaIdentity}>
          <div className={styles.mla}>{selectedEan}</div>
          <div className={styles.criteriaIdentityMeta}>
            {isNew ? 'Sin suscribir — al guardar entra a periodicidad' : 'Suscripción guardada'}
          </div>
        </div>

        <form
          className={`${styles.criteriaForm} ${styles.periodicidadForm}`}
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

          <label className={styles.criteriaCheck}>
            <input
              type="checkbox"
              checked={todoElEan}
              disabled={!canWrite}
              onChange={(e) => setTodoElEan(e.target.checked)}
            />
            Todo el EAN (incluye MLAs futuros)
          </label>

          {isLegacyRules && (
            <p className={styles.criteriaFeedbackError} role="status">
              Suscripción por reglas (legado). Elegí Todo el EAN o tildá MLAs y guardá para
              migrarla.
            </p>
          )}

          <fieldset className={styles.periodicidadFieldset}>
            <legend>Filtros del listado</legend>
            <p className={styles.emptyBody}>
              Achican los checkboxes de abajo; no definen la suscripción.
            </p>
            <div className={styles.periodicidadFilterRow} role="group" aria-label="Tipo">
              {TIPO_OPCIONES.map((tipo) => (
                <label key={tipo.id} className={styles.criteriaCheck}>
                  <input
                    type="checkbox"
                    checked={filterTipos.includes(tipo.id)}
                    onChange={() => setFilterTipos((prev) => toggleId(prev, tipo.id))}
                  />
                  {tipo.nombre}
                </label>
              ))}
            </div>
            <div className={styles.periodicidadFilterRow} role="group" aria-label="Lista">
              {pricelists.length === 0 && <span className={styles.emptyBody}>Sin listas</span>}
              {pricelists.map((lista) => (
                <label key={lista.id} className={styles.criteriaCheck}>
                  <input
                    type="checkbox"
                    checked={filterPricelists.includes(Number(lista.id))}
                    onChange={() =>
                      setFilterPricelists((prev) => toggleId(prev, lista.id, true))
                    }
                  />
                  {lista.nombre || `Lista ${lista.id}`}
                </label>
              ))}
            </div>
            <div className={styles.periodicidadFilterRow} role="group" aria-label="Tienda">
              {tiendasGrupos.length === 0 && <span className={styles.emptyBody}>Sin tiendas</span>}
              {tiendasGrupos.map((grupo) => {
                const ids = (grupo.ids || []).map(Number).filter((n) => n > 0);
                const checked = ids.some((id) => filterTiendas.includes(id));
                return (
                  <label key={grupo.value} className={styles.criteriaCheck}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => {
                        setFilterTiendas((prev) => {
                          const set = new Set(prev.map(Number));
                          if (checked) ids.forEach((id) => set.delete(id));
                          else ids.forEach((id) => set.add(id));
                          return [...set];
                        });
                      }}
                    />
                    {grupo.label || ids.map((id) => getLabel(id)).join(' / ')}
                  </label>
                );
              })}
            </div>
          </fieldset>

          <fieldset className={`${styles.periodicidadFieldset} ${styles.periodicidadMlaFieldset}`}>
            <legend>
              MLAs ({filteredMlas.length}
              {filteredMlas.length !== (mlaOptions || []).length
                ? ` de ${(mlaOptions || []).length}`
                : ''}
              )
            </legend>
            <div className={styles.periodicidadMlaToolbar}>
              <button
                type="button"
                className={styles.pagerBtn}
                disabled={!canWrite || todoElEan || mlasLoading || visibleIds.length === 0}
                onClick={allVisibleSelected ? deselectAllVisible : selectAllVisible}
              >
                {allVisibleSelected ? 'Deseleccionar todos' : 'Seleccionar todos'}
              </button>
              <span className={styles.toolbarHint}>
                Solo los visibles (filtros); no cubre MLAs futuros
              </span>
            </div>
            {mlasLoading && <p className={styles.emptyBody}>Cargando MLAs…</p>}
            {!mlasLoading && filteredMlas.length === 0 && (
              <p className={styles.emptyBody}>
                No hay MLAs con el alcance / filtros actuales.
              </p>
            )}
            {!mlasLoading && filteredMlas.length > 0 && (
              <div className={styles.periodicidadMlaList} role="list">
                {filteredMlas.map((opt) => {
                  const mla = String(opt.mla).toUpperCase();
                  const checked = todoElEan || selectedSet.has(mla);
                  const tiendaLabel =
                    opt.tienda_oficial_id != null
                      ? getLabel(opt.tienda_oficial_id) || `Tienda ${opt.tienda_oficial_id}`
                      : 'Sin tienda';
                  return (
                    <label
                      key={mla}
                      role="listitem"
                      className={`${styles.criteriaCheck} ${
                        opt.criterios_aplicados
                          ? styles.periodicidadMlaConCriterio
                          : styles.periodicidadMlaSinCriterio
                      }`}
                    >
                      <input
                        type="checkbox"
                        disabled={!canWrite || todoElEan}
                        checked={checked}
                        onChange={() => toggleMla(mla)}
                      />
                      <span>
                        <strong>{mla}</strong>
                        {' · '}
                        {opt.tipo_nombre || opt.tipo_publicacion || 'Tipo —'}
                        {' · '}
                        {opt.lista_nombre ||
                          (opt.pricelist_id != null ? `Lista ${opt.pricelist_id}` : 'Lista —')}
                        {' · '}
                        {tiendaLabel}
                        {' · '}
                        <span
                          className={
                            opt.criterios_aplicados
                              ? styles.periodicidadCriterioBadge
                              : styles.periodicidadSinCriterioBadge
                          }
                        >
                          {opt.criterios_aplicados ? 'Con criterio' : 'Sin criterio'}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </fieldset>

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
            {saving ? 'Guardando…' : isNew ? 'Suscribir EAN' : 'Guardar'}
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
          visible en el catálogo y consultable a mano desde Advisor.
        </p>
      </ModalTesla>
    </aside>
  );
}
