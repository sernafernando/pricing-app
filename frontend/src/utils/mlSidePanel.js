/**
 * Open a sale in MercadoLibre, in the browser extension's side panel when
 * present and in a new tab otherwise.
 *
 * Extension contract: its content script sets `data-ml-panel="1"` on
 * <html> and listens for `window.postMessage({ type: 'ml-open', url })`
 * from this origin.
 */

/** ML's sale URL uses the pack id when the sale belongs to a pack, else the order id. */
export function buildMlSaleUrl(packId, orderId) {
  const id = packId ?? orderId;
  if (id == null) return null;
  return `https://vendedores.mercadolibre.com.ar/ventas/${id}/detalle`;
}

export function isMlPanelAvailable() {
  return document.documentElement.dataset.mlPanel === '1';
}

export function openInMlPanel(url) {
  if (!url) return;
  if (isMlPanelAvailable()) {
    window.postMessage({ type: 'ml-open', url }, window.location.origin);
  } else {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}
