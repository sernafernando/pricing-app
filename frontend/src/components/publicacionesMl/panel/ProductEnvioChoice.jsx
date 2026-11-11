import { useEffect, useId, useState } from 'react';
import { AlertTriangle, Calendar, Save, Truck } from 'lucide-react';
import { usePermisos } from '../../../contexts/PermisosContext';
import { publicacionesMlAPI } from '../../../services/api';
import { amount, timeOfDay } from './format';
import { LISTING_TYPE_LABELS, LOGISTIC_TYPE_LABELS, label } from './labels';
import styles from './productEnvioChoice.module.css';

// The server checks the same permission on the write.
const EDIT_PERMISSION = 'productos.editar_precio_clasica';
// Publications shown before "Ver las N restantes".
const FIRST_PUBLICATIONS = 4;
// Drop-off is "Mercado Envíos" in the design; the shared map leaves it untranslated, so it is added here only.
const LOGISTICS_LABELS = { ...LOGISTIC_TYPE_LABELS, drop_off: 'Mercado Envíos', xd_drop_off: 'Mercado Envíos' };

const money = (value) => (value == null ? null : `$ ${amount(value)}`);
const keyOf = ({ modo, mla }) => (modo === 'mla' ? `mla:${mla}` : modo);
const choiceOf = (key) => (key.startsWith('mla:') ? { modo: 'mla', mla: key.slice(4) } : { modo: key });
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** Why a request failed: the app's envelope message, else `fallback`; a 403 names what was refused. */
function reasonOf(error, { forbidden, fallback }) {
  if (error?.response?.status === 403) return forbidden;
  const data = error?.response?.data;
  const message = data?.error?.message ?? (typeof data?.detail === 'string' ? data.detail : null);
  return message || fallback;
}

