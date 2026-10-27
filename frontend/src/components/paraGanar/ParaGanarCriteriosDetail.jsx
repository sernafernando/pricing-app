import { useEffect, useState } from 'react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import {
  CRITERIA_FLAG_FIELDS,
  CRITERIA_NUMBER_FIELDS,
  EMPTY_CRITERIA_FORM,
  criteriaToForm,
  formToPayload,
  sourceLabel,
} from './criteriaFields';
import ParaGanarCatalogSellers from './ParaGanarCatalogSellers';
import styles from '../../pages/ParaGanarAdvisor.module.css';

export default function ParaGanarCriteriosDetail({ selected }) {
  const { tienePermiso } = usePermisos();
  const canWrite = tienePermiso('productos.editar_precios');

  const [form, setForm] = useState(EMPTY_CRITERIA_FORM);
  const [source, setSource] = useState('default');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [saveOk, setSaveOk] = useState(false);

  useEffect(() => {
    if (!selected?.mla) {
      setForm(EMPTY_CRITERIA_FORM);
      setSource('default');
      setLoadError(null);
      setSaveError(null);
      setSaveOk(false);
      return undefined;
    }

    let cancelled = false;
    async function load() {
      setLoading(true);
      setLoadError(null);
      setSaveError(null);
      setSaveOk(false);
      try {
        const { data } = await api.get(`/para-ganar/criterios/${encodeURIComponent(selected.mla)}`);
        if (cancelled) return;
        setForm(criteriaToForm(data));
        setSource(data.source || 'default');
      } catch (err) {
        if (cancelled) return;
        setForm(EMPTY_CRITERIA_FORM);
        setSource('default');
        if (err.response?.status === 403) {
          setLoadError('No tenés permiso para ver criterios.');
        } else {
          setLoadError('No se pudieron cargar los criterios.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [selected?.mla]);

  const setField = (key, value) => {
    setSaveOk(false);
    setSaveError(null);
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    if (!selected?.mla || !canWrite || saving) return;

    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      const payload = formToPayload(form);
      const { data } = await api.put(
        `/para-ganar/criterios/${encodeURIComponent(selected.mla)}`,
        payload,
      );
      setForm(criteriaToForm(data));
      setSource(data.source || 'mla');
      setSaveOk(true);
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (typeof detail === 'string') {
        setSaveError(detail);
      } else if (err.response?.status === 403) {
        setSaveError('No tenés permiso para guardar criterios (productos.editar_precios).');
      } else if (err.response?.status === 422) {
        setSaveError('Revisá los valores: rangos o números inválidos.');
      } else {
        setSaveError('No se pudieron guardar los criterios.');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside className={styles.detail} aria-label="Criterios de la MLA">
      <div className={styles.panelTitle}>Criterios MLA</div>
      {!selected && (
        <div className={styles.emptyState}>
          <p className={styles.emptyTitle}>Seleccioná un MLA</p>
          <p className={styles.emptyBody}>
            Acá editás los criterios de esa publicación. Origen producto / default PM
            llega después; por ahora se guarda override por MLA.
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
              Origen efectivo: <strong>{sourceLabel(source)}</strong>
              {loading ? ' · cargando…' : ''}
            </div>
          </div>

          {loadError && (
            <p className={styles.criteriaFeedbackError} role="alert">
              {loadError}
            </p>
          )}

          <form
            className={styles.criteriaForm}
            onSubmit={onSubmit}
            aria-label={`Criterios de ${selected.mla}`}
          >
            {CRITERIA_NUMBER_FIELDS.map((field) => (
              <label key={field.key} className={styles.criteriaField}>
                <span>{field.label}</span>
                <input
                  className={styles.criteriaInput}
                  type="text"
                  inputMode="decimal"
                  placeholder={field.placeholder}
                  value={form[field.key]}
                  disabled={loading || !canWrite}
                  onChange={(e) => setField(field.key, e.target.value)}
                />
              </label>
            ))}
            {CRITERIA_FLAG_FIELDS.map((field) => (
              <label key={field.key} className={styles.criteriaCheck}>
                <input
                  type="checkbox"
                  checked={Boolean(form[field.key])}
                  disabled={loading || !canWrite}
                  onChange={(e) => setField(field.key, e.target.checked)}
                />
                {field.label}
              </label>
            ))}
            {saveError && (
              <p className={styles.criteriaFeedbackError} role="alert">
                {saveError}
              </p>
            )}
            {saveOk && (
              <p className={styles.criteriaFeedbackOk} role="status">
                Criterios guardados.
              </p>
            )}
            <button
              type="submit"
              className={styles.saveCriteriaBtn}
              disabled={loading || saving || !canWrite}
              title={canWrite ? undefined : 'Requiere productos.editar_precios'}
            >
              {saving ? 'Guardando…' : 'Guardar criterios de esta MLA'}
            </button>
          </form>

          <ParaGanarCatalogSellers mla={selected.mla} />
        </div>
      )}
    </aside>
  );
}
