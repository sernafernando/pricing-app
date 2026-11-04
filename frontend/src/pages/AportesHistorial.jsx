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

const valueLabel = (snap) => (snap.kind === 'percentage' ? 'Porcentaje' : 'Monto');
const valueText = (snap) =>
  snap.kind === 'percentage'
    ? `${Number(snap.value).toLocaleString('es-AR', { maximumFractionDigits: 2 })} %`
    : formatSignedMoney(Number(snap.value));
const rangeText = (snap) => `${dayMonth(snap.date_from)} → ${dayMonth(snap.date_to)}`;

/** The fields of a snapshot an edit can change, in the form's order: label and text of each. */
const FIELDS = [
  ['Marca', (s) => s.brand || 'Sin marca'],
  ['Campaña', (s) => (s.campaign_id == null ? 'Toda la cuenta Display' : String(s.campaign_id))],
  ['Tipo', (s) => KINDS[s.kind] || s.kind],
  [valueLabel, valueText],
  ['Cómo se liquida', (s) => SETTLEMENTS[s.settlement] || 'Sin liquidación'],
  ['Rango', rangeText],
  ['Nota', (s) => s.note || 'Sin nota'],
];

/** What a load shows, as the design: type, value, settlement (fixed amounts only) and range. */
function loadedLines(snap) {
  const lines = [
    { label: 'Tipo', after: KINDS[snap.kind] || snap.kind },
    { label: valueLabel(snap), after: valueText(snap) },
  ];
  if (snap.settlement) lines.push({ label: 'Cómo se liquida', after: SETTLEMENTS[snap.settlement] });
  lines.push({ label: 'Rango', after: rangeText(snap) });
  return lines;
}

/** What an edit changed, field by field. */
function changedLines(before, after) {
  return FIELDS.map(([label, text]) => ({
    label: typeof label === 'function' ? label(after) : label,
    before: text(before),
    after: text(after),
  })).filter((line) => line.before !== line.after);
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
            // Only figures go monospace, as the design: "$ 120.000,00", "30 %".
            const mono = line.label === 'Monto' || line.label === 'Porcentaje' ? styles.mono : '';
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
  const [state, setState] = useState({ events: null, error: null });
  useEffect(() => {
    let active = true;
    api
      .get(`/ml-ads/contributions/${aporte.id}/history`)
      .then(({ data }) => active && setState({ events: data.events, error: null }))
      .catch((err) => active && setState({ events: null, error: apiErrorMessage(err, 'No se pudo cargar el historial') }));
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
      {state.events && (
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
