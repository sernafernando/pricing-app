/**
 * The preset date windows shared by the ML sales view and the métricas
 * dashboard, in their OWN module.
 *
 * They lived beside `DateRangeFilter` until ESLint's
 * `react-refresh/only-export-components` pointed out the obvious: a file
 * that exports a component AND a function breaks Fast Refresh. The rule's
 * own advice is this file.
 *
 */
import { toLocalDateString } from './dateUtils';

/** `fecha` minus `meses`, never spilling into the following month.
 *
 * `Date.setMonth` keeps the day of month, so asking for three months
 * before 31 May yields 31 February -- which JavaScript normalises to 3
 * March. Clamping the day to the target month's last valid one is what
 * "three months earlier" means to a reader looking at a date picker. */
function restarMesesSinDesbordar(fecha, meses) {
  const anio = fecha.getFullYear();
  const mes = fecha.getMonth() - meses;
  const dia = fecha.getDate();
  // Day 0 of the NEXT month is the last day of this one.
  const ultimoDiaDelMesDestino = new Date(anio, mes + 1, 0).getDate();
  return new Date(anio, mes, Math.min(dia, ultimoDiaDelMesDestino));
}

export function calcularRangoPreset(filtro, hoy = new Date()) {
  const formatearFechaISO = (fecha) => toLocalDateString(fecha);

  let desde;
  let hasta = hoy;

  switch (filtro) {
    case 'hoy':
      desde = new Date(hoy);
      break;
    case 'ayer':
      desde = new Date(hoy);
      desde.setDate(desde.getDate() - 1);
      hasta = new Date(desde);
      break;
    case '3d':
      desde = new Date(hoy);
      desde.setDate(desde.getDate() - 2);
      break;
    case '7d':
      desde = new Date(hoy);
      desde.setDate(desde.getDate() - 6);
      break;
    case '14d':
      desde = new Date(hoy);
      desde.setDate(desde.getDate() - 13);
      break;
    case 'mesActual':
      desde = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
      break;
    case '30d':
      desde = new Date(hoy);
      desde.setDate(desde.getDate() - 29);
      break;
    case '3m':
      // CLAMPED to the target month's last day. `setMonth(getMonth() - 3)`
      // on 31 May asks for 31 February, and JavaScript rolls that into
      // March -- so "últimos 3 meses" silently started in the WRONG month,
      // two days late, on every 31st. Métricas has carried that since it
      // was written; fixing it here fixes it there too, which is the point
      // of the two screens sharing one module.
      desde = restarMesesSinDesbordar(hoy, 3);
      break;
    default:
      return null;
  }

  return { desde: formatearFechaISO(desde), hasta: formatearFechaISO(hasta) };
}
