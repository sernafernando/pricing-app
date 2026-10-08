import styles from './PublicationCell.module.css';

/**
 * First (pinned) column: thumbnail, title and the facts that identify the
 * publication -- MLA, Full, catalogue, how many variations. The title is the
 * only thing that may be missing; it reads "Sin título", never an empty cell.
 */
export default function PublicationCell({ item }) {
  const tags = [
    item.is_full && 'Full',
    item.catalog_listing && 'Catálogo',
    item.variations_count > 0 && `${item.variations_count} variaciones`,
  ].filter(Boolean);
  return (
    <div className={styles.cell}>
      <div className={styles.thumbnail} aria-hidden="true">
        {item.thumbnail && <img src={item.thumbnail} alt="" loading="lazy" className={styles.image} />}
      </div>
      <div className={styles.info}>
        <span className={`${styles.title} ${item.title ? '' : styles.titleEmpty}`} title={item.title ?? undefined}>
          {item.title ?? 'Sin título'}
        </span>
        <span className={styles.meta}>
          <span className={styles.mla}>{item.item_id}</span>
          {tags.map((tag) => (
            <span key={tag} className={styles.tag}>
              {tag}
            </span>
          ))}
        </span>
      </div>
    </div>
  );
}
