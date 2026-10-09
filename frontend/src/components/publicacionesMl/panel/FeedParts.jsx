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
