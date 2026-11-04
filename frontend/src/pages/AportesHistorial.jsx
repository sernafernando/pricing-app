/**
 * AportesHistorial — the history of one aporte (ml-ads-aportes-vista S4), laid out as the approved Stitch modal
 * "Historial del aporte" (973006a2): every audit row of `GET /ml-ads/contributions/{id}/history`, oldest first. A load
 * lists what was loaded; an edit lists only what changed, the old value struck through; a deletion says who and when.
 */
import { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import ModalTesla from '../components/ModalTesla';
import { StatusPill } from '../components/kit';
import api from '../services/api';
import { apiErrorMessage } from '../utils/apiErrorMessage';
import { formatSignedMoney } from '../utils/ventasMlTone';
import { scopeOf } from '../utils/aportesScope';
import { dayMonth, stampDateTime } from '../utils/aportesDates';
import styles from './AportesHistorial.module.css';

const ACTIONS = {
  created: { text: 'Cargado', tone: 'info' },
  edited: { text: 'Editado', tone: 'warning' },
  deleted: { text: 'Borrado', tone: 'danger' },
};

const KINDS = { percentage: 'Porcentaje', fixed_amount: 'Monto fijo' };
const SETTLEMENTS = { full: 'Se recibe todo', refund_difference: 'Devuelve la diferencia' };

const valueText = (snap) =>
  snap.kind === 'percentage'
    ? `${Number(snap.value).toLocaleString('es-AR', { maximumFractionDigits: 2 })} %`
    : formatSignedMoney(Number(snap.value));
const fullDay = (iso) => iso.split('-').reverse().join('/');
const rangeText = (snap, withYear) =>
  withYear ? `${fullDay(snap.date_from)} → ${fullDay(snap.date_to)}` : `${dayMonth(snap.date_from)} → ${dayMonth(snap.date_to)}`;

/**
 * The fields of a snapshot, in the form's order. `same(before, after)`: whether an edit left it alone (on the raw
 * values, so a change the text hides, such as only the year of a date, still shows); `loaded`: what a load lists, as
 * the design (type, value, settlement of a fixed amount, range); `mono`: figures, set in monospace.
 */
const FIELDS = [
  { label: () => 'Marca', text: (s) => s.brand || 'Sin marca', same: (a, b) => a.brand === b.brand },
  {
    label: () => 'Campaña',
    text: (s) => (s.campaign_id == null ? 'Toda la cuenta Display' : String(s.campaign_id)),
    same: (a, b) => a.campaign_id === b.campaign_id,
  },
  { label: () => 'Tipo', text: (s) => KINDS[s.kind] || s.kind, same: (a, b) => a.kind === b.kind, loaded: () => true },
  {
    // Named by its kind; "Valor" when an edit changed the kind, so neither side is mislabeled.
    label: (before, after) =>
      before && before.kind !== after.kind ? 'Valor' : after.kind === 'percentage' ? 'Porcentaje' : 'Monto',
    text: valueText,
    same: (a, b) => a.kind === b.kind && Number(a.value) === Number(b.value),
    loaded: () => true,
    mono: true,
  },
  {
    label: () => 'Cómo se liquida',
    text: (s) => SETTLEMENTS[s.settlement] || 'Sin liquidación',
    same: (a, b) => a.settlement === b.settlement,
    loaded: (s) => Boolean(s.settlement),
  },
  {
    label: () => 'Rango',
    text: rangeText,
    same: (a, b) => a.date_from === b.date_from && a.date_to === b.date_to,
    loaded: () => true,
  },
  { label: () => 'Nota', text: (s) => s.note || 'Sin nota', same: (a, b) => (a.note || null) === (b.note || null) },
];

/** What a load shows: the loaded fields of its snapshot. */
const loadedLines = (snap) =>
  FIELDS.filter((f) => f.loaded?.(snap)).map((f) => ({ label: f.label(null, snap), after: f.text(snap), mono: f.mono }));

/** What an edit changed, field by field. A range whose day and month read the same shows its years. */
function changedLines(before, after) {
  return FIELDS.filter((f) => !f.same(before, after)).map((f) => {
    let [old, now] = [f.text(before), f.text(after)];
    if (old === now) [old, now] = [f.text(before, true), f.text(after, true)];
    return { label: f.label(before, after), before: old, after: now, mono: f.mono };
  });
}

function linesOf(event) {
  if (event.action === 'created' && event.after) return loadedLines(event.after);
  if (event.action === 'edited' && event.before && event.after) return changedLines(event.before, event.after);
  return [];
}

function Event({ event }) {
  const action = ACTIONS[event.action] || { text: event.action, tone: 'neutral' };
  const lines = linesOf(event);
  return (
    <li className={`${styles.event} ${styles[event.action] || ''}`}>
      <div className={styles.head}>
        <StatusPill tone={action.tone}>{action.text}</StatusPill>
        <span className={styles.who}>{`${event.user || 'Sin dato'} · ${stampDateTime(event.at)}`}</span>
      </div>
      {lines.length > 0 && (
        <ul className={styles.lines}>
          {lines.map((line) => {
            const mono = line.mono ? styles.mono : '';
            return (
              <li key={line.label}>
                {`${line.label}: `}
                {line.before !== undefined && (
                  <>
                    <del className={`${styles.before} ${mono}`}>{line.before}</del>
                    {' → '}
                  </>
                )}
                <span className={`${styles.after} ${mono}`}>{line.after}</span>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

/** `aporte`: the row of the "Por aporte" view whose history to show. */
export default function AportesHistorial({ aporte, onClose }) {
  const [state, setState] = useState({ events: null, error: null, loading: true });
  useEffect(() => {
    let active = true;
    api
      .get(`/ml-ads/contributions/${aporte.id}/history`)
      .then(({ data }) => active && setState({ events: data?.events ?? [], error: null, loading: false }))
      .catch(
        (err) =>
          active &&
          setState({ events: null, error: apiErrorMessage(err, 'No se pudo cargar el historial'), loading: false }),
      );
    return () => {
      active = false;
    };
  }, [aporte.id]);

  const scope = scopeOf(aporte);
  const subtitle = [aporte.brand || 'Sin marca', scope.name, aporte.campaign_id].filter((part) => part != null).join(' · ');

  return (
    <ModalTesla
      isOpen
      onClose={onClose}
      title="Historial del aporte"
      subtitle={subtitle}
      size="md"
      footer={
        <div className={styles.footer}>
          <button type="button" className={styles.btnSecondary} onClick={onClose}>
            Cerrar
          </button>
        </div>
      }
    >
      {state.error && (
        <p className={styles.error} role="alert">
          {state.error}
        </p>
      )}
      {state.loading && <p className={styles.muted}>Cargando historial...</p>}
      {state.events?.length === 0 && (
        <p className={styles.muted}>
          Este aporte no tiene cambios registrados: se cargó antes de que se guardara el historial.
        </p>
      )}
      {state.events?.length > 0 && (
        <ul className={styles.events} aria-label="Eventos del aporte">
          {state.events.map((event, index) => (
            <Event key={`${event.action}-${event.at}-${index}`} event={event} />
          ))}
        </ul>
      )}
      <p className={styles.note}>
        <Info size={14} aria-hidden="true" />
        Si el aporte se borra, el historial lo muestra con quién lo borró y cuándo.
      </p>
    </ModalTesla>
  );
}
