export const nounOf = (groupBy) => ({ publication: 'Publicaciones', group: 'Grupos' }[groupBy] ?? 'Productos');
// The card shows while some sold line has a sell in or a sell out (the backend's `SellInOut.applies`: `sell_in`
// and `sell_out` are null otherwise). `costo` never decides it: it is the cost WITHOUT sell in, there for any
// sale; the cost with sell in only exists with a sell in. The "C/ sell in/out" lines follow the same rule
// through `total_gauss`, which the backend leaves null when neither applies.
const hasSellCard = (sell) => Boolean(sell && (sell.sell_in != null || sell.sell_out != null));

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
    sell && { id: 'sell_in_out', label: 'Sell in / Sell out' },
    { id: 'rows_with_sales', label: `${nounOf(groupBy)} con ventas` },
    { id: 'ageing', label: 'Ageing promedio' },
    canSeeMargin && kpis?.ads && { id: 'ads', label: 'Publicidad (ML Ads)' },
  ].filter(Boolean);
}
