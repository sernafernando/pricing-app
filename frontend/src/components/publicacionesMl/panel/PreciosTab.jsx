import { usePermisos } from '../../../contexts/PermisosContext';
import ProductPrices from '../../pricing/ProductPrices';
import { pricePermissions } from '../../pricing/productPricePermissions';
import ListPriceGroup from './ListPriceGroup';

/**
 * Precios: the prices of the product the publication is linked to (the
 * item-level one). The tab only picks the product and the user's write
 * permissions; a write refreshes the panel and the list (`onWritten`). The
 * product cost is shown with the same gate as the Producto tab
 * (`canSeeMargin`, ml_metricas.ver_ganancia).
 *
 * On top, the Precios view's own price group (`ListPriceGroup`, the list's cells and handlers from `priceGroup`), so
 * the tab shows and edits what the list does; `ProductPrices` below keeps the cost, the markup editor and the rest.
 */
export default function PreciosTab({ detail, canSeeMargin, onWritten, priceGroup = null }) {
  const { tienePermiso } = usePermisos();
  const productItemId = detail.product.item_id;
  return (
    <>
      <ListPriceGroup productItemId={productItemId} canSeeMargin={Boolean(canSeeMargin)} group={priceGroup} />
      <ProductPrices
        productItemId={productItemId}
        permissions={pricePermissions(tienePermiso)}
        onWritten={onWritten}
        showCost={Boolean(canSeeMargin)}
        readAgain={priceGroup?.version ?? 0}
      />
    </>
  );
}
