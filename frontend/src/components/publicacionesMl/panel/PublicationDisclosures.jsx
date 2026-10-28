import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Section } from './PanelParts';
import styles from './panel.module.css';

/**
 * A section of the product panel with one row per publication, each closed until opened, which shows what
 * `renderOpen(itemId)` draws under it; several may be open at once. Nothing shows without publications.
 *
 * Productos opens these per publication in its publication tree (catalog competition, wholesale prices); the product
 * panel lists them the same way so each publication reads only when asked.
 *
 * @param {object} props
 * @param {string} props.title The section's heading, also the start of each row's accessible name ("<title> de MLA…").
 * @param {Array<{item_id: string, title?: string}>} props.publications
 * @param {(itemId: string) => import('react').ReactNode} props.renderOpen
 */
export default function PublicationDisclosures({ title, publications, renderOpen }) {
  const [open, setOpen] = useState(() => new Set());
  if (publications.length === 0) return null;

  const toggle = (itemId) =>
    setOpen((previous) => {
      const next = new Set(previous);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });

  return (
    <Section title={title}>
      <ul className={styles.entries}>
        {publications.map((publication) => {
          const isOpen = open.has(publication.item_id);
          const Chevron = isOpen ? ChevronDown : ChevronRight;
          return (
            <li key={publication.item_id} className={styles.entry}>
              <button
                type="button"
                className={`btn-tesla ghost sm ${styles.disclosure}`}
                onClick={() => toggle(publication.item_id)}
                aria-expanded={isOpen}
                aria-label={`${title} de ${publication.item_id}`}
              >
                <Chevron size={14} aria-hidden="true" />
                <span className={styles.itemId}>{publication.item_id}</span>
                <span className={styles.entryTitle}>{publication.title ?? 'Sin título'}</span>
              </button>
              {isOpen && renderOpen(publication.item_id)}
            </li>
          );
        })}
      </ul>
    </Section>
  );
}
