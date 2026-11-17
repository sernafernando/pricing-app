/**
 * The Métricas board's channel (vpf-metricas-canal-fe S5, S6, C3, C4): Mercado Libre, the ventas por fuera of the
 * GBP PDF, or both. The backend enforces every rule here; the screen only offers what it would accept.
 */

export const CANALES = ['ml', 'fuera', 'todo'];
export const DEFAULT_CANAL = 'ml';
export const CANAL_OPTIONS = [
  { value: 'ml', label: 'ML' },
  { value: 'fuera', label: 'Por fuera' },
  { value: 'todo', label: 'Todo' },
];

// The cost of the fuera lines: Costo D (Precio Costo x 1,065, the default) or the plain Precio Costo.
export const COSTOS = ['costo_d', 'costo'];
export const DEFAULT_COSTO = 'costo_d';
export const COSTO_OPTIONS = [
  { value: 'costo_d', label: 'Costo D' },
  { value: 'costo', label: 'Costo' },
];
export const COSTO_LABELS = { costo_d: 'Costo D', costo: 'Costo' };

// The `rows[].canal` of canal=todo, as the Canal column reads it.
export const ROW_CANAL_LABELS = { ml: 'ML', fuera: 'Por fuera', ambos: 'ML + fuera' };

const VER_ML = 'ml_metricas.ver';
const VER_FUERA = 'ventas_fuera.ver_metricas_pdf';

/** The channels a viewer may use, in the selector's order (S5): `tplink.solo` keeps ML only (403 elsewhere). */
export function canalesPermitidos(tienePermiso, { tpSolo = false } = {}) {
  const ml = tienePermiso(VER_ML);
  const fuera = !tpSolo && tienePermiso(VER_FUERA);
  return [ml && 'ml', fuera && 'fuera', ml && fuera && 'todo'].filter(Boolean);
}

/** `requested` when the viewer may use it; otherwise the first channel it may (a PDF-only viewer: Por fuera). */
export function canalInicial(requested, permitidos) {
  if (permitidos.includes(requested)) return requested;
  return permitidos[0] ?? DEFAULT_CANAL;
}

/** Total Gauss, markup and cost figures of a channel (S6): each side needs its own profit permission. */
export function margenPermitido(canal, tienePermiso) {
  const ml = tienePermiso('ml_metricas.ver_ganancia');
  const fuera = tienePermiso('ventas_fuera.ver_ganancia');
  if (canal === 'fuera') return fuera;
  if (canal === 'todo') return ml && fuera;
  return ml;
}

const capitalize = (text) => (text ? text.charAt(0).toUpperCase() + text.slice(1).toLowerCase() : '');
const INT_FORMAT = new Intl.NumberFormat('es-AR');

/** `kpis.fuera.por_tipo` as one line: "104 Fc A · 54 Fc B · 6 Nc A". */
export function formatPorTipo(porTipo) {
  return (porTipo ?? []).map(({ tipo, letra, cantidad }) => `${INT_FORMAT.format(cantidad)} ${capitalize(tipo)} ${letra}`).join(' · ');
}

const two = (n) => String(n).padStart(2, '0');

/** When a PDF was uploaded, as "16/11 12:10" (local time); null when unknown. */
export function formatPdfStamp(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return `${two(date.getDate())}/${two(date.getMonth() + 1)} ${two(date.getHours())}:${two(date.getMinutes())}`;
}

/** A "sin producto" row: a fuera line whose code is no product of the catalog (negative product id, C3). */
export const isSinProducto = (row) => Number(row?.product_item_id) < 0;
