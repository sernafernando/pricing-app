import { EMPTY_VALUE } from './feedFormat';
import styles from './panel.module.css';

/** The loading note, the error with its retry, or nothing once the feed is ready. */
export function FeedStatus({ feed, loadingText, errorText }) {
  if (feed.status === 'loading') {
    return (
      <p className={styles.note} role="status">
        {loadingText}
      </p>
    );
  }
  if (feed.status === 'error') {
    return (
      <div className={styles.error} role="alert">
        <span>{errorText(feed.error)}</span>
        <button type="button" className="btn-tesla outline sm" onClick={feed.reload}>
          Reintentar
        </button>
      </div>
    );
  }
  return null;
}

/** "Ver más" while there is a next page; a failed page keeps the list and says so. */
export function LoadMore({ feed, failedText }) {
  if (feed.nextCursor == null) return null;
  return (
    <div className={styles.more}>
      {feed.more === 'error' && (
        <p className={styles.note} role="alert">
          {failedText}
        </p>
      )}
      <button type="button" className="btn-tesla outline sm" disabled={feed.more === 'loading'} onClick={feed.loadMore}>
        {feed.more === 'loading' ? 'Cargando…' : 'Ver más'}
      </button>
    </div>
  );
}

const TAG_TONES = {
  ours: styles.tagOurs,
  auto: styles.tagAuto,
  warning: styles.tagWarning,
  success: styles.tagSuccess,
  info: styles.tagInfo,
  neutral: styles.tagNeutral,
};

/** A small label: who caused a change (`originTag`) or a promotion's state (`stateTone`). */
export function Tag({ tone = 'neutral', children }) {
  return <span className={`${styles.tag} ${TAG_TONES[tone] ?? styles.tagNeutral}`}>{children}</span>;
}

/** A before → after pair; a side that does not exist is left out before the arrow, or is the dash after it. */
export function Change({ before, after, delta }) {
  return (
    <span className={styles.change}>
      {before != null && (
        <>
          <span className={styles.before}>{before}</span>
          <span aria-hidden="true">→</span>
        </>
      )}
      <span className={styles.after}>{after ?? EMPTY_VALUE}</span>
      {delta && <span className={delta.direction === 'up' ? styles.deltaUp : styles.deltaDown}>{delta.text}</span>}
    </span>
  );
}
