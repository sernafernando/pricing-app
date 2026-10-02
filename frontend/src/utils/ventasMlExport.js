import api from '../services/api';

const FALLBACK_NAME = 'ventas-ml.csv';
const GENERIC_ERROR = 'No se pudo exportar las ventas.';

export function filenameFromDisposition(header) {
  const match = /filename="?([^";]+)"?/i.exec(header || '');
  return match ? match[1] : FALLBACK_NAME;
}

// With `responseType: 'blob'` an error body arrives as a Blob too, so the
// backend's message (e.g. "too many sales, narrow the filters") has to be
// read back out of it.
async function messageFromError(err) {
  const data = err?.response?.data;
  if (data && typeof data.text === 'function') {
    try {
      const parsed = JSON.parse(await data.text());
      const message = parsed?.error?.message || parsed?.detail;
      if (typeof message === 'string' && message) return message;
    } catch {
      // not JSON: fall through to the generic message
    }
  }
  return GENERIC_ERROR;
}

/**
 * Downloads the CSV of the filtered set. `params` must come from
 * `buildVentasMLFilterParams` -- the SAME builder the list and the KPI strip
 * use -- so the file holds what the table holds. Throws an Error whose
 * message is safe to show the operator.
 */
export async function exportVentasCsv(params) {
  await downloadCsv('/ml-ventas-ops/sales/export', params);
}

/** Métricas ML board CSV (`GET /ml-metricas/board/export`): same download
 * and error handling, params from `buildMetricasMLParams`. */
export async function exportMetricasCsv(params) {
  await downloadCsv('/ml-metricas/board/export', params);
}

async function downloadCsv(url, params) {
  let response;
  try {
    response = await api.get(url, { params, responseType: 'blob' });
  } catch (err) {
    throw new Error(await messageFromError(err));
  }
  const objectUrl = URL.createObjectURL(response.data);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = filenameFromDisposition(response.headers?.['content-disposition']);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(objectUrl);
}
