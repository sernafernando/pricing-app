/** The Auditoría de stock view's hideable columns and KPI cards (auditoria-stock S3, S7, L6), each remembered per
 * browser by the page (`useHiddenKpis`). The product column is always shown. */

/** Every hideable column, in the picker's order, with the permission it needs (`sales`, `margin`). */
export const AUDIT_COLUMN_OPTIONS = [
  { id: 'unidades_erp', label: 'Stock ERP' },
  { id: 'unidades_full', label: 'Stock Full' },
  { id: 'unidades_total', label: 'Stock total' },
  { id: 'valor_erp', label: 'Valor ERP' },
  { id: 'valor_full', label: 'Valor Full' },
  { id: 'valor_total', label: 'Valor total' },
  { id: 'unidades_7d', label: 'Ventas 7D', sales: true },
  { id: 'unidades_30d', label: 'Ventas 30D', sales: true },
  { id: 'units_trend', label: 'Tendencia de ventas', sales: true },
  { id: 'markup', label: 'Markup actual', margin: true },
  { id: 'markup_30d', label: 'Markup real 30D', sales: true, margin: true },
  { id: 'markup_trend', label: 'Tendencia de markup', sales: true, margin: true },
  { id: 'facturado_30d', label: 'Facturado 30D', sales: true },
  { id: 'total_gauss_30d', label: 'Total Gauss 30D', sales: true, margin: true },
  { id: 'tipo', label: 'Tipo' },
  { id: 'estado', label: 'Estado' },
  { id: 'promos_aplicadas', label: 'Promos aplicadas' },
];

export const auditColumnOptions = ({ canSeeSales, canSeeMargin }) =>
  AUDIT_COLUMN_OPTIONS.filter((option) => (!option.sales || canSeeSales) && (!option.margin || canSeeMargin));

export const AUDIT_KPI_OPTIONS = [
  { id: 'valor_erp', label: 'Valor stock ERP' },
  { id: 'valor_full', label: 'Valor stock Full' },
  { id: 'valor_total', label: 'Valor stock total' },
  { id: 'unidades', label: 'Unidades' },
  { id: 'sin_publicacion_activa', label: 'Con stock sin publicación activa' },
  { id: 'promo', label: 'Productos con stock' },
];
