import ProductPrices from '../../pricing/ProductPrices';

/**
 * Precios: the prices of the product the publication is linked to (the
 * item-level one). The tab only picks the product; `ProductPrices` reads it.
 */
export default function PreciosTab({ detail }) {
  return <ProductPrices productItemId={detail.product.item_id} />;
}
