export const nounOf = (groupBy) => ({ publication: 'Publicaciones', group: 'Grupos' }[groupBy] ?? 'Productos');
// The card shows while some sold line has a sell out (the backend's `ConSo.applies`: `sell_out` is null otherwise).
// `costo` never decides it: it is the frozen cost (costo SI, Costo SI T3 D1), there for any sale. The "C/ SO" lines
// follow the same rule through `total_gauss`, which the backend leaves null when no sell out applies.
const hasSellCard = (sell) => Boolean(sell && sell.sell_out != null);

/**
 * The KPIs this viewer sees on the board right now, in the strip's order, for the "Indicadores" picker:
 * the strip's cards plus the ads block (`ads`, drawn by `AdsKpiBlock` while the ads are on).
 */
export function metricasKpiOptions(kpis, { canSeeMargin, groupBy, tpSolo = false }) {
  const tp = canSeeMargin && kpis?.total_tp != null;
  const sell = hasSellCard(canSeeMargin ? kpis?.sell_in_out : null);
  return [
    { id: 'units', label: 'Unidades vendidas' },
    { id: 'gross', label: 'Facturado bruto' },
    !tpSolo && { id: 'total_gauss', label: 'Total Gauss' },
    tp && { id: 'total_tp', label: 'Total TP' },
    { id: 'markup', label: tpSolo ? 'Markup TP' : 'Markup promedio' },
    sell && { id: 'sell_in_out', label: 'Sell out' },
    { id: 'rows_with_sales', label: `${nounOf(groupBy)} con ventas` },
    { id: 'ageing', label: 'Ageing promedio' },
    canSeeMargin && kpis?.ads && { id: 'ads', label: 'Publicidad (ML Ads)' },
  ].filter(Boolean);
}
