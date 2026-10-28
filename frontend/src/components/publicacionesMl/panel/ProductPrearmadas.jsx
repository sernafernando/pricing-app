import { useMemo } from 'react';
import PrearmadaBadge from '../../PrearmadaBadge';
import { usePrearmadasStats } from '../../../hooks/usePrearmadasStats';

/**
 * The prearmadas of a product, the same badge Productos shows beside each product (`PrearmadaBadge`): how many are
 * ready, or else how many are available as an upgrade; nothing when there are none. Read with the same hook
 * (`usePrearmadasStats`, `POST /prearmados/stats/batch`), which asks nothing without
 * `produccion.ver_prearmadas_stats`.
 *
 * @param {object} props
 * @param {number} props.productItemId The ERP product.
 */
export default function ProductPrearmadas({ productItemId }) {
  const itemIds = useMemo(() => [productItemId], [productItemId]);
  const { statsById } = usePrearmadasStats(itemIds);
  return <PrearmadaBadge stats={statsById[productItemId]} />;
}
