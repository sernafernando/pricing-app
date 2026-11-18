/** The Auditoría de stock view's hideable columns and KPI cards (auditoria-stock S3, S7, L6). The columns are kept in
 * the user's saved layout (pubml-columnas-presets), the KPI cards per browser (`useHiddenKpis`). The product column is
 * always shown. */

/** The audit table's column groups (`StockAuditTable`); the picker shows each as one block. */
export const AUDIT_GROUPS = {
  STOCK: 'Stock (unidades)',
  VALOR: 'Valor stock (USD · ARS)',
  VENTAS: 'Ventas (unidades)',
  MARKUP: 'Markup con sell in / sell out',
  RESULTADO: 'Resultado',
  ROTACION: 'Rotación',
};
const { STOCK, VALOR, VENTAS, MARKUP, RESULTADO, ROTACION } = AUDIT_GROUPS;

/**
 * Every hideable column in the table's default order, with its group and the permission it needs (`sales`,
 * `margin`). Keep it in step with `StockAuditTable`'s columns.
 */
export const AUDIT_COLUMN_OPTIONS = [
  { id: 'tipo', label: 'Tipo' },
  { id: 'estado', label: 'Estado' },
  { id: 'promos_aplicadas', label: 'Promos aplicadas' },
  { id: 'unidades_erp', label: 'Stock ERP', group: STOCK },
  { id: 'unidades_full', label: 'Stock Full', group: STOCK },
  { id: 'unidades_total', label: 'Stock total', group: STOCK },
  { id: 'valor_erp', label: 'Valor ERP', group: VALOR },
  { id: 'valor_full', label: 'Valor Full', group: VALOR },
  { id: 'valor_total', label: 'Valor total', group: VALOR },
  { id: 'unidades_7d', label: 'Ventas 7D', group: VENTAS, sales: true },
  { id: 'unidades_30d', label: 'Ventas 30D', group: VENTAS, sales: true },
  { id: 'units_trend', label: 'Tendencia de ventas', group: VENTAS, sales: true },
  { id: 'markup', label: 'Markup actual', group: MARKUP, margin: true },
  { id: 'markup_30d', label: 'Markup real 30D', group: MARKUP, sales: true, margin: true },
  { id: 'markup_trend', label: 'Tendencia de markup', group: MARKUP, sales: true, margin: true },
  { id: 'facturado_30d', label: 'Facturado 30D', group: RESULTADO, sales: true },
  { id: 'total_gauss_30d', label: 'Total Gauss 30D', group: RESULTADO, sales: true, margin: true },
  { id: 'ultima_venta', label: 'Última venta', group: ROTACION, sales: true },
  { id: 'ageing', label: 'Ageing', group: ROTACION, sales: true },
  { id: 'cobertura', label: 'Días de cobertura', group: ROTACION, sales: true },
  { id: 'rotacion', label: 'Rotación (veces)', group: ROTACION, sales: true },
];

export const auditColumnOptions = ({ canSeeSales, canSeeMargin }) =>
  AUDIT_COLUMN_OPTIONS.filter((option) => (!option.sales || canSeeSales) && (!option.margin || canSeeMargin));

/**
 * The audit's columns as the page's column layout reads them (pubml-columnas-presets S1, S2): the product column
 * first and fixed, then every hideable one the viewer may see, in the table's order.
 */
export const auditColumnLayout = (permissions) => [
  { key: 'descripcion', label: 'Producto' },
  ...auditColumnOptions(permissions).map(({ id, label, group }) => ({ key: id, label, group })),
];

export const AUDIT_KPI_OPTIONS = [
  { id: 'valor_erp', label: 'Valor stock ERP' },
  { id: 'valor_full', label: 'Valor stock Full' },
  { id: 'valor_total', label: 'Valor stock total' },
  { id: 'unidades', label: 'Unidades' },
  { id: 'sin_publicacion_activa', label: 'Con stock sin publicación activa' },
  { id: 'promo', label: 'Productos con stock' },
];
