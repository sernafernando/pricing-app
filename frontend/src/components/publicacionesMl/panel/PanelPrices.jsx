import ProductPrices from '../../pricing/ProductPrices';
import usePanelPriceExtras from './usePanelPriceExtras';

/**
 * A panel's prices (S2): the product's one price table (`ProductPrices`) with what only the list has -- Calcular at the
 * end of the reference line and the Tienda Nube price by the web transfer (`usePanelPriceExtras`). Mounted only while
 * the Precios tab is open, so the listing is asked only then. Both extras ride in the table's loaded view: while the
 * product's prices fail to load the tab shows that error alone, with nothing to calculate on.
 */
export default function PanelPrices({ productItemId, priceGroup = null, ...props }) {
  const extras = usePanelPriceExtras(productItemId, priceGroup);
  return <ProductPrices productItemId={productItemId} referenceAction={extras.calculate} webTransferNote={extras.tnPrice} {...props} />;
}
