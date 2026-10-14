import { BadgePercent, Store } from 'lucide-react';
import { buildMlSellerListingUrl, buildMlSellerPromosUrl } from '../../utils/mlSellerPanel';
import styles from './MlSellerLinks.module.css';

const LINKS = [
  { label: 'Ver en el panel de ML', build: buildMlSellerListingUrl, Icon: Store },
  { label: 'Ver promociones en ML', build: buildMlSellerPromosUrl, Icon: BadgePercent },
];

// Inside a clickable table row, following a link must not also select the row.
const stopPropagation = (event) => event.stopPropagation();

/**
 * Icon links to the publication in the Mercado Libre seller panel: its
 * listing and its promotions, each in a new tab. Nothing without a usable id.
 */
export default function MlSellerLinks({ itemId }) {
  return LINKS.map((link) => {
    const { label, Icon } = link;
    const href = link.build(itemId);
    if (!href) return null;
    return (
      <a
        key={label}
        className={styles.link}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={label}
        title={label}
        onClick={stopPropagation}
      >
        <Icon size={12} aria-hidden="true" />
      </a>
    );
  });
}
