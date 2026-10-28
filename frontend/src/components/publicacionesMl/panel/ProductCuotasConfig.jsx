import { useEffect, useState } from 'react';
import { usePermisos } from '../../../contexts/PermisosContext';
import { preciosAPI, productosAPI } from '../../../services/api';
import { Field, Fields, Section } from './PanelParts';
import styles from './panel.module.css';

const EDIT_PERMISSION = 'productos.editar_precio_cuotas';

// `recalcular_cuotas_auto` as the select's value and back: null follows the global setting.
const recalcValueOf = (stored) => (stored === true ? 'always' : stored === false ? 'never' : 'global');
const RECALC_STORED = { global: null, always: true, never: false };
// The read view and the select say the same.
const RECALC_LABELS = { global: 'Usar la configuración global', always: 'Siempre recalcular', never: 'Nunca recalcular' };

const PERCENT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 });

/** A product's extra markup, or "Global" when it follows the global one. */
const markupText = (value) => (value == null ? 'Global' : `${PERCENT.format(value)} %`);

const LISTS = [
  { key: 'web', label: 'Web', priceField: 'precio_lista_ml' },
  { key: 'pvp', label: 'PVP', priceField: 'precio_pvp' },
];
const LIST_LABELS = Object.fromEntries(LISTS.map(({ key, label }) => [key, label]));

const STORED_FIELDS = ['recalcular_cuotas_auto', 'markup_adicional_cuotas_custom', 'markup_adicional_cuotas_pvp_custom'];

// `complete` is false when the read lacks a setting: the PATCH replaces all three, so it is not offered then.
const settingsOf = (product) => ({
  recalc: recalcValueOf(product.recalcular_cuotas_auto),
  web: product.markup_adicional_cuotas_custom ?? null,
  pvp: product.markup_adicional_cuotas_pvp_custom ?? null,
  complete: STORED_FIELDS.every((field) => field in product),
  // The lists whose instalments a save recalculates (Productos' "recalcular cuotas desde clásica"): those with a price.
  lists: LISTS.filter(({ priceField }) => Number(product[priceField]) > 0).map(({ key }) => key),
});

const inputOf = (value) => (value == null ? '' : String(value));

/**
 * The typed markup as the server takes it: empty is null (the global one); `undefined` is not a number of 0-100.
 * A text field, not a number one: the browser reports a number field it cannot parse ("6,5") as empty, which would
 * be saved as the global markup.
 */
function markupOf(text) {
  const typed = text.trim();
  if (typed === '') return null;
  if (!/^\d+([.,]\d+)?$/.test(typed)) return undefined;
  const value = Number(typed.replace(',', '.'));
  return Number.isFinite(value) && value >= 0 && value <= 100 ? value : undefined;
}

/** Recalculates the instalments of each list from its clásica price, as Productos does after saving; says how it went. */
async function recalculate(productItemId, lists) {
  if (lists.length === 0) return { note: 'Guardado. Sin precio Web ni PVP, no hay cuotas para recalcular.', done: false };
  const results = [];
  // One after the other, as Productos' calls: each reads the settings just stored.
  for (const list of lists) {
    try {
      await preciosAPI.recalcularCuotas(productItemId, list);
      results.push({ list, ok: true });
    } catch (error) {
      const detail = error?.response?.data?.detail;
      results.push({ list, ok: false, reason: typeof detail === 'string' && detail ? detail : 'probá de nuevo' });
    }
  }
  const done = results.filter((r) => r.ok).map((r) => LIST_LABELS[r.list]);
  const failed = results.filter((r) => !r.ok);
  let note = 'Guardado.';
  if (done.length > 0) note += ` Cuotas ${done.join(' y ')} recalculadas desde la clásica.`;
  for (const { list, reason } of failed) note += ` No se pudieron recalcular las ${LIST_LABELS[list]}: ${reason}`;
  return { note, done: done.length > 0 };
}

function describeError(error) {
  if (error?.response?.status === 403) return 'No tenés permiso para editar la configuración de cuotas.';
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' && detail ? detail : 'No se pudo guardar la configuración de cuotas. Probá de nuevo.';
}

/**
 * A product's own instalment settings, as Productos' gear edits them: whether its instalments are recalculated when
 * the price changes (the global setting, always or never) and the extra markup of its Web and PVP instalments (empty
 * follows the global one). Editable with `productos.editar_precio_cuotas`, which the server checks too. Saving then
 * recalculates the instalments of the Web and PVP lists that have a price from their clásica price, as Productos does
 * (`POST /precios/recalcular-cuotas`), and `onRecalculated` tells the panel so its prices are read again.
 * Self-contained so the panel can place it anywhere; mount it with `key={productItemId}`.
 *
 * @param {object} props
 * @param {number} props.productItemId The ERP product.
 * @param {() => void} [props.onRecalculated] Called once a list's instalments were recalculated.
 */
export default function ProductCuotasConfig({ productItemId, onRecalculated }) {
  const { tienePermiso } = usePermisos();
  const [read, setRead] = useState({ status: 'loading', settings: null });
  const [attempt, setAttempt] = useState(0);
  const [form, setForm] = useState(null);
  // What the last save says (saved, and how the recalculation went), or null.
  const [saved, setSaved] = useState(null);

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
    // A read missing a setting would PATCH defaults over values never shown: only a complete read is editable.
    if (!read.settings?.complete) return;
    const { recalc, web, pvp } = read.settings;
    setSaved(null);
    setForm({ recalc, web: inputOf(web), pvp: inputOf(pvp), status: 'editing', error: null });
  };

  const save = async (event) => {
    event.preventDefault();
    if (form.status === 'saving') return;
    const web = markupOf(form.web);
    const pvp = markupOf(form.pvp);
    if (web === undefined || pvp === undefined) {
      setForm({ ...form, error: 'El markup adicional tiene que ser un número de 0 a 100.' });
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
      const { note, done } = await recalculate(productItemId, read.settings.lists);
      if (done) onRecalculated?.();
      setForm(null);
      setSaved(note);
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
      <form className={styles.identityForm} onSubmit={save}>
        <label className={styles.identityField}>
          <span>Recalcular cuotas</span>
          <select
            className={styles.identityInput}
            value={form.recalc}
            disabled={saving}
            onChange={(event) => setForm({ ...form, recalc: event.target.value })}
          >
            {Object.entries(RECALC_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.identityField}>
          <span>Markup adicional cuotas Web (%)</span>
          <input
            type="text"
            inputMode="decimal"
            className={styles.identityInput}
            value={form.web}
            disabled={saving}
            onChange={(event) => setForm({ ...form, web: event.target.value })}
          />
        </label>
        <label className={styles.identityField}>
          <span>Markup adicional cuotas PVP (%)</span>
          <input
            type="text"
            inputMode="decimal"
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
    const { recalc, web, pvp, complete } = read.settings;
    body = (
      <>
        <Fields>
          <Field label="Recalcular cuotas">{RECALC_LABELS[recalc]}</Field>
          <Field label="Markup adicional cuotas Web">{markupText(web)}</Field>
          <Field label="Markup adicional cuotas PVP">{markupText(pvp)}</Field>
        </Fields>
        {tienePermiso(EDIT_PERMISSION) && !complete && (
          <p className={styles.note}>No se pudo leer la configuración completa, así que no se puede editar.</p>
        )}
        {tienePermiso(EDIT_PERMISSION) && complete && (
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
      {saved && !form && read.status === 'ready' && (
        <p className={styles.feedback} role="status">
          {saved}
        </p>
      )}
    </Section>
  );
}
