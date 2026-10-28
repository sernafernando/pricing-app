import { useEffect, useState } from 'react';
import { usePermisos } from '../../../contexts/PermisosContext';
import { preciosAPI, productosAPI } from '../../../services/api';
import { Field, Fields, Section } from './PanelParts';
import styles from './panel.module.css';

const EDIT_PERMISSION = 'productos.editar_precio_cuotas';

// `recalcular_cuotas_auto` as the select's value and back: null follows the global setting.
const RECALC_VALUE = (stored) => (stored === true ? 'always' : stored === false ? 'never' : 'global');
const RECALC_STORED = { global: null, always: true, never: false };
const RECALC_LABELS = { global: 'Usa la configuración global', always: 'Siempre', never: 'Nunca' };

const PERCENT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 });

/** A product's extra markup, or "Global" when it follows the global one. */
const markupText = (value) => (value == null ? 'Global' : `${PERCENT.format(value)} %`);

const settingsOf = (product) => ({
  recalc: RECALC_VALUE(product.recalcular_cuotas_auto),
  web: product.markup_adicional_cuotas_custom ?? null,
  pvp: product.markup_adicional_cuotas_pvp_custom ?? null,
});

const inputOf = (value) => (value == null ? '' : String(value));

/** The typed markup as the server takes it: empty is null (the global one); `undefined` is out of 0-100. */
function markupOf(text) {
  if (text.trim() === '') return null;
  const value = Number(text);
  return Number.isFinite(value) && value >= 0 && value <= 100 ? value : undefined;
}

function describeError(error) {
  if (error?.response?.status === 403) return 'No tenés permiso para editar la configuración de cuotas.';
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' && detail ? detail : 'No se pudo guardar la configuración de cuotas. Probá de nuevo.';
}

/**
 * A product's own instalment settings, as Productos' gear edits them: whether its instalments are recalculated when
 * the price changes (the global setting, always or never) and the extra markup of its Web and PVP instalments (empty
 * follows the global one). Editable with `productos.editar_precio_cuotas`, which the server checks too. Saving changes
 * no price: the settings apply the next time the instalments are recalculated. Self-contained so the panel can place
 * it anywhere; mount it with `key={productItemId}`.
 *
 * @param {object} props
 * @param {number} props.productItemId The ERP product.
 */
export default function ProductCuotasConfig({ productItemId }) {
  const { tienePermiso } = usePermisos();
  const [read, setRead] = useState({ status: 'loading', settings: null });
  const [attempt, setAttempt] = useState(0);
  const [form, setForm] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let current = true;
    preciosAPI
      .obtenerProducto(productItemId)
      .then(({ data }) => current && setRead({ status: 'ready', settings: settingsOf(data) }))
      .catch(() => current && setRead({ status: 'error', settings: null }));
    return () => {
      current = false;
    };
  }, [productItemId, attempt]);

  const reload = () => {
    setRead({ status: 'loading', settings: null });
    setAttempt((n) => n + 1);
  };

  const edit = () => {
    const { recalc, web, pvp } = read.settings;
    setSaved(false);
    setForm({ recalc, web: inputOf(web), pvp: inputOf(pvp), status: 'editing', error: null });
  };

  const save = async (event) => {
    event.preventDefault();
    if (form.status === 'saving') return;
    const web = markupOf(form.web);
    const pvp = markupOf(form.pvp);
    if (web === undefined || pvp === undefined) {
      setForm({ ...form, error: 'El markup adicional va de 0 a 100.' });
      return;
    }
    setForm({ ...form, status: 'saving', error: null });
    try {
      // The PATCH replaces all three: an untouched one is sent as it was.
      await productosAPI.configCuotas(productItemId, {
        recalcular_cuotas_auto: RECALC_STORED[form.recalc],
        markup_adicional_cuotas_custom: web,
        markup_adicional_cuotas_pvp_custom: pvp,
      });
      setForm(null);
      setSaved(true);
      // Show what is stored, not what was typed.
      reload();
    } catch (error) {
      setForm((current) => current && { ...current, status: 'editing', error: describeError(error) });
    }
  };

  let body;
  if (read.status === 'loading') {
    body = (
      <p className={styles.note} role="status">
        Cargando configuración de cuotas…
      </p>
    );
  } else if (read.status === 'error') {
    body = (
      <div className={styles.error} role="alert">
        <span>No se pudo cargar la configuración de cuotas.</span>
        <button type="button" className="btn-tesla outline sm" onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  } else if (form) {
    const saving = form.status === 'saving';
    body = (
      <form className={styles.identityForm} onSubmit={save} noValidate>
        <label className={styles.identityField}>
          <span>Recalcular cuotas</span>
          <select
            className={styles.identityInput}
            value={form.recalc}
            disabled={saving}
            onChange={(event) => setForm({ ...form, recalc: event.target.value })}
          >
            <option value="global">Usar la configuración global</option>
            <option value="always">Siempre recalcular</option>
            <option value="never">Nunca recalcular</option>
          </select>
        </label>
        <label className={styles.identityField}>
          <span>Markup adicional cuotas Web (%)</span>
          <input
            type="number"
            min="0"
            max="100"
            step="0.1"
            className={styles.identityInput}
            value={form.web}
            disabled={saving}
            onChange={(event) => setForm({ ...form, web: event.target.value })}
          />
        </label>
        <label className={styles.identityField}>
          <span>Markup adicional cuotas PVP (%)</span>
          <input
            type="number"
            min="0"
            max="100"
            step="0.1"
            className={styles.identityInput}
            value={form.pvp}
            disabled={saving}
            onChange={(event) => setForm({ ...form, pvp: event.target.value })}
          />
        </label>
        <p className={styles.note}>Vacío: el markup adicional global.</p>
        <div className={styles.statusConfirm}>
          <button type="submit" className="btn-tesla primary sm" disabled={saving}>
            Guardar
          </button>
          <button type="button" className="btn-tesla outline sm" onClick={() => setForm(null)} disabled={saving}>
            Cancelar
          </button>
        </div>
        {form.error && (
          <p className={styles.feedback} role="alert">
            {form.error}
          </p>
        )}
      </form>
    );
  } else {
    const { recalc, web, pvp } = read.settings;
    body = (
      <>
        <Fields>
          <Field label="Recalcular cuotas">{RECALC_LABELS[recalc]}</Field>
          <Field label="Markup adicional cuotas Web">{markupText(web)}</Field>
          <Field label="Markup adicional cuotas PVP">{markupText(pvp)}</Field>
        </Fields>
        {tienePermiso(EDIT_PERMISSION) && (
          <button type="button" className={`btn-tesla outline sm ${styles.identityEdit}`} onClick={edit}>
            Editar cuotas
          </button>
        )}
      </>
    );
  }

  return (
    <Section title="Configuración de cuotas">
      {body}
      {saved && !form && (
        <p className={styles.feedback} role="status">
          Guardado. No cambia ningún precio: se aplica la próxima vez que se recalculen las cuotas.
        </p>
      )}
    </Section>
  );
}
