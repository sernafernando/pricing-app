/**
 * DateRangeFilter — quick-preset + custom date-range picker.
 *
 * "El mismo módulo": this is the ONE date-range control for ML sales
 * views. It used to live only inside DashboardMetricasML.jsx; extracted
 * here so VentasML.jsx (and any future screen) shares the exact same
 * preset arithmetic and custom-range behaviour instead of a copy that
 * would drift the first time one side got touched -- two screens
 * disagreeing about what "últimos 7 días" means is the same
 * two-numbers-for-one-question failure this codebase fights everywhere
 * else.
 *
 * Owns NO url/query-param persistence: it is a controlled component.
 * The caller passes the current `fechaDesde`/`fechaHasta` (and, if it
 * wants the active-preset highlight to survive a reload/back-nav, the
 * `filtroActivo` it last received from `onChange`) and gets notified via
 * `onChange({ desde, hasta, filtro })` when a preset or the custom range
 * is applied. Each page keeps its own persistence (query params, plain
 * state, whatever).
 *
 * Custom range only applies on "Aplicar", never while typing -- the same
 * behaviour DashboardMetricasML had. There is deliberately no Enter
 * shortcut: an earlier version of this docblock claimed one and none
 * existed, which is the kind of promise a reader trusts and then finds
 * missing. Add the handler before adding the claim back.
 *
 * Usage:
 *   <DateRangeFilter
 *     fechaDesde={fechaDesde}
 *     fechaHasta={fechaHasta}
 *     filtroActivo={filtroActivo}
 *     onChange={({ desde, hasta, filtro }) => { ... }}
 *   />
 */

import { useState, useEffect, useId } from 'react';
import { Calendar } from 'lucide-react';
import { toLocalDateString } from '../utils/dateUtils';
import styles from './DateRangeFilter.module.css';

const PRESETS = [
  { key: 'hoy', label: 'Hoy' },
  { key: 'ayer', label: 'Ayer' },
  { key: '3d', label: '3d' },
  { key: '7d', label: '7d' },
  { key: '14d', label: '14d' },
  { key: 'mesActual', label: 'Mes actual' },
  { key: '30d', label: '30d' },
  { key: '3m', label: '3m' },
];

/**
 * Given a preset key, returns `{ desde, hasta }` as "YYYY-MM-DD" strings,
 * computed against `hoy` (defaults to `new Date()`, overridable for tests).
 * Arithmetic taken from DashboardMetricasML.jsx's `aplicarFiltroRapido`
 * and kept as it was -- `7d` is `hoy - 6`, not `- 7`, and normalising that
 * would make the two screens disagree about the same word.
 *
 * ONE deliberate exception, `3m`: the original used
 * `setMonth(getMonth() - 3)`, which on 31 May asks for 31 February and
 * JavaScript rolls into March, so the window silently started in the
 * wrong month. That is a bug, not a convention, and sharing this module
 * fixes it on both screens at once. Everything else stays.
 */
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

export default function DateRangeFilter({ fechaDesde, fechaHasta, filtroActivo, onChange }) {
  const idBase = useId();
  const [mostrarDropdown, setMostrarDropdown] = useState(false);
  const [fechaTemporal, setFechaTemporal] = useState({ desde: fechaDesde, hasta: fechaHasta });

  // Sincronizar fechas temporales cuando cambian las fechas del filtro
  // (mismo comportamiento que DashboardMetricasML).
  useEffect(() => {
    setFechaTemporal({ desde: fechaDesde, hasta: fechaHasta });
  }, [fechaDesde, fechaHasta]);

  const aplicarFiltroRapido = (filtro) => {
    const rango = calcularRangoPreset(filtro);
    if (!rango) return;
    setMostrarDropdown(false);
    onChange({ desde: rango.desde, hasta: rango.hasta, filtro });
  };

  // A range whose end precedes its start matches NOTHING, and the screen
  // would read as "no hay ventas" -- indistinguishable from a real empty
  // result. Refusing to apply it keeps the previous range and says why,
  // instead of handing the operator a silent zero.
  const rangoIncompleto = !fechaTemporal.desde || !fechaTemporal.hasta;
  const rangoInvertido = Boolean(
    fechaTemporal.desde && fechaTemporal.hasta && fechaTemporal.desde > fechaTemporal.hasta
  );

  const aplicarFechaPersonalizada = () => {
    // An EMPTY range is not "no filter", it is a filter that says nothing
    // -- and applying it marks the control active while CLEARING whatever
    // the page had (in VentasML, the month filter, since the two are the
    // same axis). Pressing Aplicar on a blank dropdown must do nothing,
    // not quietly throw away the operator's current filter.
    if (rangoIncompleto || rangoInvertido) return;
    setMostrarDropdown(false);
    onChange({ desde: fechaTemporal.desde, hasta: fechaTemporal.hasta, filtro: 'custom' });
  };

  return (
    <div className={styles.filtrosRapidos}>
      <button
        type="button"
        onClick={() => setMostrarDropdown((prev) => !prev)}
        className={`${styles.btnFiltroRapido} ${styles.btnCalendar}`}
        title="Seleccionar rango personalizado"
      >
        <Calendar size={16} />
      </button>

      {PRESETS.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          onClick={() => aplicarFiltroRapido(key)}
          className={`${styles.btnFiltroRapido} ${filtroActivo === key ? styles.activo : ''}`}
        >
          {label}
        </button>
      ))}

      {mostrarDropdown && (
        <>
          <div className={styles.dropdownOverlay} onClick={() => setMostrarDropdown(false)} />
          <div className={styles.dropdownFecha}>
            <div className={styles.dropdownFechaContent}>
              {/* `htmlFor`/`id`, not a bare <label>: unassociated, a screen
                  reader announces two unnamed date fields. `useId` because
                  two instances of this filter on one page would otherwise
                  share ids and the second label would point at the first
                  input. */}
              <div className={styles.dropdownFechaField}>
                <label htmlFor={`${idBase}-desde`}>Desde</label>
                <input
                  id={`${idBase}-desde`}
                  type="date"
                  value={fechaTemporal.desde}
                  onChange={(e) => setFechaTemporal({ ...fechaTemporal, desde: e.target.value })}
                  className={styles.dropdownDateInput}
                />
              </div>
              <div className={styles.dropdownFechaField}>
                <label htmlFor={`${idBase}-hasta`}>Hasta</label>
                <input
                  id={`${idBase}-hasta`}
                  type="date"
                  value={fechaTemporal.hasta}
                  onChange={(e) => setFechaTemporal({ ...fechaTemporal, hasta: e.target.value })}
                  className={styles.dropdownDateInput}
                />
              </div>
              {rangoInvertido && (
                <p className={styles.rangoInvertido} role="alert">
                  La fecha «desde» es posterior a la «hasta».
                </p>
              )}
              {/* `type="button"`: inside a form, a bare button submits it. */}
              <button
                type="button"
                onClick={aplicarFechaPersonalizada}
                disabled={rangoIncompleto || rangoInvertido}
                className="btn-tesla outline-subtle-primary sm"
              >
                Aplicar
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
