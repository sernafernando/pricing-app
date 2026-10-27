import { useEffect, useState } from 'react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { SELLER_DISPOSITIONS } from './sellerDispositions';
import styles from '../../pages/ParaGanarAdvisor.module.css';

export default function ParaGanarCatalogSellers({ mla }) {
  const { tienePermiso } = usePermisos();
  const canWrite = tienePermiso('productos.editar_precios');

  const [catalogProductId, setCatalogProductId] = useState(null);
  const [sellers, setSellers] = useState([]);
  const [draft, setDraft] = useState({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [saveOk, setSaveOk] = useState(false);
  const [synced, setSynced] = useState(false);

  useEffect(() => {
    if (!mla) {
      setSellers([]);
      setDraft({});
      setCatalogProductId(null);
      setError(null);
      setSaveOk(false);
      return undefined;
    }

    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      setSaveOk(false);
      try {
        let { data } = await api.get(
          `/para-ganar/criterios/${encodeURIComponent(mla)}/sellers`,
        );
        // Persist competition members only when the user can write.
        if (canWrite && data.catalog_product_id) {
          try {
            const synced = await api.post(
              `/para-ganar/criterios/${encodeURIComponent(mla)}/sellers/sync`,
            );
            data = synced.data;
          } catch {
            // Keep the read-only merge if sync fails (e.g. no snapshot yet).
          }
        }
        if (cancelled) return;
        setCatalogProductId(data.catalog_product_id || null);
        setSynced(Boolean(data.synced_from_competition));
        const rows = data.sellers || [];
        setSellers(rows);
        const nextDraft = {};
        rows.forEach((row) => {
          nextDraft[row.seller_id] = row.disposition || 'active';
        });
        setDraft(nextDraft);
      } catch (err) {
        if (cancelled) return;
        setSellers([]);
        setDraft({});
        if (err.response?.status === 403) {
          setError('No tenés permiso para ver sellers del catálogo.');
        } else {
          setError('No se pudo cargar el roster de sellers.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [mla, canWrite]);

  const dirty = sellers.some(
    (row) => (draft[row.seller_id] || 'active') !== (row.disposition || 'active'),
  );

  const onSave = async () => {
    if (!mla || !canWrite || saving || !dirty) return;
    setSaving(true);
    setError(null);
    setSaveOk(false);
    try {
      const payload = {
        sellers: sellers.map((row) => ({
          seller_id: row.seller_id,
          disposition: draft[row.seller_id] || 'active',
        })),
      };
      const { data } = await api.put(
        `/para-ganar/criterios/${encodeURIComponent(mla)}/sellers`,
        payload,
      );
      const rows = data.sellers || [];
      setSellers(rows);
      const nextDraft = {};
      rows.forEach((row) => {
        nextDraft[row.seller_id] = row.disposition || 'active';
      });
      setDraft(nextDraft);
      setSaveOk(true);
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (typeof detail === 'string') {
        setError(detail);
      } else if (err.response?.status === 403) {
        setError('No tenés permiso para guardar disposiciones (productos.editar_precios).');
      } else {
        setError('No se pudieron guardar las disposiciones.');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className={styles.sellersBlock} aria-label="Sellers del catálogo">
      <h3 className={styles.sellersTitle}>Sellers del catálogo</h3>
      <p className={styles.sellersHint}>
        {catalogProductId
          ? `Catálogo ${catalogProductId}${synced ? ' · sincronizado desde competencia' : ''}`
          : 'Esta MLA no tiene catalog_product_id; no hay roster.'}
      </p>

      {loading && <p className={styles.sellersHint}>Cargando sellers…</p>}
      {error && (
        <p className={styles.criteriaFeedbackError} role="alert">
          {error}
        </p>
      )}

      {!loading && catalogProductId && sellers.length === 0 && (
        <p className={styles.sellersHint}>
          Todavía no hay sellers guardados. Aparecen cuando exista un snapshot de
          competencia de catálogo para este producto.
        </p>
      )}

      {!loading && sellers.length > 0 && (
        <ul className={styles.sellersList}>
          {sellers.map((row) => (
            <li key={row.seller_id} className={styles.sellerRow}>
              <div className={styles.sellerIdentity}>
                <span className={styles.sellerNick}>
                  {row.nickname || `Seller ${row.seller_id}`}
                </span>
                <span className={styles.sellerMeta}>id {row.seller_id}</span>
              </div>
              <label className={styles.sellerDisposition}>
                <span className={styles.srOnly}>Disposición</span>
                <select
                  className={styles.criteriaInput}
                  value={draft[row.seller_id] || 'active'}
                  disabled={!canWrite || saving}
                  onChange={(e) => {
                    setSaveOk(false);
                    setDraft((prev) => ({ ...prev, [row.seller_id]: e.target.value }));
                  }}
                >
                  {SELLER_DISPOSITIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>
            </li>
          ))}
        </ul>
      )}

      {saveOk && (
        <p className={styles.criteriaFeedbackOk} role="status">
          Disposiciones guardadas.
        </p>
      )}

      {sellers.length > 0 && (
        <button
          type="button"
          className={styles.saveCriteriaBtn}
          disabled={!canWrite || saving || !dirty}
          onClick={onSave}
          title={canWrite ? undefined : 'Requiere productos.editar_precios'}
        >
          {saving ? 'Guardando…' : 'Guardar disposiciones de sellers'}
        </button>
      )}
    </section>
  );
}
