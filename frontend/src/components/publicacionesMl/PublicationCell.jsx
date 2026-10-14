import { buildMlSellerListingUrl, buildMlSellerPromosUrl, openMlSellerUrl } from '../../utils/mlSellerPanel';
import MlSellerLinks from './MlSellerLinks';
import styles from './PublicationCell.module.css';

const MLA_SHORTCUTS = 'Alt+clic: ver en el panel de ML · Mayús+clic: ver promociones en ML';

/**
 * Alt+click on the MLA opens the seller panel listing, Shift+click its
 * promotions. Ctrl/Cmd and plain clicks go on to the row as before.
 */
function handleMlaClick(event, itemId) {
  if (event.ctrlKey || event.metaKey) return;
  const build = event.altKey ? buildMlSellerListingUrl : event.shiftKey ? buildMlSellerPromosUrl : null;
  if (!build) return;
  event.preventDefault();
  event.stopPropagation();
  openMlSellerUrl(build(itemId));
}

// Shift+click would otherwise extend the text selection over the row.
const preventShiftSelection = (event) => {
  if (event.shiftKey) event.preventDefault();
};

/**
 * First (pinned) column: thumbnail, title and the facts that identify the
 * publication -- MLA, Full, catalogue, how many variations -- plus links to
 * it in the ML seller panel. The title is the only thing that may be
 * missing; it reads "Sin título", never an empty cell.
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
          {/* Mouse-only shortcut; the links beside it are the keyboard path. */}
          <span
            className={styles.mla}
            title={MLA_SHORTCUTS}
            onClick={(event) => handleMlaClick(event, item.item_id)}
            onMouseDown={preventShiftSelection}
          >
            {item.item_id}
          </span>
          <MlSellerLinks itemId={item.item_id} />
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
