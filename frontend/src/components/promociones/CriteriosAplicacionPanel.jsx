import { useEffect, useState } from 'react';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import styles from './CriteriosAplicacionPanel.module.css';

const AUTO_ON_HINT =
  'Con Auto-aplicación prendida, el sistema acepta sola la misma sugerencia que verías y enrola esa promo en lugar de flagear. Queda registrado en auditoría si fue auto o manual. Activarlo es tu responsabilidad.';

function emptyForm() {
  return {
    c1_activo: false,
    c1_markup_min: '',
    c1_markup_max: '',
    c2_activo: false,
    c2_solo_markup_positivo: true,
    c6_activo: false,
    c6_solo_via_promo: false,
    c6_gap_min: '5000',
    c6_distancia_objetivo: '100',
    auto_aplicacion: false,
  };
}

function fromApi(data) {
  return {
    c1_activo: Boolean(data.c1_activo),
    c1_markup_min: data.c1_markup_min == null ? '' : String(data.c1_markup_min),
    c1_markup_max: data.c1_markup_max == null ? '' : String(data.c1_markup_max),
    c2_activo: Boolean(data.c2_activo),
    c2_solo_markup_positivo: data.c2_solo_markup_positivo !== false,
    c6_activo: Boolean(data.c6_activo),
    c6_solo_via_promo: Boolean(data.c6_solo_via_promo),
    c6_gap_min: data.c6_gap_min == null ? '5000' : String(data.c6_gap_min),
    c6_distancia_objetivo: data.c6_distancia_objetivo == null ? '100' : String(data.c6_distancia_objetivo),
    auto_aplicacion: Boolean(data.auto_aplicacion),
  };
}

function toPayload(form) {
  const numOrNull = (value) => {
    if (value === '' || value == null) return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  };
  return {
    c1_activo: form.c1_activo,
    c1_markup_min: numOrNull(form.c1_markup_min),
    c1_markup_max: numOrNull(form.c1_markup_max),
    c2_activo: form.c2_activo,
    c2_solo_markup_positivo: form.c2_solo_markup_positivo,
    c6_activo: form.c6_activo,
    c6_solo_via_promo: form.c6_solo_via_promo,
    c6_gap_min: Number(form.c6_gap_min) || 0,
    c6_distancia_objetivo: Number(form.c6_distancia_objetivo) || 0,
    auto_aplicacion: form.auto_aplicacion,
  };
}

/**
 * Criterios de aplicación for one MLA (col2 of Promos). Loads/saves via
 * hay-mejores-criterios API. Mutual exclusion with Ver competencia is owned
 * by PromocionesTab.
 */
export default function CriteriosAplicacionPanel({ mla }) {
  const { tienePermiso } = usePermisos();
  const canWrite = tienePermiso('promos.escribir');
  const [form, setForm] = useState(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSavedFlash(false);
    promocionesAPI
      .getHayMejoresCriterios(mla)
      .then((res) => {
        if (!cancelled) setForm(fromApi(res.data || {}));
      })
      .catch(() => {
        if (!cancelled) setError('No se pudieron cargar los criterios.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mla]);

  const setField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSavedFlash(false);
  };

  const handleSave = async () => {
    if (!canWrite || saving) return;
    setSaving(true);
    setError(null);
    try {
      const res = await promocionesAPI.putHayMejoresCriterios(mla, toPayload(form));
      setForm(fromApi(res.data || {}));
      setSavedFlash(true);
    } catch {
      setError('No se pudieron guardar los criterios.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className={styles.state}>Cargando criterios…</div>;
  }

  return (
    <div className={styles.panel}>
      <section className={styles.section}>
        <label className={styles.checkRow}>
          <input
            type="checkbox"
            checked={form.c1_activo}
            disabled={!canWrite}
            onChange={(e) => setField('c1_activo', e.target.checked)}
          />
          C1 — Límite de markup
        </label>
        {form.c1_activo && (
          <div className={styles.fieldRow}>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>Mín %</span>
              <input
                type="number"
                step="any"
                className={styles.input}
                value={form.c1_markup_min}
                disabled={!canWrite}
                onChange={(e) => setField('c1_markup_min', e.target.value)}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>Máx %</span>
              <input
                type="number"
                step="any"
                className={styles.input}
                value={form.c1_markup_max}
                disabled={!canWrite}
                onChange={(e) => setField('c1_markup_max', e.target.value)}
              />
            </label>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <label className={styles.checkRow}>
          <input
            type="checkbox"
            checked={form.c2_activo}
            disabled={!canWrite}
            onChange={(e) => setField('c2_activo', e.target.checked)}
          />
          C2 — Ganar catálogo
        </label>
        {form.c2_activo && (
          <label className={styles.checkRowNested}>
            <input
              type="checkbox"
              checked={form.c2_solo_markup_positivo}
              disabled={!canWrite}
              onChange={(e) => setField('c2_solo_markup_positivo', e.target.checked)}
            />
            Solo con markup positivo (&gt; 0)
          </label>
        )}
      </section>

      <section className={styles.section}>
        <label className={styles.checkRow}>
          <input
            type="checkbox"
            checked={form.c6_activo}
            disabled={!canWrite}
            onChange={(e) => setField('c6_activo', e.target.checked)}
          />
          C6 — Techo por monopolio
        </label>
        {form.c6_activo && (
          <>
            <label className={styles.checkRowNested}>
              <input
                type="checkbox"
                checked={form.c6_solo_via_promo}
                disabled={!canWrite}
                onChange={(e) => setField('c6_solo_via_promo', e.target.checked)}
              />
              Solo vía promo
            </label>
            <div className={styles.fieldRow}>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>Gap mín $</span>
                <input
                  type="number"
                  step="any"
                  min="0"
                  className={styles.input}
                  value={form.c6_gap_min}
                  disabled={!canWrite}
                  onChange={(e) => setField('c6_gap_min', e.target.value)}
                />
              </label>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>Distancia $</span>
                <input
                  type="number"
                  step="any"
                  min="0"
                  className={styles.input}
                  value={form.c6_distancia_objetivo}
                  disabled={!canWrite}
                  onChange={(e) => setField('c6_distancia_objetivo', e.target.value)}
                />
              </label>
            </div>
          </>
        )}
      </section>

      <section className={styles.section}>
        <label className={styles.checkRow}>
          <input
            type="checkbox"
            checked={form.auto_aplicacion}
            disabled={!canWrite}
            onChange={(e) => setField('auto_aplicacion', e.target.checked)}
          />
          Auto-aplicación
        </label>
        {form.auto_aplicacion && <p className={styles.autoHint}>{AUTO_ON_HINT}</p>}
      </section>

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {savedFlash && !error && <p className={styles.saved}>Guardado.</p>}

      {canWrite && (
        <button
          type="button"
          className="btn-tesla primary sm"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? 'Guardando…' : 'Guardar criterios'}
        </button>
      )}
    </div>
  );
}
