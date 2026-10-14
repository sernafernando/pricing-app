import { usePermisos } from '../../../contexts/PermisosContext';
import ProductPrices from '../../pricing/ProductPrices';
import { pricePermissions } from '../../pricing/productPricePermissions';

/**
 * Precios: the prices of the product the publication is linked to (the
 * item-level one). The tab only picks the product and the user's write
 * permissions; a write refreshes the panel and the list (`onWritten`).
 */
export default function PreciosTab({ detail, onWritten }) {
  const { tienePermiso } = usePermisos();
  return <ProductPrices productItemId={detail.product.item_id} permissions={pricePermissions(tienePermiso)} onWritten={onWritten} />;
}
