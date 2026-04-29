/**
 * Helpers de formato de moneda para el módulo compras.
 *
 * Convención del módulo: la empresa paga todo en ARS. Los pedidos se
 * pueden cargar en USD pero contablemente la deuda es ARS. Por eso, en
 * todas las vistas mostramos el equivalente ARS (= monto * TC) cuando
 * el pedido está en USD y tiene TC asignado.
 *
 * Si el TC se edita post-aprobado (Feature B del módulo), el equivalente
 * ARS se recalcula automáticamente porque siempre es derivado.
 */

/**
 * Formatea un número como moneda local con su prefijo correspondiente.
 *
 * @param {number|string|null|undefined} value
 * @param {'ARS'|'USD'} [moneda='ARS']
 * @returns {string} ej: "$1.500.000,00" / "US$1.000,00"
 */
export const formatMoneda = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

/**
 * Calcula el equivalente en ARS de un monto en USD usando el TC dado.
 * Si moneda no es USD o no hay TC válido → retorna null (= no mostrar).
 *
 * @param {number|string} monto
 * @param {string} moneda
 * @param {number|string|null|undefined} tc - tipo de cambio (ARS por 1 USD)
 * @returns {number|null}
 */
export const equivalenteEnArs = (monto, moneda, tc) => {
  if (moneda !== 'USD') return null;
  const tcNum = Number(tc);
  if (!Number.isFinite(tcNum) || tcNum <= 0) return null;
  const montoNum = Number(monto) || 0;
  return montoNum * tcNum;
};

/**
 * Formatea un TC como número con coma decimal.
 *
 * @param {number|string|null|undefined} tc
 * @returns {string} ej: "1.500,00"
 */
export const formatTC = (tc) => {
  const num = Number(tc);
  if (!Number.isFinite(num) || num <= 0) return '—';
  return num.toLocaleString('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
};
