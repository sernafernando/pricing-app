/**
 * usePublishPricing — the two-base publish-price derivation (Slice 2, money
 * path) extracted from `TnPublishModal.jsx` verbatim (PR-9 file-size split,
 * zero behavior change) so the modal's own file stays under the ~200-line
 * component ceiling. See `VariantFieldsSection` for the two-base rule.
 */
import { useMemo } from 'react';
import { useMarkupOffset } from './useMarkupOffset';

export function usePublishPricing({ isOpen, row, manualPrice }) {
  const hasWebPrice =
    row?.precio_web_transferencia != null &&
    row?.precio_web_transferencia !== '' &&
    row?.participa_web_transferencia === true;

  const { offsetPercent, setOffsetPercent, loadingOffset, offsetError } = useMarkupOffset({ isOpen, hasWebPrice });

  const basePrice = hasWebPrice ? Number(row.precio_web_transferencia) : null;
  const computedPrice = useMemo(() => {
    if (!hasWebPrice || basePrice == null || Number.isNaN(basePrice)) return null;
    // `null` (config not loaded / failed) and `''` (operator cleared the box)
    // are checked BEFORE Number(): both coerce to 0, which would quietly
    // publish at the bare base price instead of blocking.
    if (offsetPercent === null || offsetPercent === '') return null;
    const offset = Number(offsetPercent);
    if (Number.isNaN(offset)) return null;
    return (basePrice * (1 + offset / 100)).toFixed(2);
  }, [hasWebPrice, basePrice, offsetPercent]);

  const finalPrice = hasWebPrice
    ? computedPrice
    : manualPrice !== '' && !Number.isNaN(Number(manualPrice))
      ? Number(manualPrice).toFixed(2)
      : null;
  const finalPriceIsValid = finalPrice != null && Number(finalPrice) > 0;
  const priceBaseSource = hasWebPrice ? 'web_transferencia' : 'manual';

  return {
    hasWebPrice,
    basePrice,
    offsetPercent,
    setOffsetPercent,
    loadingOffset,
    offsetError,
    computedPrice,
    finalPrice,
    finalPriceIsValid,
    priceBaseSource,
  };
}
