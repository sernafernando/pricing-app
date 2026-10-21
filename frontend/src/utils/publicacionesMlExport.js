import { downloadCsv } from './ventasMlExport';
import { exportarCsvASheets } from './googleSheetsExport';

// The views with an export: the Agrupado tree has none.
const EXPORT_URLS = {
  publicacion: '/ml-publications/view/items/export',
  producto: '/ml-publications/view/products/export',
};

export const canExportVista = (vista) => Object.hasOwn(EXPORT_URLS, vista);

/** `publicaciones-ml-<vista>-<YYYY-MM-DD>.csv`, the operator's own day. */
export function exportFilename(vista, today = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `publicaciones-ml-${vista}-${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}.csv`;
}

/**
 * Downloads the CSV of the current view of Publicaciones ML. `params` must be the list's own request without the
 * page (`buildExportParams`), so the file holds what the list holds. Throws an Error whose message is safe to show
 * the operator (the backend's: too many rows, a slow query, no permission).
 */
export async function exportPublicacionesCsv(vista, params) {
  await downloadCsv(exportUrl(vista), params, exportOptions(vista));
}

/** The same export, sent to a new Google Sheet (`exportarCsvASheets`) titled like the file. */
export async function exportPublicacionesSheets(vista, params) {
  return exportarCsvASheets(exportUrl(vista), params, exportOptions(vista));
}

function exportUrl(vista) {
  if (!canExportVista(vista)) throw new Error('Esta vista no se puede exportar.');
  return EXPORT_URLS[vista];
}

const exportOptions = (vista) => ({ filename: exportFilename(vista), genericError: 'No se pudo exportar las publicaciones.' });
