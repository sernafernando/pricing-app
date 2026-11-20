import { useEffect, useState } from 'react';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { statusQuoGanaCatalogo } from './statusQuoGanaCatalogo';
import styles from './CriteriosAplicacionPanel.module.css';

const AUTO_ON_HINT =
  'Con Auto-aplicación prendida, el sistema acepta sola la misma sugerencia que verías y enrola esa promo en lugar de flagear. Queda registrado en auditoría si fue auto o manual. Activarlo es tu responsabilidad.';

const C2_YA_GANANDO_HINT =
  'Ya estás ganando el catálogo (ranking efectivo). C2 queda prendido pero no flagea hasta que dejes de ganar; ahí sí va a buscar una promo que te recupere el #1.';

function emptyForm() {
  return {
    c1_activo: false,
    c1_markup_min: '',
    c1_markup_max: '',
    c2_activo: false,
    c2_solo_markup_positivo: true,
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
  // Manual override only (not on any role): show/change the Auto-aplicación checkbox.
  const canAuto = tienePermiso('promos.auto_aplicacion');
  const [form, setForm] = useState(emptyForm);
  const [sellersExcluidos, setSellersExcluidos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const [yaGanandoCatalogo, setYaGanandoCatalogo] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSavedFlash(false);
    setYaGanandoCatalogo(false);
    promocionesAPI
      .getHayMejoresCriterios(mla)
      .then((res) => {
        if (cancelled) return;
        const data = res.data || {};
        setForm(fromApi(data));
        setSellersExcluidos(Array.isArray(data.sellers_excluidos) ? data.sellers_excluidos.map(String) : []);
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

  const sellersExcluidosKey = sellersExcluidos.slice().sort().join('|');

  // When C2 is on, refresh the "ya ganando" banner from the latest catalog snapshot.
  useEffect(() => {
    if (!form.c2_activo || !mla) {
      setYaGanandoCatalogo(false);
      return undefined;
    }
    let cancelled = false;
    const excluded = sellersExcluidosKey ? sellersExcluidosKey.split('|') : [];
    promocionesAPI
      .getCompetenciaCatalogo(mla)
      .then((res) => {
        if (cancelled) return;
        setYaGanandoCatalogo(statusQuoGanaCatalogo(res.data || {}, { mla, sellersExcluidos: excluded }));
      })
      .catch(() => {
        if (!cancelled) setYaGanandoCatalogo(false);
      });
    return () => {
      cancelled = true;
    };
  }, [form.c2_activo, mla, sellersExcluidosKey]);

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
          <>
            <label className={styles.checkRowNested}>
              <input
                type="checkbox"
                checked={form.c2_solo_markup_positivo}
                disabled={!canWrite}
                onChange={(e) => setField('c2_solo_markup_positivo', e.target.checked)}
              />
              Solo con markup positivo (&gt; 0)
            </label>
            {yaGanandoCatalogo && (
              <p className={styles.c2YaGanando} role="status">
                {C2_YA_GANANDO_HINT}
              </p>
            )}
          </>
        )}
      </section>

      {canAuto && (
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
      )}

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
