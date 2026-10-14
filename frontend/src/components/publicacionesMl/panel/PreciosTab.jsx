import { usePermisos } from '../../../contexts/PermisosContext';
import ProductPrices from '../../pricing/ProductPrices';
import { pricePermissions } from '../../pricing/productPricePermissions';

/**
 * Precios: the prices of the product the publication is linked to (the
 * item-level one). The tab only picks the product and the user's write
 * permissions; a write refreshes the panel and the list (`onWritten`). The
 * product cost is shown with the same gate as the Producto tab
 * (`canSeeMargin`, ml_metricas.ver_ganancia).
 */
export default function PreciosTab({ detail, canSeeMargin, onWritten }) {
  const { tienePermiso } = usePermisos();
  return <ProductPrices productItemId={detail.product.item_id} permissions={pricePermissions(tienePermiso)} onWritten={onWritten} showCost={Boolean(canSeeMargin)} />;
}
