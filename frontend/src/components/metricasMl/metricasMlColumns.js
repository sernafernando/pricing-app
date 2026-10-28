import { chainHeader } from '../../utils/metricasMlLevels';
import { TP_MARKUP_HINT } from '../../utils/metricasMlTp';

// The picker's dimensions live with the levels, shared with Publicaciones ML.
export { DIMENSION_OPTIONS } from '../../utils/metricasMlLevels';

/**
 * The Métricas ML board's columns (tablero.html): grouped, each leaf
 * hideable from the ColumnPicker except Producto. Margin columns only exist
 * for a user with `ml_metricas.ver_ganancia` (the backend sends them `null`
 * otherwise, and an all-dash column would just be noise).
 */
export const COLUMN_GROUPS = [
  { id: 'producto', label: 'Producto' },
  { id: 'ventas', label: 'Ventas (unidades)' },
  { id: 'markup', label: 'Markup' },
  { id: 'resultado', label: 'Resultado financiero' },
  { id: 'publicidad', label: 'Publicidad' },
  { id: 'rotacion', label: 'Rotación' },
  { id: 'sellin', label: 'Sell-in / Sell-out' },
];

const MARGIN_COLUMNS = new Set([
  'markup',
  'markup_delta',
  'markup_trend',
  'markup_range',
  'total_gauss',
  'total_tp',
  'ads_cost',
  'costo',
  'costo_sell_in',
  'sell_in',
  'sell_out',
  'total_gauss_sell',
  'markup_sell',
]);

function productHeader(groupBy, dimension) {
  if (groupBy === 'publication') return 'Publicación / Producto';
  if (groupBy === 'group') return chainHeader(dimension);
  return 'Detalle / SKU / Marca';
}

/**
 * `tpSolo`: a `tplink.solo` user's board (backend P5b) always carries the TP costs and never a Total Gauss, so
 * Total TP takes its place and the markup is Markup TP.
 */
export function buildBoardColumns({
  canSeeMargin,
  periodLabel,
  groupBy,
  dimension,
  adsOn = false,
  tpOn = false,
  tpSolo = false,
  costosTp = false,
}) {
  const showTp = tpOn || tpSolo;
  const markupHeader = tpSolo ? 'Markup TP' : 'Markup act.';
  const columns = [
    { id: 'producto', group: 'producto', header: productHeader(groupBy, dimension), enableHiding: false },
    // The units sold in the chosen period (the KPI's figure, per row), ahead of the fixed windows.
    { id: 'units', group: 'ventas', header: `Unidades ${periodLabel}` },
    { id: 'units_24h', group: 'ventas', header: '24H' },
    { id: 'units_3d', group: 'ventas', header: '3D' },
    { id: 'units_7d', group: 'ventas', header: '7D' },
    { id: 'units_15d', group: 'ventas', header: '15D' },
    { id: 'units_30d', group: 'ventas', header: '30D' },
    { id: 'units_trend', group: 'ventas', header: 'Tendencia' },
    // "Costos TP": the markup of TP-store operations is Markup TP; the header's tooltip says so.
    { id: 'markup', group: 'markup', header: markupHeader, ...(showTp ? { title: TP_MARKUP_HINT } : {}) },
    { id: 'markup_delta', group: 'markup', header: 'vs anterior' },
    { id: 'markup_trend', group: 'markup', header: 'Tendencia 90D' },
    { id: 'markup_range', group: 'markup', header: 'Mín / Máx 90D' },
    { id: 'gross', group: 'resultado', header: `Facturado ${periodLabel}` },
    ...(tpSolo ? [] : [{ id: 'total_gauss', group: 'resultado', header: 'Total Gauss' }]),
    // "Costos TP" on: Total TP next to Total Gauss, which stays.
    ...(showTp ? [{ id: 'total_tp', group: 'resultado', header: 'Total TP' }] : []),
    // Only once the board subtracts ads: the Product Ads (net of IVA) charged to the row.
    ...(adsOn ? [{ id: 'ads_cost', group: 'publicidad', header: 'Publicidad (inversión)' }] : []),
    { id: 'last_sale', group: 'rotacion', header: 'Última venta' },
    { id: 'ageing', group: 'rotacion', header: 'Ageing' },
    // Real now (`productos_erp.stock`): out of the "coming soon" group.
    { id: 'stock', group: 'rotacion', header: 'Stock' },
    // Sell in lowers the cost, sell out adds to profit: each figure next to the one without them. On the Gauss
    // basis, so never for `tplink.solo` (the backend sends none).
    ...(tpSolo
      ? []
      : [
          { id: 'costo', group: 'sellin', header: 'Costo' },
          { id: 'costo_sell_in', group: 'sellin', header: 'Costo c/ sell in' },
          { id: 'sell_in', group: 'sellin', header: 'Sell in' },
          { id: 'sell_out', group: 'sellin', header: 'Sell out' },
          { id: 'total_gauss_sell', group: 'sellin', header: 'Total c/ sell in/out' },
          // No such markup with "Costos TP" (the sell in is on the Gauss cost): shown empty, never a sort -- from
          // the toggle's click (`costosTp`), not once the TP board answers (`tpOn`).
          {
            id: 'markup_sell',
            group: 'sellin',
            header: 'Markup c/ sell in/out',
            ...(tpOn || costosTp ? { sortable: false } : {}),
          },
        ]),
  ];
  return canSeeMargin ? columns : columns.filter((col) => !MARGIN_COLUMNS.has(col.id));
}
