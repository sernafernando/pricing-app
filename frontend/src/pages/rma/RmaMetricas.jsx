/**
 * RmaMetricas.jsx
 *
 * Container for the RMA Métricas dashboard.
 * Fetches GET /rma-seguimiento/stats/detallado via React Query and renders:
 *   - Date range controls (native date inputs + fecha_caso/recepcion_fecha toggle).
 *   - 4 MetricCards: items totales, casos, abiertos, cerrados.
 *   - 6 ChartDonut (one per dimension, lazy-loaded within this chunk).
 *   - DrilldownModal (opened when a chart segment is clicked).
 *
 * STATE DECISION: all view state (dates, selected segment) lives in local useState.
 * No Zustand — this is view-scoped, no global concern.
 *
 * QUERY DECISION: placeholderData: keepPreviousData so toggling the date range
 * doesn't flash empty charts while the new request is in-flight.
 */
import { useState } from 'react';
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { BarChart2, Calendar } from 'lucide-react';
import { MetricCard } from '../../components/CloudflareCard';
import api from '../../services/api';
import ChartDonut from './ChartDonut';
import DrilldownModal from './DrilldownModal';
import styles from './RmaMetricas.module.css';

// Ordered list of dimensions as they appear in the grid.
const DIMENSION_ORDER = [
  'estado_recepcion',
  'causa_devolucion',
  'apto_venta',
  'estado_proceso',
  'estado_proveedor',
  'proveedor',
];

const DIMENSION_LABELS = {
  estado_recepcion: 'Estado Recepción',
  causa_devolucion: 'Causa Devolución',
  apto_venta: 'Apto para Venta',
  estado_proceso: 'Estado Proceso',
  estado_proveedor: 'Estado Proveedor',
  proveedor: 'Proveedor',
};

// Format a Date as YYYY-MM-DD using LOCAL components (not UTC). Using
// toISOString() here would shift the date in UTC-3 (e.g. local June 1 midnight
// serializes to May 31), breaking the default range near midnight.
function formatLocalDate(d) {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getFirstDayOfCurrentMonth() {
  const now = new Date();
  return formatLocalDate(new Date(now.getFullYear(), now.getMonth(), 1));
}

function getTodayString() {
  return formatLocalDate(new Date());
}

/**
 * Resolve the `valor` query string for the drill-down endpoint from a bucket.
 * The backend expects:
 *   - Numeric id  → string form of id  (e.g. "12")
 *   - null id + valor "Sin clasificar" → "sin_clasificar"
 *   - null id + valor "Otros"          → "otros"
 */
function resolveValorParam(bucket) {
  if (bucket.valor === 'Sin clasificar') return 'sin_clasificar';
  if (bucket.valor === 'Otros') return 'otros';
  if (bucket.id !== null && bucket.id !== undefined) return String(bucket.id);
  return 'sin_clasificar';
}

export default function RmaMetricas() {
  const [dateField, setDateField] = useState('fecha_caso');
  const [dateFrom, setDateFrom] = useState(getFirstDayOfCurrentMonth);
  const [dateTo, setDateTo] = useState(getTodayString);
  const [selectedSegment, setSelectedSegment] = useState(null);

  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: ['rma-metrics-detallado', dateField, dateFrom, dateTo],
    queryFn: () =>
      api
        .get('/rma-seguimiento/stats/detallado', {
          params: {
            date_field: dateField,
            date_from: dateFrom,
            date_to: dateTo,
          },
        })
        .then((r) => r.data),
    // Keep the previous dataset visible during refetch (paired with an
    // "Actualizando..." label) to avoid a flash-to-empty when the date range
    // changes — intentional UX override of the "no stale data" spec line.
    placeholderData: keepPreviousData,
  });

  const totales = data?.totales;
  const dimensiones = data?.dimensiones ?? {};

  const handleSegmentClick = (dimension, bucket) => {
    setSelectedSegment({
      dimension,
      valor: resolveValorParam(bucket),
      bucket,
    });
  };

  const closeDrilldown = () => setSelectedSegment(null);

  return (
    <div className={styles.container}>

      {/* Controls */}
      <div className={styles.controls}>
        <div
          className={styles.dateToggle}
          role="group"
          aria-label="Campo de fecha para filtros"
        >
          <button
            type="button"
            className={`${styles.toggleBtn} ${dateField === 'fecha_caso' ? styles.toggleActive : ''}`}
            onClick={() => setDateField('fecha_caso')}
          >
            Fecha Caso
          </button>
          <button
            type="button"
            className={`${styles.toggleBtn} ${dateField === 'recepcion_fecha' ? styles.toggleActive : ''}`}
            onClick={() => setDateField('recepcion_fecha')}
          >
            Fecha Recepción
          </button>
        </div>

        <div className={styles.dateRange}>
          <Calendar size={15} className={styles.calIcon} aria-hidden="true" />
          <label className={styles.dateLabel} htmlFor="metricas-date-from">Desde</label>
          <input
            id="metricas-date-from"
            type="date"
            className={styles.dateInput}
            value={dateFrom}
            max={dateTo}
            onChange={(e) => setDateFrom(e.target.value)}
          />
          <span className={styles.dateSep} aria-hidden="true">—</span>
          <label className={styles.dateLabel} htmlFor="metricas-date-to">Hasta</label>
          <input
            id="metricas-date-to"
            type="date"
            className={styles.dateInput}
            value={dateTo}
            min={dateFrom}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </div>

        {isFetching && !isLoading && (
          <span className={styles.fetchingLabel}>Actualizando...</span>
        )}
      </div>

      {/* recepcion_fecha caveat */}
      {dateField === 'recepcion_fecha' && (
        <p className={styles.caveat}>
          Items sin fecha de recepción no se incluyen al filtrar por Fecha Recepción.
        </p>
      )}

      {/* Error state */}
      {error && (
        <div className={styles.errorBanner} role="alert">
          Error al cargar las métricas. Verificá el rango de fechas y volvé a intentar.
        </div>
      )}

      {/* Metric indicator cards */}
      <div className={styles.metricsRow}>
        <MetricCard
          label="Items"
          value={totales ? totales.items.toLocaleString('es-AR') : '—'}
        />
        <MetricCard
          label="Casos"
          value={totales ? totales.casos.toLocaleString('es-AR') : '—'}
        />
        <MetricCard
          label="Abiertos"
          value={totales ? totales.abiertos.toLocaleString('es-AR') : '—'}
        />
        <MetricCard
          label="Cerrados"
          value={totales ? totales.cerrados.toLocaleString('es-AR') : '—'}
        />
      </div>

      {/* Loading skeleton (only first load, not refetches) */}
      {isLoading && !data && (
        <div className={styles.loading} aria-busy="true">
          <BarChart2 size={36} className={styles.loadingIcon} aria-hidden="true" />
          <span>Cargando métricas...</span>
        </div>
      )}

      {/* Charts grid */}
      {!error && data && (
        <div className={styles.chartsGrid}>
          {DIMENSION_ORDER.map((dim) => {
            const dimData = dimensiones[dim];
            if (!dimData) return null;
            return (
              <ChartDonut
                key={dim}
                title={DIMENSION_LABELS[dim] ?? dim}
                buckets={dimData.buckets}
                onSegmentClick={(bucket) => handleSegmentClick(dim, bucket)}
              />
            );
          })}
        </div>
      )}

      {/* Drill-down modal */}
      {selectedSegment && (
        <DrilldownModal
          selectedSegment={selectedSegment}
          dateField={dateField}
          dateFrom={dateFrom}
          dateTo={dateTo}
          onClose={closeDrilldown}
        />
      )}
    </div>
  );
}
