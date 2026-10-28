import { preciosAPI } from '../../services/api';
import { formatRate, isBlank } from './priceFormat';

/**
 * The rebate and web transfer of ONE product as Productos edits them (useProductosToggles: same endpoints, payloads,
 * defaults and validation): what their editors open with and the write each edit leads to. Shared by the product
 * panel's ProductToggles and Publicaciones ML's row, so both write the same thing.
 */

// Productos' defaults for a product that never had them.
export const REBATE_DEFAULT = 3.8;
export const WEB_TRANSF_DEFAULT = 6.0;

/** Productos' parse: the first comma is the decimal separator. */
export const parsePercent = (text) => parseFloat(String(text).replace(',', '.'));

export const storedRebate = (product) => (isBlank(product.porcentaje_rebate) ? REBATE_DEFAULT : product.porcentaje_rebate);

/** What the rebate editor opens with. */
export const rebateDraft = (product) => ({ participa: Boolean(product.participa_rebate), porcentaje: formatRate(storedRebate(product)) });

/** What the web transfer editor opens with. */
export const webTransfDraft = (product) => ({
  participa: Boolean(product.participa_web_transferencia),
  porcentaje: formatRate(isBlank(product.porcentaje_markup_web) ? WEB_TRANSF_DEFAULT : product.porcentaje_markup_web),
  preservar: Boolean(product.preservar_porcentaje_web),
});

/**
 * The write of an edited rebate: `{ error }` for a value that is not sent, or `{ write(itemId), saved, fallback }`.
 * Turning it off sends the stored percentage, as Productos' quick toggle does: the field is hidden then, so whatever
 * it holds is not read.
 */
export function rebateWrite(product, { participa, porcentaje }) {
  const value = participa ? parsePercent(porcentaje) : storedRebate(product);
  if (!Number.isFinite(value) || value < 0 || value > 100) return { error: 'El porcentaje de rebate debe ser un número entre 0 y 100.' };
  return {
    write: (itemId) => preciosAPI.setRebate(itemId, { participa_rebate: participa, porcentaje_rebate: value }),
    saved: 'Rebate guardado',
    fallback: 'No se pudo guardar el rebate.',
  };
}

/** The write of an edited web transfer. As Productos, an unreadable percentage is sent as 0. */
export function webTransfWrite(product, { participa, porcentaje, preservar }) {
  const value = parsePercent(porcentaje) || 0;
  return {
    write: (itemId) => preciosAPI.setWebTransferencia(itemId, { participa, porcentaje_markup: value, preservar_porcentaje: preservar }),
    saved: 'Web transferencia guardada',
    fallback: 'No se pudo guardar web transferencia.',
  };
}
