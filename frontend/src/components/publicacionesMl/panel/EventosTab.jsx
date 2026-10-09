import { publicacionesMlAPI } from '../../../services/api';
import { eventLabel } from '../eventLabels';
import { date } from './format';
import { FeedStatus, LoadMore } from './FeedParts';
import { describeFeedError, formatFeedValue } from './feedFormat';
import { usePagedFeed } from './usePagedFeed';
import { Section } from './PanelParts';
import styles from './panel.module.css';

const ERRORS = { forbidden: 'No tenés permiso para ver los eventos.', fallback: 'No se pudieron cargar los eventos.' };
const fetchEvents = (itemId, params) => publicacionesMlAPI.events(itemId, params);

const PRICE_KIND_LABELS = { standard: 'Precio estándar', promotion: 'Precio de promoción', sale: 'Precio de venta' };

/** A price event's values are money; anything else is shown as the store wrote it. */
const isMoney = (event) => event.price_kind != null || event.event_type === 'promotion_price_changed';

function EventLine({ event }) {
  const money = isMoney(event);
  const hasValues = event.old_value != null || event.new_value != null;
  const detail = [PRICE_KIND_LABELS[event.price_kind], event.promotion_type].filter(Boolean).join(' · ');
  return (
    <li className={styles.entry}>
      <div className={styles.entryHead}>
        <span className={styles.entryTitle}>{eventLabel(event.event_type)}</span>
        <time className={styles.entryWhen} dateTime={event.observed_at}>
          {date(event.observed_at)}
        </time>
      </div>
      {detail && <span className={styles.note}>{detail}</span>}
      {hasValues && (
        <span className={styles.change}>
          <span>{formatFeedValue(event.old_value, { money })}</span>
          <span aria-hidden="true">→</span>
          <span>{formatFeedValue(event.new_value, { money })}</span>
        </span>
      )}
    </li>
  );
}

/**
 * Eventos: the publication's real events (`ml_item_events`), newest first, a
 * page at a time. Never a derived fact (a sale, a negative margin). The labels
 * are `eventLabels.js`'s, whatever the backend sent. With the events flag off
 * the store writes none, and the tab says so rather than look empty.
 */
export default function EventosTab({ itemId }) {
  const feed = usePagedFeed(fetchEvents, itemId, 'events');
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
  return (
    <Section title="Eventos">
      <ul className={styles.entries}>
        {feed.items.map((event) => (
          <EventLine key={event.id} event={event} />
        ))}
      </ul>
      <LoadMore feed={feed} failedText="No se pudieron cargar más eventos." />
    </Section>
  );
}
