import { formatDateOnly } from '../../utils/dateUtils';

/** Helpers of the sell-out programs UI (campanas-sistema slice E). */

const DIA = { day: '2-digit', month: '2-digit', year: 'numeric' };

const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

/** «2 activas», a group's pill. */
export const textoActivas = (n) => plural(n, 'activa', 'activas');

/** «3 campañas asignadas a «MARCA PROG». 1 ya lo tenía.», the bulk bar's line after an assignment. */
export function textoAsignadas({ asignadas, sin_cambio: sinCambio }, nombre) {
  const partes = [`${plural(asignadas, 'campaña asignada', 'campañas asignadas')} a «${nombre}».`];
  if (sinCambio > 0) partes.push(`${sinCambio} ya lo ${sinCambio === 1 ? 'tenía' : 'tenían'}.`);
  return partes.join(' ');
}

export { plural };

/** «01/08/2026 – 31/10/2026». */
export const fechasDe = (desde, hasta) => `${formatDateOnly(desde, DIA)} – ${formatDateOnly(hasta, DIA)}`;

const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];

/** «Oct–Dic 2026»: the calendar quarter holding `fecha` ('YYYY-MM-DD'). */
export function trimestreDe(fecha) {
  const [anio, mes] = fecha.split('-').map(Number);
  const primero = Math.floor((mes - 1) / 3) * 3;
  return `${MESES[primero]}–${MESES[primero + 2]} ${anio}`;
}

/** «2 campañas renovadas en «MARCA PROG» para Ene–Mar 2027.», the Programas line after Renovar programa. */
export const textoRenovado = (creadas, programa, fechaDesde) =>
  `${plural(creadas, 'campaña renovada', 'campañas renovadas')} en «${programa}» para ${trimestreDe(fechaDesde)}.`;

/** A campaign name as the backend's `nombres` compares it: ignoring case and repeated spaces. */
export const nombreNormalizado = (nombre) => nombre.split(/\s+/).filter(Boolean).join(' ').toLowerCase();

/** A suggestion's identity: its dates, which the backend groups by (exactly the same dates). */
export const claveSugerencia = (s) => `${s.fecha_desde}|${s.fecha_hasta}`;

/** Where the focus goes when a dialog's opener is gone: the programs heading. */
export const RESPALDOS_DE_FOCO = ['#sell-out-programas-titulo'];
