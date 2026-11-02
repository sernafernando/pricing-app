import { formatDateOnly } from '../../utils/dateUtils';

/** Helpers of the sell-out programs UI (campanas-sistema slice E). */

const DIA = { day: '2-digit', month: '2-digit', year: 'numeric' };

const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

/** "Ver: Por programa | Lista" (`?vista=`). */
export const VISTAS = [
  { value: 'programas', label: 'Por programa' },
  { value: 'lista', label: 'Lista' },
];

/** How many columns the campaigns table has: the checkbox one only with a selection. */
export const columnasCampanas = (seleccionable) => (seleccionable ? 7 : 6);

/** «3 campañas · 2 nombres · 01/08/2026 – 31/10/2026», a group row's (or a suggestion's) summary. */
export function resumenDeGrupo({ campanas, nombres, desde, hasta }) {
  const fechas = `${formatDateOnly(desde, DIA)} – ${formatDateOnly(hasta, DIA)}`;
  return `${plural(campanas, 'campaña', 'campañas')} · ${plural(nombres, 'nombre', 'nombres')} · ${fechas}`;
}

/** «2 activas», a group's pill. */
export const textoActivas = (n) => plural(n, 'activa', 'activas');

/** «3 campañas asignadas a «MARCA PROG». 1 ya lo tenía.», the bulk bar's line after an assignment. */
export function textoAsignadas({ asignadas, sin_cambio: sinCambio }, nombre) {
  const partes = [`${plural(asignadas, 'campaña asignada', 'campañas asignadas')} a «${nombre}».`];
  if (sinCambio > 0) partes.push(`${sinCambio} ya lo ${sinCambio === 1 ? 'tenía' : 'tenían'}.`);
  return partes.join(' ');
}

export { plural };
