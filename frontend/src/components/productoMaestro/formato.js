/** Number formats of the product master, as the approved mock shows them (es-AR). */

/** `4561` -> `4.561`; empty -> `—`. */
export function numero(value) {
  if (value === null || value === undefined || value === '') return '—';
  return Number(value).toLocaleString('es-AR');
}

/** `('USD', 4.6606)` -> `USD 4,66`. */
export function moneda(codigo, value) {
  if (value === null || value === undefined) return '—';
  const n = Number(value).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return codigo ? `${codigo} ${n}` : n;
}

/** `11999.4` -> `$ 11.999`. */
export function pesos(value) {
  if (value === null || value === undefined) return '—';
  return `$ ${Math.round(Number(value)).toLocaleString('es-AR')}`;
}
