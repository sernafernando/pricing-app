/**
 * Display helpers for the ventas-por-fuera PDF loads (upload modal and history page). Dates from the API come as
 * `YYYY-MM-DD` (read as text, never shifted by the time zone) or ISO datetimes (shown in local time).
 */

const MONEY = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const INT = new Intl.NumberFormat('es-AR');

const presente = (value) => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));

/** `$ 1.234,50`, `-$ 1.234,50` for negatives, '—' when unknown. */
export function dinero(value) {
  if (!presente(value)) return '—';
  const num = Number(value);
  return `${num < 0 ? '-' : ''}$ ${MONEY.format(Math.abs(num))}`;
}

/** `1.187`, '—' when unknown. */
export function entero(value) {
  return presente(value) ? INT.format(Number(value)) : '—';
}

const partes = (iso) => {
  const [anio, mes, dia] = String(iso).slice(0, 10).split('-');
  return { anio, mes, dia };
};

/** `2026-10-31` -> `31/10/2026`. */
export function fecha(iso) {
  if (!iso) return '—';
  const { anio, mes, dia } = partes(iso);
  return `${dia}/${mes}/${anio}`;
}

/** `2026-10-31` -> `31/10`. */
export function diaMes(iso) {
  if (!iso) return '—';
  const { mes, dia } = partes(iso);
  return `${dia}/${mes}`;
}

/** `01/10/2026 – 31/10/2026`. */
export function rango(desde, hasta) {
  return `${fecha(desde)} – ${fecha(hasta)}`;
}

/** `01/10 – 31/10/2026` (the year once when both dates share it). */
export function rangoCorto(desde, hasta) {
  if (!desde || !hasta) return '—';
  return partes(desde).anio === partes(hasta).anio ? `${diaMes(desde)} – ${fecha(hasta)}` : rango(desde, hasta);
}

const dos = (n) => String(n).padStart(2, '0');

const aFecha = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
};

/** ISO datetime -> `16/11/2026 12:10` (local time). */
export function fechaHora(iso) {
  const d = aFecha(iso);
  if (!d) return '—';
  return `${dos(d.getDate())}/${dos(d.getMonth() + 1)}/${d.getFullYear()} ${dos(d.getHours())}:${dos(d.getMinutes())}`;
}

/** ISO datetime -> `16/11 12:10` (local time). */
export function diaHora(iso) {
  const d = aFecha(iso);
  if (!d) return '—';
  return `${dos(d.getDate())}/${dos(d.getMonth() + 1)} ${dos(d.getHours())}:${dos(d.getMinutes())}`;
}

/** `Ana, Bruno y Carla`. */
export function enumerar(nombres) {
  const lista = (nombres || []).filter(Boolean);
  if (lista.length <= 1) return lista.join('');
  return `${lista.slice(0, -1).join(', ')} y ${lista.at(-1)}`;
}

/** `Fc A 00008-00018011`, as GBP prints a document. */
export function comprobante({ tipo, letra, punto_venta: puntoVenta, numero }) {
  return `${tipo} ${letra} ${String(puntoVenta).padStart(5, '0')}-${String(numero).padStart(8, '0')}`;
}

/** The text of a failed upload/read: the API message (`{error:{message}}` or `{detail:{message}}` or a string
 * `detail`), a clear one for a 413 without body, else `fallback`. */
export function mensajeError(err, fallback) {
  const data = err?.response?.data;
  const mensaje = data?.error?.message || data?.detail?.message || (typeof data?.detail === 'string' ? data.detail : '');
  if (mensaje) return mensaje;
  if (err?.response?.status === 413) return 'El PDF supera los 20 MB: exportalo de nuevo con menos páginas.';
  return fallback;
}