/** `dd/mm HH:mm` of a moment, in local time. */
function shortMoment(value) {
  const at = new Date(value);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(at.getDate())}/${pad(at.getMonth() + 1)} ${timeOfDay(value)}`;
}

function lastChange(eleccion) {
  if (!eleccion.updated_at) return 'Sin elección guardada: usa el máximo';
  const who = eleccion.usuario_nombre ? `${eleccion.usuario_nombre} · ` : '';
  return `Último cambio: ${who}${shortMoment(eleccion.updated_at)}`;
}

/** One radio row: label and subtitle on the left, the amount on the right. */
function Option({ name, value, checked, stored, disabled, onChange, title, detail, figure, muted = false }) {
  const className = [styles.option, checked && styles.optionChecked, disabled && styles.optionDisabled].filter(Boolean).join(' ');
  return (
    <label className={className}>
      <input type="radio" name={name} value={value} checked={checked} disabled={disabled} onChange={() => onChange(value)} />
      <span className={styles.optionText}>
        <span className={styles.optionTitle}>
          {title}
          {stored && <span className={styles.selectedBadge}>Seleccionado</span>}
        </span>
        {detail && <span className={styles.optionDetail}>{detail}</span>}
      </span>
      <span className={`${styles.figure} ${muted ? styles.figureMuted : ''}`}>{figure ?? 'Sin costo'}</span>
    </label>
  );
}

/**
 * The product's shipping cost (S7b): every candidate cost at once (the maximum of its active publications, today's
 * behavior; their simple mean; their mean weighted by the units sold; or one publication's own cost) and the one the
 * product uses. A PM with `productos.editar_precio_clasica` picks one and saves it; a save reads the options again
 * and `onSaved` tells the panel, whose list reloads (the markups depend on it). Everyone else sees the stored choice
 * marked. Self-contained; mount it with `key={productItemId}`.
 *
 * @param {object} props
 * @param {number} props.productItemId The ERP product.
 * @param {() => void} [props.onSaved] Called after a choice was stored.
 */
export default function ProductEnvioChoice({ productItemId, onSaved }) {
  const { tienePermiso } = usePermisos();
  const canEdit = tienePermiso(EDIT_PERMISSION);
  const name = useId();
  const [read, setRead] = useState({ status: 'loading', data: null, error: null });
  const [attempt, setAttempt] = useState(0);
  // The option picked and not saved yet (its key), or null: the stored one.
  const [picked, setPicked] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let current = true;
    // Inside the chain, a client that throws becomes the read's error instead of breaking the panel.
    Promise.resolve()
      .then(() => publicacionesMlAPI.productEnvio(productItemId))
      .then(({ data }) => current && setRead({ status: 'ready', data, error: null }))
      .catch((error) => {
        if (!current) return;
        const message = reasonOf(error, {
          forbidden: 'No tenés permiso para ver los costos de envío.',
          fallback: 'No se pudieron cargar los costos de envío.',
        });
        setRead({ status: 'error', data: null, error: message });
      });
    return () => {
      current = false;
    };
  }, [productItemId, attempt]);

  const reload = () => {
    setRead((previous) => (previous.data ? previous : { status: 'loading', data: null, error: null }));
    setAttempt((n) => n + 1);
  };

  let body;
  if (read.status === 'loading') {
    body = (
      <p className={styles.note} role="status">
        Cargando costos de envío…
      </p>
    );
  } else if (read.status === 'error') {
    body = (
      <div className={styles.readError} role="alert">
        <span>{read.error}</span>
        <button type="button" className="btn-tesla outline sm" onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  } else {
    const { publicaciones, promedio, ponderado, max, eleccion } = read.data;
    const storedKey = keyOf(eleccion);
    const checkedKey = picked ?? storedKey;
    const withCost = publicaciones.filter((p) => p.costo != null).length;
    const totalUnits = publicaciones.reduce((sum, p) => sum + (p.unidades ?? 0), 0);
    const sorted = [...publicaciones].sort((a, b) => b.unidades - a.unidades);
    const shown = expanded ? sorted : sorted.slice(0, FIRST_PUBLICATIONS);
    const rest = sorted.length - FIRST_PUBLICATIONS;
    const disabled = !canEdit || saving;
    const choose = (key) => {
      setSaveError(null);
      setPicked(key === storedKey ? null : key);
    };
    const option = (value) => ({
      name,
      value,
      checked: checkedKey === value,
      stored: storedKey === value,
      disabled,
      onChange: choose,
    });

    const save = async () => {
      if (picked == null || saving) return;
      setSaving(true);
      setSaveError(null);
      try {
        await publicacionesMlAPI.saveProductEnvio(productItemId, choiceOf(picked));
      } catch (error) {
        setSaving(false);
        setSaveError(
          reasonOf(error, {
            forbidden: 'No tenés permiso para elegir el costo de envío del producto.',
            fallback: 'No se pudo guardar la elección. Probá de nuevo.',
          }),
        );
        return;
      }
      setSaving(false);
      setPicked(null);
      reload();
      // Last: whatever the panel does with it cannot turn a save that worked into an error here.
      onSaved?.();
    };

    body = (
      <>
        <p className={styles.period}>
          <Calendar size={14} aria-hidden="true" />
          <span>
            Período: <strong>últimos 30 días</strong> · {plural(totalUnits, 'unidad', 'unidades')}
          </span>
        </p>
        <div className={styles.options}>
          {eleccion.warning && (
            <p className={styles.warning} role="note">
              <AlertTriangle size={16} aria-hidden="true" />
              <span>
                La publicación elegida ({eleccion.mla}) está pausada o sin costo: se usa el máximo ({money(max) ?? 'sin costo'}) hasta
                que elijas otra.
              </span>
            </p>
          )}
          <div role="radiogroup" aria-label="Costo de envío del producto" className={styles.group}>
            <Option {...option('max')} title="Máximo (actual)" detail="Valor por defecto si no elegís otro" figure={money(max)} />
            <Option
              {...option('promedio')}
              title="Promedio"
              detail={`Promedio simple de ${plural(withCost, 'publicación activa', 'publicaciones activas')}`}
              figure={money(promedio)}
            />
            <Option
              {...option('ponderado')}
              title="Ponderado por ventas"
              detail={
                ponderado == null
                  ? 'Sin ventas en el período: usa el promedio'
                  : 'Según ventas del período seleccionado · se guarda con los últimos 30 días'
              }
              figure={money(ponderado ?? promedio)}
              muted={ponderado == null}
            />

            <div className={styles.listHeader}>
              <span>Por publicación</span>
              <span className={styles.listCount}>{plural(publicaciones.length, 'publicación', 'publicaciones')}</span>
            </div>
            {shown.map((p) => (
              <Option
                key={p.mla}
                {...option(`mla:${p.mla}`)}
                disabled={disabled || p.costo == null}
                title={
                  <span className={styles.publication}>
                    <span className={styles.mla}>{p.mla}</span>
                    {p.tipo && <span className={styles.chip}>{label(LISTING_TYPE_LABELS, p.tipo)}</span>}
                    {p.logistica && <span className={`${styles.chip} ${styles.chipInfo}`}>{label(LOGISTICS_LABELS, p.logistica)}</span>}
                    <span className={styles.units}>{p.unidades} u.</span>
                    {p.mas_vendida && <span className={`${styles.chip} ${styles.chipSuccess}`}>(más vendida)</span>}
                  </span>
                }
                figure={money(p.costo)}
              />
            ))}
          </div>
          {rest > 0 && (
            <button type="button" className={`btn-tesla outline sm ${styles.more}`} onClick={() => setExpanded(!expanded)}>
              {expanded ? 'Ver menos' : rest === 1 ? 'Ver la restante' : `Ver las ${rest} restantes`}
            </button>
          )}
        </div>
        <div className={styles.footer}>
          <span className={styles.lastChange}>{lastChange(eleccion)}</span>
          {canEdit && (
            <button type="button" className="btn-tesla primary sm" onClick={save} disabled={picked == null || saving}>
              <Save size={14} aria-hidden="true" />
              Guardar elección
            </button>
          )}
        </div>
        {saveError && (
          <p className={styles.saveError} role="alert">
            {saveError}
          </p>
        )}
      </>
    );
  }

  const titleId = `${name}-title`;
  return (
    <section className={styles.card} aria-labelledby={titleId}>
      <header className={styles.header}>
        <span className={styles.icon}>
          <Truck size={20} aria-hidden="true" />
        </span>
        <div>
          <h3 id={titleId} className={styles.title}>
            Costo de envío del producto
          </h3>
          <p className={styles.subtitle}>
            Definí el costo logístico de referencia que impacta en el cálculo de markup y precios de este producto.
          </p>
        </div>
      </header>
      {body}
    </section>
  );
}
