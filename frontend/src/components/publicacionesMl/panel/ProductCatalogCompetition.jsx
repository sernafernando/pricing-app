import { useRef } from 'react';
import { usePermisos } from '../../../contexts/PermisosContext';
import CatalogCompetitionPanel from '../../promociones/CatalogCompetitionPanel';
import PublicationDisclosures from './PublicationDisclosures';

const VIEW_PERMISSION = 'promos.ver';

/**
 * The catalog competition of a product's catalog publications, as Productos' publication tree shows it: one entry
 * per publication with `catalog_listing`, closed until opened, which mounts the same `CatalogCompetitionPanel`
 * (the stored snapshot from `GET /promociones/catalogo-competencia/{mla}`, the cheaper competitors in our format
 * and our markup if we matched them; refreshing one needs `promos.escribir`). A snapshot read once is kept while
 * the panel shows this product, so reopening reads nothing.
 *
 * Only with `promos.ver`, the permission that endpoint requires; nothing shows when no publication is in a catalog.
 * Self-contained so the panel can place it anywhere; mount it with the product row's key (`key={productKey}`, which
 * "Sin producto" also has) so another product starts closed and reads afresh.
 *
 * @param {object} props
 * @param {Array<{item_id: string, title?: string, catalog_listing?: boolean}>} props.publications The product's
 *   publications the panel lists.
 */
export default function ProductCatalogCompetition({ publications }) {
  const { tienePermiso } = usePermisos();
  const snapshotsRef = useRef(new Map());
  if (!tienePermiso(VIEW_PERMISSION)) return null;

  return (
    <PublicationDisclosures
      title="Competencia de catálogo"
      publications={publications.filter((publication) => publication.catalog_listing)}
      renderOpen={(itemId) => <CatalogCompetitionPanel mla={itemId} catalogCompetitionCacheRef={snapshotsRef} />}
    />
  );
}
