import { useRef, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { usePermisos } from '../../../contexts/PermisosContext';
import CatalogCompetitionPanel from '../../promociones/CatalogCompetitionPanel';
import { Section } from './PanelParts';
import styles from './panel.module.css';

const VIEW_PERMISSION = 'promos.ver';

/**
 * The catalog competition of a product's catalog publications, as Productos' publication tree shows it: one entry
 * per publication with `catalog_listing`, closed until opened, which mounts the same `CatalogCompetitionPanel`
 * (the stored snapshot from `GET /promociones/catalogo-competencia/{mla}`, the cheaper competitors in our format
 * and our markup if we matched them; refreshing one needs `promos.escribir`). A snapshot read once is kept while
 * the panel shows this product, so reopening reads nothing.
 *
 * Only with `promos.ver`, the permission that endpoint requires; nothing shows when no publication is in a catalog.
 * Self-contained so the panel can place it anywhere; mount it with `key={productItemId}`.
 *
 * @param {object} props
 * @param {Array<{item_id: string, title?: string, catalog_listing?: boolean}>} props.publications The product's
 *   publications the panel lists.
 */
export default function ProductCatalogCompetition({ publications }) {
  const { tienePermiso } = usePermisos();
  const snapshotsRef = useRef(new Map());
  const [open, setOpen] = useState(() => new Set());

  const catalog = publications.filter((publication) => publication.catalog_listing);
  if (!tienePermiso(VIEW_PERMISSION) || catalog.length === 0) return null;

  const toggle = (itemId) =>
    setOpen((previous) => {
      const next = new Set(previous);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });

  return (
    <Section title="Competencia de catálogo">
      <ul className={styles.entries}>
        {catalog.map((publication) => {
          const isOpen = open.has(publication.item_id);
          const Chevron = isOpen ? ChevronDown : ChevronRight;
          return (
            <li key={publication.item_id} className={styles.entry}>
              <button
                type="button"
                className={`btn-tesla ghost sm ${styles.disclosure}`}
                onClick={() => toggle(publication.item_id)}
                aria-expanded={isOpen}
                aria-label={`Competencia de catálogo de ${publication.item_id}`}
              >
                <Chevron size={14} aria-hidden="true" />
                <span className={styles.itemId}>{publication.item_id}</span>
                <span className={styles.entryTitle}>{publication.title ?? 'Sin título'}</span>
              </button>
              {isOpen && <CatalogCompetitionPanel mla={publication.item_id} catalogCompetitionCacheRef={snapshotsRef} />}
            </li>
          );
        })}
      </ul>
    </Section>
  );
}
