import { downloadCsv } from '../../../utils/ventasMlExport';

/**
 * The Auditoría de stock as an Excel workbook (auditoria-stock L7): every row of the view, with its filters and sort
 * (`params` from `buildStockAuditExportParams`), saved under the server's file name. `downloadCsv` saves any blob the
 * backend answers. Throws an Error whose message is safe to show the operator.
 */
export async function exportAuditoriaStockExcel(params) {
  await downloadCsv('/ml-publications/view/stock-audit/export', params, {
    genericError: 'No se pudo exportar la auditoría de stock.',
  });
}
