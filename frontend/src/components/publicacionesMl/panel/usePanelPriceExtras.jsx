import { useMemo } from 'react';
import CalculatePriceButton from '../CalculatePriceButton';
import TnPriceLine from '../TnPriceLine';
import useListPrices from '../useListPrices';

/**
 * What a panel's Precios tab takes from Productos' listing of its product (S2), now that the list's own price group
 * is gone: Calcular, which opens Productos' pricing modal on the listing's product (its cost and stock), for the
 * reference line; and the Tienda Nube price with its transfer price, for the web transfer row. Neither repeats a
 * price of the tab. Both are null while the listing is on its way, failed or the product has no such thing.
 *
 * @param {number|null} productItemId
 * @param {object|null} priceGroup The page's `priceGroup`: `onCalculate`, `tnCardPercent`, `version`.
 */
export default function usePanelPriceExtras(productItemId, priceGroup) {
  const ids = useMemo(() => [productItemId], [productItemId]);
  const prices = useListPrices(ids, productItemId != null, priceGroup?.version ?? 0);
  // A failed read leaves no product (`useListPrices` drops them), so neither extra shows.
  const product = prices.byId.get(productItemId) ?? null;
  const onCalculate = priceGroup?.onCalculate ?? null;
  if (!product) return { calculate: null, tnPrice: null };
  return {
    calculate: onCalculate ? <CalculatePriceButton product={product} onCalculate={onCalculate} /> : null,
    tnPrice: <TnPriceLine product={product} percent={priceGroup?.tnCardPercent ?? null} label="Tienda Nube" />,
  };
}
