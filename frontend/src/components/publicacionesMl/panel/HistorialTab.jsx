import { useState } from 'react';
import { publicacionesMlAPI } from '../../../services/api';
import { date } from './format';
import { FeedStatus, LoadMore } from './FeedParts';
import { describeFeedError, formatFeedValue } from './feedFormat';
import { usePagedFeed } from './usePagedFeed';
import { Section } from './PanelParts';
import cellStyles from '../cells.module.css';
import styles from './panel.module.css';

const ERRORS = { forbidden: 'No tenés permiso para ver el historial.', fallback: 'No se pudo cargar el historial.' };
const fetchHistory = (itemId, params) => publicacionesMlAPI.history(itemId, params);

/** The resources the change log keeps (`ml_change_log.resource_type`). An unknown one gets a generic label, never its code. */
const RESOURCE_LABELS = {
  item: 'Publicación',
  prices: 'Precios',
  sale_price: 'Precio de venta',
  promotions: 'Promociones',
  stock: 'Stock',
  product_link: 'Producto vinculado',
  competition: 'Competencia de catálogo',
  user_product: 'Producto de usuario',
  replenishment: 'Reposición',
  family: 'Familia',
};

const GENERIC_RESOURCE_LABEL = 'Otro recurso';

/** Entries that are not a plain change say so. */
const KIND_LABELS = { gone: 'Eliminada de Mercado Libre', restored: 'Restaurada en Mercado Libre' };

/** Business lines whose values are money. */
const MONEY_KEYS = new Set(['price', 'base_price', 'original_price', 'price_channel', 'sale_price', 'regular_price', 'promotion_price', 'price_to_win']);

function Line({ line }) {
  const money = MONEY_KEYS.has(line.label_key);
  // A business line reads as its Spanish label; a technical one is the raw field path.
  return (
    <div className={styles.line} data-line="">
      {line.label ? <span className={styles.lineLabel}>{line.label}</span> : <code className={cellStyles.code}>{line.path}</code>}
      <span className={styles.change}>
        <span>{formatFeedValue(line.old, { money })}</span>
        <span aria-hidden="true">→</span>
        <span>{formatFeedValue(line.new, { money })}</span>
      </span>
    </div>
  );
}

function Entry({ entry, showAll }) {
  const lines = showAll ? [...entry.business, ...entry.technical] : entry.business;
  return (
    <li className={styles.entry}>
      <div className={styles.entryHead}>
        <span className={styles.entryTitle}>{RESOURCE_LABELS[entry.resource_type] ?? GENERIC_RESOURCE_LABEL}</span>
        <time className={styles.entryWhen} dateTime={entry.observed_at}>
          {date(entry.observed_at)}
        </time>
      </div>
      {KIND_LABELS[entry.kind] && <span className={styles.note}>{KIND_LABELS[entry.kind]}</span>}
      {lines.map((line) => (
        <Line key={line.path} line={line} />
      ))}
    </li>
  );
}

/** An entry is worth showing at first sight if a person would look at it. */
const hasBusiness = (entry) => entry.business.length > 0 || entry.kind !== 'change';

/**
 * Historial: what changed in the publication, from `ml_change_log`, newest
 * first. Each entry lists one line per changed field with the previous and the
 * new value. Business fields (price, status, stock, title, promotions, the
 * product link) come first; the technical ones, and the entries made only of
 * them, wait behind "Ver todo".
 */
export default function HistorialTab({ itemId }) {
  const feed = usePagedFeed(fetchHistory, itemId, 'entries');
  // "Ver todo" belongs to one publication: it is off for any other, whatever remounts around the tab.
  const [expanded, setExpanded] = useState({ itemId, on: false });
  const showAll = expanded.itemId === itemId && expanded.on;
  if (feed.status !== 'ready') {
    return <FeedStatus feed={feed} loadingText="Cargando historial…" errorText={(error) => describeFeedError(error, ERRORS)} />;
  }
  if (feed.items.length === 0) return <p className={styles.note}>No hay cambios registrados para esta publicación.</p>;

  const visible = showAll ? feed.items : feed.items.filter(hasBusiness);
  return (
    <Section title="Historial">
      <div>
        <button type="button" className="btn-tesla outline sm" aria-pressed={showAll} onClick={() => setExpanded({ itemId, on: !showAll })}>
          Ver todo
        </button>
      </div>
      {visible.length === 0 && <p className={styles.note}>Solo cambios técnicos en esta página. Usá «Ver todo» para verlos.</p>}
      <ul className={styles.entries}>
        {visible.map((entry) => (
          <Entry key={entry.id} entry={entry} showAll={showAll} />
        ))}
      </ul>
      <LoadMore feed={feed} failedText="No se pudieron cargar más cambios." />
    </Section>
  );
}
