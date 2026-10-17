import { useState } from 'react';
import { publicacionesMlAPI } from '../../../services/api';
import { dayHeading, dayKey, timeOfDay } from './format';
import { Change, FeedStatus, LoadMore, Tag } from './FeedParts';
import { describeFeedError } from './feedFormat';
import { describeEvent, originTag, stateTone } from './eventSentence';
import { usePagedFeed } from './usePagedFeed';
import { Section } from './PanelParts';
import styles from './panel.module.css';

const ERRORS = { forbidden: 'No tenés permiso para ver los eventos.', fallback: 'No se pudieron cargar los eventos.' };
const fetchEvents = (itemId, params) => publicacionesMlAPI.events(itemId, params);

/** The chips over the list: what each one keeps of the loaded events. */
const FILTERS = [
  { key: 'todos', label: 'Todos', keep: () => true },
  { key: 'nosotros', label: 'Hechos por nosotros', keep: (event) => event.origin?.kind === 'nosotros' },
  { key: 'ml', label: 'Cambios de ML', keep: (event) => event.origin?.kind === 'ml' },
  { key: 'importantes', label: 'Solo importantes', keep: (event) => !event.informational },
];

function EventLine({ event }) {
  const { title, detail, change } = describeEvent(event);
  const origin = originTag(event.origin, event.informational);
  return (
    <li className={styles.event}>
      <div className={styles.entryHead}>
        <span className={styles.entryTitle}>{title}</span>
        <time className={styles.entryWhen} dateTime={event.observed_at}>
          {timeOfDay(event.observed_at)}
        </time>
      </div>
      {detail && <span className={styles.note}>{detail}</span>}
      {change && (
        <span className={styles.detailLine}>
          {change.label && <span className={styles.note}>{change.label}</span>}
          <Change before={change.before} after={change.after} delta={change.delta} />
        </span>
      )}
      {(origin || event.status_label) && (
        <div className={styles.tags}>
          {origin && <Tag tone={origin.tone}>{origin.text}</Tag>}
          {event.status_label && <Tag tone={stateTone(event.status_label)}>{event.status_label}</Tag>}
        </div>
      )}
    </li>
  );
}

/** Consecutive events of the same local day, in the order received (newest first). */
function byDay(events) {
  const days = [];
  for (const event of events) {
    const key = dayKey(event.observed_at);
    if (days.at(-1)?.key !== key) days.push({ key, at: event.observed_at, events: [] });
    days.at(-1).events.push(event);
  }
  return days;
}

/**
 * Eventos: the publication's real events (`ml_item_events`), newest first, a
 * page at a time, grouped by day. Each one is a sentence (`eventSentence.js`)
 * with who caused it and, for a promotion, its state. The chips narrow the
 * loaded events. With the events flag off the store writes none, and the tab
 * says so rather than look empty.
 */
export default function EventosTab({ itemId }) {
  const feed = usePagedFeed(fetchEvents, itemId, 'events');
  const [filter, setFilter] = useState('todos');
  const status = <FeedStatus feed={feed} loadingText="Cargando eventos…" errorText={(error) => describeFeedError(error, ERRORS)} />;
  if (feed.status !== 'ready') return status;
  if (feed.meta?.enabled === false) {
    return (
      <p className={styles.note} role="status">
        Los eventos están desactivados: la sincronización de publicaciones no los registra.
      </p>
    );
  }
  if (feed.items.length === 0) return <p className={styles.note}>Todavía no hay eventos para esta publicación.</p>;

  const active = FILTERS.find((candidate) => candidate.key === filter) ?? FILTERS[0];
  const shown = feed.items.filter(active.keep);
  const now = new Date();
  return (
    <div className={styles.feed}>
      <div className={styles.chips}>
        {FILTERS.map((candidate) => (
          <button
            key={candidate.key}
            type="button"
            className={styles.chip}
            aria-pressed={candidate.key === active.key}
            onClick={() => setFilter(candidate.key)}
          >
            {candidate.label}
            <span className={styles.chipCount}>{feed.items.filter(candidate.keep).length}</span>
          </button>
        ))}
      </div>
      {shown.length === 0 && <p className={styles.note}>Ningún evento de los cargados coincide con este filtro.</p>}
      {byDay(shown).map((day) => (
        <Section key={day.key} title={dayHeading(day.at, now)}>
          <ul className={styles.events}>
            {day.events.map((event) => (
              <EventLine key={event.id} event={event} />
            ))}
          </ul>
        </Section>
      ))}
      <LoadMore feed={feed} failedText="No se pudieron cargar más eventos." />
    </div>
  );
}
