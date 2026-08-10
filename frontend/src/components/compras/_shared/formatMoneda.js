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
 * Converts an amount from one currency to another for an origin→destination leg.
 *
 * Mirrors the backend authority `fx_service.convertir_entre_monedas`
 * (backend/app/services/fx_service.py) exactly, including its rounding:
 *   - same currency  → identity (the TC is irrelevant and is not consulted)
 *   - ARS → USD      → monto / tc
 *   - USD → ARS      → monto * tc
 *
 * Returns `null` — never 0 and never the unconverted amount — when the
 * conversion cannot be performed (unusable TC, non-numeric amount, currency
 * pair outside the ARS/USD whitelist). Falling back to the raw amount would
 * deduct a number denominated in the wrong currency, which is exactly how the
 * on-screen total drifted away from what the backend records.
 *
 * @param {number|string} monto
 * @param {string} desde - source currency
 * @param {string} hacia - destination currency
 * @param {number|string|null|undefined} tc - tipo de cambio (ARS per 1 USD)
 * @returns {number|null}
 */
export const convertirMonto = (monto, desde, hacia, tc) => {
  const montoNum = Number(monto);
  if (monto === '' || monto === null || monto === undefined || !Number.isFinite(montoNum)) return null;
  if (desde === hacia) return montoNum;
  const tcNum = Number(tc);
  if (!Number.isFinite(tcNum) || tcNum <= 0) return null;
  if (desde === 'ARS' && hacia === 'USD') return Math.round((montoNum / tcNum) * 100) / 100;
  if (desde === 'USD' && hacia === 'ARS') return Math.round(montoNum * tcNum * 100) / 100;
  return null;
};

/**
 * ERP `curr_id_transaction` → módulo-compras currency code.
 *
 * Mirrors the backend authority `_curr_id_a_moneda`
 * (backend/app/services/pedidos_service.py) 1:1, including its behaviour for
 * unknown ids: ERP convention is 1=ARS, 2=USD, anything else maps to nothing.
 *
 * Returns `null` — NEVER a default currency — on unknown/null input. An ERP
 * document whose currency we cannot identify must not be rendered with a
 * confident symbol: silently defaulting to ARS is exactly how a 1.500.000 ARS
 * invoice ended up displayed as "US$1.500.000,00".
 *
 * @param {number|string|null|undefined} currId - `curr_id_transaction` del ERP
 * @returns {'ARS'|'USD'|null} null = unknown, caller MUST handle it explicitly
 */
export const monedaDeCurrId = (currId) => {
  if (currId === null || currId === undefined || currId === '') return null;
  const id = Number(currId);
  if (id === 1) return 'ARS';
  if (id === 2) return 'USD';
  return null;
};

/**
 * Formatea el monto de un documento del ERP usando SU PROPIA moneda.
 *
 * Use this — not `formatMoneda(value, entidadLocal.moneda)` — for any amount
 * coming from an ERP document (factura / NC). The ERP document carries its own
 * currency in `curr_id_transaction` and it does NOT have to match the currency
 * of the local pedido or NC it is being linked to: cross-currency linking is a
 * supported, backend-tested business case.
 *
 * When the currency cannot be identified the amount is rendered WITHOUT any
 * currency symbol plus an explicit marker, so the reader can tell the currency
 * is unknown instead of being shown a wrong-but-confident "$" or "US$".
 *
 * @param {number|string|null|undefined} value
 * @param {number|string|null|undefined} currId - `curr_id_transaction` del ERP
 * @returns {string} ej: "$1.500.000,00" / "US$1.000,00" /
 *                   "1.500.000,00 (moneda desconocida)"
 */
export const formatMonedaErp = (value, currId) => {
  const moneda = monedaDeCurrId(currId);
  if (moneda === null) {
    const num = Number(value) || 0;
    const monto = num.toLocaleString('es-AR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return `${monto} (moneda desconocida)`;
  }
  return formatMoneda(value, moneda);
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
