/**
 * Utilidades de fecha que usan timezone LOCAL del browser.
 *
 * ¿Por qué?  `new Date().toISOString()` devuelve UTC.
 * En Argentina (UTC-3) a las 21:00 local ya es el día siguiente en UTC,
 * lo que rompe cualquier query de "hoy" contra el backend.
 *
 * Regla: NUNCA usar toISOString() para obtener la fecha del usuario.
 *        Siempre usar estas funciones.
 */

/**
 * Devuelve la fecha local como "YYYY-MM-DD".
 * Reemplazo directo de: new Date().toISOString().split('T')[0]
 *
 * @param {Date} [date=new Date()] - Fecha a formatear (default: ahora)
 * @returns {string} "YYYY-MM-DD" en timezone local
 *
 * @example
 * toLocalDateString()                   // "2026-03-04" (hoy local)
 * toLocalDateString(new Date(2026, 0, 1)) // "2026-01-01"
 */
export const toLocalDateString = (date = new Date()) => {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
};

/**
 * Devuelve fecha+hora local como "YYYY-MM-DDTHH:mm".
 * Reemplazo directo de: new Date().toISOString().slice(0, 16)
 *
 * Útil para inputs datetime-local.
 *
 * @param {Date} [date=new Date()] - Fecha a formatear (default: ahora)
 * @returns {string} "YYYY-MM-DDTHH:mm" en timezone local
 *
 * @example
 * toLocalDateTimeString() // "2026-03-04T21:30"
 */
export const toLocalDateTimeString = (date = new Date()) => {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const h = String(date.getHours()).padStart(2, '0');
  const min = String(date.getMinutes()).padStart(2, '0');
  return `${y}-${m}-${d}T${h}:${min}`;
};

/**
 * Devuelve un timestamp local seguro para nombres de archivo.
 * Reemplazo directo de: new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5)
 *
 * @param {Date} [date=new Date()] - Fecha a formatear (default: ahora)
 * @returns {string} "YYYY-MM-DDTHH-mm-ss" en timezone local
 *
 * @example
 * toLocalTimestamp() // "2026-03-04T21-30-45"
 */
export const toLocalTimestamp = (date = new Date()) => {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const h = String(date.getHours()).padStart(2, '0');
  const min = String(date.getMinutes()).padStart(2, '0');
  const s = String(date.getSeconds()).padStart(2, '0');
  return `${y}-${m}-${d}T${h}-${min}-${s}`;
};
