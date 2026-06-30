// Formatting and display utilities for Productos page

/**
 * Formats a date string as GMT-3 (Argentina timezone).
 * Assumes the input string lacks timezone info and should be treated as UTC.
 */
export function formatearFechaGMT3(fechaString) {
  const fecha = new Date(fechaString + 'Z'); // Force UTC interpretation
  const opciones = {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'America/Argentina/Buenos_Aires'
  };
  return fecha.toLocaleString('es-AR', opciones);
}

/**
 * Returns true if the value is empty or a valid finite number.
 */
export function isValidNumericInput(value) {
  if (value === '' || value === null || value === undefined) return true;
  const num = parseFloat(value);
  return !isNaN(num) && isFinite(num);
}

/**
 * Returns a sort-direction icon for a column given the current sort order array.
 * @param {string} columna
 * @param {Array<{columna: string, direccion: string}>} ordenColumnas
 */
export function getIconoOrden(columna, ordenColumnas) {
  const orden = ordenColumnas.find(o => o.columna === columna);
  if (!orden) return '↕';
  return orden.direccion === 'asc' ? '▲' : '▼';
}

/**
 * Returns the 1-based position of a column in the current sort order, or null if not sorted.
 * @param {string} columna
 * @param {Array<{columna: string, direccion: string}>} ordenColumnas
 */
export function getNumeroOrden(columna, ordenColumnas) {
  const index = ordenColumnas.findIndex(o => o.columna === columna);
  return index >= 0 ? index + 1 : null;
}
