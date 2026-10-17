import { useState } from 'react';
import { publicacionesMlAPI } from '../../../services/api';
import { date } from './format';
import { Change, FeedStatus, LoadMore, Tag } from './FeedParts';
import { describeFeedError } from './feedFormat';
import { originTag, stateTone } from './eventSentence';
import { usePagedFeed } from './usePagedFeed';
import styles from './panel.module.css';

const ERRORS = { forbidden: 'No tenés permiso para ver el historial.', fallback: 'No se pudo cargar el historial.' };
const fetchHistory = (itemId, params) => publicacionesMlAPI.history(itemId, params);
const TECHNICAL = { tecnicos: true };

/** The resources the change log keeps (`ml_change_log.resource_type`). An unknown one gets a generic label, never its code. */
const RESOURCE_LABELS = {
  item: 'Publicación y stock',
  prices: 'Precios',
  sale_price: 'Precio de venta',
  promotions: 'Promociones',
  stock: 'Stock por depósito',
  visits: 'Visitas',
  product_link: 'Producto vinculado',
  competition: 'Competencia de catálogo',
  user_product: 'Producto de usuario',
  replenishment: 'Ventas semanales (Full)',
  family: 'Familia',
};

const GENERIC_RESOURCE_LABEL = 'Otro recurso';

/** Entries that are not a plain change say so. */
const KIND_LABELS = { gone: 'Eliminada de Mercado Libre', restored: 'Restaurada en Mercado Libre' };

function Line({ row }) {
  return (
    <div className={styles.line} data-line="">
      <span className={styles.lineLabel}>{row.label}</span>
      {row.status_label ? (
        <span className={styles.change}>
          <Tag tone={stateTone(row.status_label)}>{row.status_label}</Tag>
        </span>
      ) : (
        <Change before={row.before} after={row.after} />
      )}
    </div>
  );
}

/** Consecutive rows about the same thing (one promotion, one day) go under its name, once. */
function bySubject(rows) {
  const groups = [];
  for (const row of rows) {
    if (groups.length === 0 || groups.at(-1).subject !== row.subject) groups.push({ subject: row.subject, rows: [] });
    groups.at(-1).rows.push(row);
  }
  return groups;
}

function Entry({ entry }) {
  const origin = originTag(entry.origin, entry.informational);
  return (
    <li className={styles.entry} data-entry={entry.id}>
      <div className={styles.entryHead}>
        <span className={styles.entryTitle}>{RESOURCE_LABELS[entry.resource_type] ?? GENERIC_RESOURCE_LABEL}</span>
        <time className={styles.entryWhen} dateTime={entry.observed_at}>
          {date(entry.observed_at)}
        </time>
      </div>
      {KIND_LABELS[entry.kind] && <span className={styles.note}>{KIND_LABELS[entry.kind]}</span>}
      {bySubject(entry.rows).map((group, index) => (
        <div key={index} className={styles.lines}>
          {group.subject && <span className={styles.subject}>{group.subject}</span>}
          {group.rows.map((row, rowIndex) => (
            <Line key={`${row.path}-${row.label}-${rowIndex}`} row={row} />
          ))}
        </div>
      ))}
      {origin && (
        <div className={styles.tags}>
          <Tag tone={origin.tone}>{origin.text}</Tag>
        </div>
      )}
    </li>
  );
}

/** An entry is worth a card when it has a line to read, or it says the publication went or came back. */
const hasRows = (entry) => entry.rows.length > 0 || entry.kind !== 'change';

const hiddenNote = (count) =>
  count === 1
    ? 'Oculto 1 cambio técnico (fechas de actualización, identificadores o períodos de medición).'
    : `Ocultos ${count} cambios técnicos (fechas de actualización, identificadores y períodos de medición).`;

/**
 * Historial: what changed in the publication, from `ml_change_log`, newest
 * first: one card per change, named by its resource, each line a Spanish label
 * with the value before and after as the backend formatted them (`rows`).
 * Technical lines are left out by the backend and counted in the footer until
 * "Mostrar datos técnicos" asks for them (`tecnicos=true`).
 */
export default function HistorialTab({ itemId }) {
  // The toggle belongs to one publication: it is off for any other, whatever remounts around the tab.
  const [technical, setTechnical] = useState({ itemId, on: false });
  const showTechnical = technical.itemId === itemId && technical.on;
  const feed = usePagedFeed(fetchHistory, itemId, 'entries', showTechnical ? TECHNICAL : undefined);

  const toggle = (
    <div className={styles.chips}>
      <button
        type="button"
        className={styles.chip}
        aria-pressed={showTechnical}
        onClick={() => setTechnical({ itemId, on: !showTechnical })}
      >
        Mostrar datos técnicos
      </button>
    </div>
  );
  if (feed.status !== 'ready') {
    return (
      <div className={styles.feed}>
        {toggle}
        <FeedStatus feed={feed} loadingText="Cargando historial…" errorText={(error) => describeFeedError(error, ERRORS)} />
      </div>
    );
  }
  if (feed.items.length === 0) return <p className={styles.note}>No hay cambios registrados para esta publicación.</p>;

  const visible = feed.items.filter(hasRows);
  const hidden = feed.items.reduce((total, entry) => total + (entry.hidden_technical_count ?? 0), 0);
  return (
    <div className={styles.feed}>
      {toggle}
      {visible.length === 0 && <p className={styles.note}>En esta página solo hay cambios técnicos.</p>}
      {visible.length > 0 && (
        <ul className={styles.entries}>
          {visible.map((entry) => (
            <Entry key={entry.id} entry={entry} />
          ))}
        </ul>
      )}
      <LoadMore feed={feed} failedText="No se pudieron cargar más cambios." />
      {!showTechnical && hidden > 0 && <p className={styles.footnote}>{hiddenNote(hidden)}</p>}
    </div>
  );
}
