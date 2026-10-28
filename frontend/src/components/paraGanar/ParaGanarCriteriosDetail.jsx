import { useEffect, useRef, useState } from 'react';
import api, { preciosAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { useDebounce } from '../../hooks/useDebounce';
import {
  CRITERIA_FLAG_FIELDS,
  CRITERIA_NUMBER_FIELDS,
  EMPTY_CRITERIA_FORM,
  criteriaToForm,
  formToPayload,
  sourceLabel,
} from './criteriaFields';
import { MARKUP_PRICE_LINKS, resolveLinkedCriteriaValue } from './criteriaMarkupPriceSync';
import ParaGanarCatalogSellers from './ParaGanarCatalogSellers';
import styles from '../../pages/ParaGanarAdvisor.module.css';

export default function ParaGanarCriteriosDetail({ selected }) {
  const { tienePermiso } = usePermisos();
  const canWrite = tienePermiso('productos.editar_precios');

  const [form, setForm] = useState(EMPTY_CRITERIA_FORM);
  const [source, setSource] = useState('default');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [syncError, setSyncError] = useState(null);
  const [saveOk, setSaveOk] = useState(false);
  const [pendingSync, setPendingSync] = useState(null);
  const syncSeq = useRef(0);
  const latestSyncToken = useRef(null);

  const debouncedSync = useDebounce(pendingSync, 350);
  const itemId = selected?.item_id ?? null;
  const pricelistId = selected?.pricelist_id ?? null;
  const canPriceSync = itemId != null && pricelistId != null;

  useEffect(() => {
    if (!selected?.mla) {
      setForm(EMPTY_CRITERIA_FORM);
      setSource('default');
      setLoadError(null);
      setSaveError(null);
      setSyncError(null);
      setSaveOk(false);
      setPendingSync(null);
      return undefined;
    }

    let cancelled = false;
    async function load() {
      setLoading(true);
      setLoadError(null);
      setSaveError(null);
      setSyncError(null);
      setSaveOk(false);
      setPendingSync(null);
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

  useEffect(() => {
    if (!debouncedSync || !canPriceSync) return undefined;

    const { key, value, token } = debouncedSync;
    if (!MARKUP_PRICE_LINKS[key]) return undefined;

    let cancelled = false;
    const seq = ++syncSeq.current;

    async function run() {
      setSyncing(true);
      setSyncError(null);
      try {
        const result = await resolveLinkedCriteriaValue({
          key,
          rawValue: value,
          itemId,
          pricelistId,
          calcularPorMarkup: preciosAPI.calcularPorMarkup,
          calcularMarkup: preciosAPI.calcularMarkup,
        });
        if (cancelled || seq !== syncSeq.current) return;
        if (token !== latestSyncToken.current) return;
        if (!result) return;
        setForm((prev) => ({ ...prev, [result.peer]: result.peerValue }));
      } catch {
        if (cancelled || seq !== syncSeq.current) return;
        setSyncError('No se pudo sincronizar markup ↔ precio con la cuenta de Pricing.');
      } finally {
        if (!cancelled && seq === syncSeq.current) setSyncing(false);
      }
    }

    run();
    return () => {
      cancelled = true;
    };
  }, [debouncedSync, canPriceSync, itemId, pricelistId]);

  const setField = (key, value) => {
    setSaveOk(false);
    setSaveError(null);
    setSyncError(null);
    setForm((prev) => ({ ...prev, [key]: value }));
    if (MARKUP_PRICE_LINKS[key] && canPriceSync) {
      const token = Date.now();
      latestSyncToken.current = token;
      setPendingSync({ key, value, token });
    }
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
              {syncing ? ' · sync Pricing…' : ''}
            </div>
          </div>

          {loadError && (
            <p className={styles.criteriaFeedbackError} role="alert">
              {loadError}
            </p>
          )}
          {!loading && !canPriceSync && (
            <p className={styles.emptyBody} role="status">
              Sin item_id o pricelist_id en la cola: markup y precio no se sincronizan con Pricing.
            </p>
          )}
          {syncError && (
            <p className={styles.criteriaFeedbackError} role="alert">
              {syncError}
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
                  title={field.hint}
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
