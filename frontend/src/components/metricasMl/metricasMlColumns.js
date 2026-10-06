import { chainHeader } from '../../utils/metricasMlLevels';

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
  { id: 'rotacion', label: 'Rotación' },
  { id: 'sellin', label: 'Sell-in / Sell-out', soon: true },
];

const MARGIN_COLUMNS = new Set(['markup', 'markup_delta', 'markup_trend', 'markup_range', 'total_gauss']);

/** The "Agrupado" view's dimensions: the backend `dimension` value and the
 * name shown on its picker; the first column names the whole chain of levels. */
export const DIMENSION_OPTIONS = [
  { value: 'marca', label: 'Marca' },
  { value: 'categoria', label: 'Categoría' },
  { value: 'subcategoria', label: 'Subcategoría' },
  { value: 'tienda', label: 'Tienda' },
  { value: 'pm', label: 'PM' },
];

function productHeader(groupBy, dimension) {
  if (groupBy === 'publication') return 'Publicación / Producto';
  if (groupBy === 'group') return chainHeader(dimension);
  return 'Detalle / SKU / Marca';
}

export function buildBoardColumns({ canSeeMargin, periodLabel, groupBy, dimension }) {
  const columns = [
    { id: 'producto', group: 'producto', header: productHeader(groupBy, dimension), enableHiding: false },
    { id: 'units_24h', group: 'ventas', header: '24H' },
    { id: 'units_3d', group: 'ventas', header: '3D' },
    { id: 'units_7d', group: 'ventas', header: '7D' },
    { id: 'units_15d', group: 'ventas', header: '15D' },
    { id: 'units_30d', group: 'ventas', header: '30D' },
    { id: 'units_trend', group: 'ventas', header: 'Tendencia' },
    { id: 'markup', group: 'markup', header: 'Markup act.' },
    { id: 'markup_delta', group: 'markup', header: 'vs anterior' },
    { id: 'markup_trend', group: 'markup', header: 'Tendencia 90D' },
    { id: 'markup_range', group: 'markup', header: 'Mín / Máx 90D' },
    { id: 'gross', group: 'resultado', header: `Facturado ${periodLabel}` },
    { id: 'total_gauss', group: 'resultado', header: 'Total Gauss' },
    { id: 'last_sale', group: 'rotacion', header: 'Última venta' },
    { id: 'ageing', group: 'rotacion', header: 'Ageing' },
    // Real now (`productos_erp.stock`): out of the "coming soon" group.
    { id: 'stock', group: 'rotacion', header: 'Stock' },
    { id: 'compras_30d', group: 'sellin', header: 'Compras 30D' },
    { id: 'sell_through', group: 'sellin', header: 'Sell-Through' },
    { id: 'cobertura', group: 'sellin', header: 'Cobertura' },
  ];
  return canSeeMargin ? columns : columns.filter((col) => !MARGIN_COLUMNS.has(col.id));
}
