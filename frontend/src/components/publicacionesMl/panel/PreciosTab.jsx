import { usePermisos } from '../../../contexts/PermisosContext';
import { pricePermissions } from '../../pricing/productPricePermissions';
import PanelPrices from './PanelPrices';

/**
 * Precios: the prices of the product the publication is linked to (the
 * item-level one). The tab only picks the product and the user's write
 * permissions; a write refreshes the panel and the list (`onWritten`). The
 * product cost is shown with the same gate as the Producto tab
 * (`canSeeMargin`, ml_metricas.ver_ganancia).
 *
 * One table, a row per plan (S2): every price shows once, edited in place. From the list (`priceGroup`) only what the
 * product's own prices lack: Calcular in the reference line and the Tienda Nube price by the web transfer.
 */
export default function PreciosTab({ detail, canSeeMargin, onWritten, priceGroup = null }) {
  const { tienePermiso } = usePermisos();
  const productItemId = detail.product.item_id;
  return (
    <PanelPrices
      productItemId={productItemId}
      priceGroup={priceGroup}
      permissions={pricePermissions(tienePermiso)}
      onWritten={onWritten}
      showCost={Boolean(canSeeMargin)}
      // A write elsewhere reloads the list (`version`): these prices are read again with it.
      readAgain={priceGroup?.version ?? 0}
    />
  );
}
