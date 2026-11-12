import { useEffect, useRef, useState } from 'react';
import { BadgePercent, ExternalLink, MoreVertical, Store } from 'lucide-react';
import { buildMlSellerListingUrl, buildMlSellerPromosUrl } from '../../../utils/mlSellerPanel';
import styles from './PhonePanelActions.module.css';

// The seller panel's links, as `MlSellerLinks` builds them on desktop, here with their words.
const SELLER_LINKS = [
  { label: 'Ver en el panel de ML', build: buildMlSellerListingUrl, Icon: Store },
  { label: 'Ver promociones en ML', build: buildMlSellerPromosUrl, Icon: BadgePercent },
];

/**
 * The publication panel's top-right actions on a phone (mobile-metricas-pubml S2, PubDetalle design): "Ver en Mercado
 * Libre" as an icon, and "⋯" with the seller panel's links. The menu closes on a pick, outside or with Escape.
 */
export default function PhonePanelActions({ itemId, mlUrl }) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const outside = (event) => {
      if (!boxRef.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event) => {
      if (event.key !== 'Escape') return;
      // The menu takes this Escape: the panel stays open.
      event.preventDefault();
      setOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    // Capture: before the layout's own Escape (on window), which would close the panel.
    document.addEventListener('keydown', escape, true);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape, true);
    };
  }, [open]);

  const links = SELLER_LINKS.map((link) => ({ ...link, href: link.build(itemId) })).filter((link) => link.href);
  return (
      <div className={styles.actions} ref={boxRef}>
        {mlUrl && (
          <a className={styles.iconButton} href={mlUrl} target="_blank" rel="noopener noreferrer" aria-label="Ver en Mercado Libre">
            <ExternalLink size={18} aria-hidden="true" />
          </a>
        )}
        {links.length > 0 && (
          <button
            type="button"
            className={styles.iconButton}
            aria-label="Más acciones: abrir en el panel del vendedor"
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={() => setOpen((was) => !was)}
          >
            <MoreVertical size={20} aria-hidden="true" />
          </button>
        )}
        {open && (
          <div className={styles.menu} role="menu" aria-label="Panel del vendedor">
            {links.map((link) => {
              const { label, href } = link;
              const LinkIcon = link.Icon;
              return (
              <a
                key={label}
                className={styles.item}
                role="menuitem"
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => setOpen(false)}
              >
                <LinkIcon size={16} aria-hidden="true" />
                {label}
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}
