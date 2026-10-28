import { useRef } from 'react';
import { usePermisos } from '../../../contexts/PermisosContext';
import PxqPanel from '../../promociones/PxqPanel';
import PublicationDisclosures from './PublicationDisclosures';

const VIEW_PERMISSION = 'pxq.ver';

/**
 * The wholesale prices (PxQ tiers) of a product's publications, as Productos' publication tree shows them: one
 * entry per publication, closed until opened, which mounts the same `PxqPanel` (the tiers live on MercadoLibre beside
 * ours, the markup of each tier, and with `pxq.escribir` creating, editing and deleting tiers). What a publication
 * read is kept while the panel shows this product, so reopening reads nothing.
 *
 * Only with `pxq.ver`, the permission `PxqPanel` reads with. Self-contained so the panel can place it anywhere; mount
 * it with the product row's key (`key={productKey}`) so another product starts closed and reads afresh.
 *
 * @param {object} props
 * @param {Array<{item_id: string, title?: string}>} props.publications The product's publications the panel lists.
 */
export default function ProductPxq({ publications }) {
  const { tienePermiso } = usePermisos();
  const tiersRef = useRef(new Map());
  if (!tienePermiso(VIEW_PERMISSION)) return null;

  return (
    <PublicationDisclosures
      title="Precios mayoristas"
      publications={publications}
      renderOpen={(itemId) => <PxqPanel itemId={itemId} pxqCacheRef={tiersRef} />}
    />
  );
}
