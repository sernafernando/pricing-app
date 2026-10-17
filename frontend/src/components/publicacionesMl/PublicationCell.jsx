import { Barcode, CircleDashed, Link2, Store, TriangleAlert, Unlink } from 'lucide-react';
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

// The link to an ERP product, as a toned icon: the state's name is its accessible name.
const LINK_STATES = {
  auto: { label: 'Automático', tone: 'success', Icon: Link2 },
  manual: { label: 'Manual', tone: 'info', Icon: Link2 },
  sin_producto: { label: 'Sin producto', tone: 'warning', Icon: Unlink },
  conflicto: { label: 'Conflicto', tone: 'danger', Icon: TriangleAlert },
  no_evaluado: { label: 'Sin evaluar', tone: 'neutral', Icon: CircleDashed },
};

function storeName(item) {
  if (item.store_label) return item.store_label;
  return item.official_store_id != null ? `Tienda ${item.official_store_id}` : null;
}

/** The official store, compact: a store icon and its name; nothing when the publication has none. */
function StoreTag({ item }) {
  const name = storeName(item);
  if (!name) return null;
  return (
    <span className={styles.store} aria-label={`Tienda: ${name}`} title={`Tienda: ${name}`}>
      <Store size={11} aria-hidden="true" />
      {name}
    </span>
  );
}

/** The publication's SKU (the key of the automatic link), compact: nothing when ML carries none. */
function SkuTag({ sku }) {
  if (!sku) return null;
  const label = `SKU del vendedor: ${sku}`;
  return (
    <span className={styles.sku} aria-label={label} title={label}>
      <Barcode size={11} aria-hidden="true" />
      <span className={styles.code}>{sku}</span>
    </span>
  );
}

/** The link state, compact: a toned icon, plus the product code when linked (the description in the tooltip). */
function LinkTag({ link }) {
  const known = LINK_STATES[link?.state];
  if (!known) return null;
  const { label, tone, Icon } = known;
  const product = [link.codigo, link.descripcion].filter(Boolean).join(' ');
  return (
    <span
      className={styles.link}
      data-tone={tone}
      aria-label={`Vínculo: ${label}`}
      title={product ? `Vínculo: ${label} · ${product}` : `Vínculo: ${label}`}
    >
      <Icon size={12} aria-hidden="true" />
      {link.codigo && <span className={styles.code}>{link.codigo}</span>}
    </span>
  );
}

/**
 * First (pinned) column: thumbnail, title and the facts that identify the
 * publication -- MLA, Full, catalogue, how many variations -- plus links to
 * it in the ML seller panel, its official store and its link to an ERP
 * product (compact: they were columns of their own). The title is the only
 * thing that may be missing; it reads "Sin título", never an empty cell.
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
          <SkuTag sku={item.seller_sku} />
          <LinkTag link={item.link} />
          <StoreTag item={item} />
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
