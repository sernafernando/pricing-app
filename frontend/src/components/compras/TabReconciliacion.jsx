import { useCallback, useEffect, useState } from 'react';
import { Play, CheckCircle, AlertCircle, TrendingUp, X, Inbox } from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import useCCProveedor from '../../hooks/useCCProveedor';
import DataTable from './_shared/DataTable';
import LoadingBlock from './_shared/LoadingBlock';
import FiltersBar from './_shared/FiltersBar';
import styles from './TabReconciliacion.module.css';

const COLUMNS = [
  { key: 'fecha', label: 'Fecha', width: '110px' },
  { key: 'proveedor', label: 'Proveedor' },
  { key: 'moneda', label: 'Mon.', align: 'center', width: '60px' },
  { key: 'libro_mayor', label: 'Libro mayor', align: 'right', width: '160px' },
  { key: 'snapshot', label: 'Snapshot', align: 'right', width: '160px' },
  { key: 'diferencia', label: 'Diferencia', align: 'right', width: '160px' },
  { key: 'tolerancia', label: 'Tolerancia', align: 'right', width: '110px' },
  { key: 'estado', label: 'Estado', width: '110px' },
];

const formatMoneda = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const formatDate = (isoStr) => {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    return d.toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return isoStr;
  }
};

export default function TabReconciliacion() {
  const { tienePermiso } = usePermisos();
  const canForzar = tienePermiso('administracion.gestionar_cuentas_corrientes');

  // IMPORTANTE: desestructuramos las funciones del hook (están memoizadas con
  // useCallback y tienen referencia estable). Si dependiéramos del objeto `ccApi`
  // completo, cada render crearía un objeto nuevo → useEffect en loop infinito.
  const {
    listarReconciliaciones,
    obtenerMetricas,
    forzarReconciliacion,
    loading: ccLoading,
    error: ccError,
  } = useCCProveedor();

  const [logs, setLogs] = useState([]);
  const [metricas, setMetricas] = useState(null);

  const [filtroDesde, setFiltroDesde] = useState('');
  const [filtroHasta, setFiltroHasta] = useState('');
  const [soloDivergencias, setSoloDivergencias] = useState(false);

  const [forzando, setForzando] = useState(false);
  const [forzarError, setForzarError] = useState(null);
  const [forzarResult, setForzarResult] = useState(null);
  const [confirmForzar, setConfirmForzar] = useState(false);

  const fetchLogs = useCallback(async () => {
    const params = {};
    if (filtroDesde) params.fecha_desde = filtroDesde;
    if (filtroHasta) params.fecha_hasta = filtroHasta;
    if (soloDivergencias) params.estado = 'divergencia';
    try {
      const data = await listarReconciliaciones(params);
      setLogs(data || []);
    } catch {
      setLogs([]);
    }
  }, [listarReconciliaciones, filtroDesde, filtroHasta, soloDivergencias]);

  const fetchMetricas = useCallback(async () => {
    try {
      const data = await obtenerMetricas();
      setMetricas(data);
    } catch {
      setMetricas(null);
    }
  }, [obtenerMetricas]);

  useEffect(() => {
    fetchMetricas();
  }, [fetchMetricas]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const handleForzar = async () => {
    setForzando(true);
    setForzarError(null);
    setForzarResult(null);
    try {
      const resultado = await forzarReconciliacion();
      setForzarResult(resultado);
      setConfirmForzar(false);
      fetchLogs();
      fetchMetricas();
    } catch (err) {
      setForzarError(err.response?.data?.detail || 'Error al forzar reconciliación.');
    } finally {
      setForzando(false);
    }
  };

  const diasConsecutivos = metricas?.dias_consecutivos_sin_divergencia || 0;
  const cobertura = metricas?.cobertura_porcentaje || 0;
  const progresoDias = Math.min(100, (diasConsecutivos / 30) * 100);
  const progresoCobertura = Math.min(100, cobertura);

  return (
    <div className={styles.container}>
      {/* Métricas */}
      <div className={styles.metricasGrid}>
        <div className={styles.metricCard}>
          <div className={styles.metricHeader}>
            <TrendingUp size={14} />
            <span>Días consecutivos sin divergencia</span>
          </div>
          <div className={styles.metricValue}>
            {diasConsecutivos}
            <span className={styles.metricTarget}> / 30</span>
          </div>
          <div className={styles.progressBar}>
            <div className={styles.progressFill} style={{ width: `${progresoDias}%` }} />
          </div>
        </div>
        <div className={styles.metricCard}>
          <div className={styles.metricHeader}>
            <TrendingUp size={14} />
            <span>Cobertura proveedores (30d/90d)</span>
          </div>
          <div className={styles.metricValue}>
            {cobertura.toFixed(1)}%
            <span className={styles.metricTarget}> / 80%</span>
          </div>
          <div className={styles.progressBar}>
            <div
              className={styles.progressFill}
              style={{ width: `${progresoCobertura}%` }}
            />
          </div>
        </div>
        <div className={styles.metricCard}>
          <div className={styles.metricHeader}>
            <span>Criterio deprecación snapshot</span>
          </div>
          <div className={styles.criterioList}>
            <div>
              {metricas?.criterio_deprecacion?.dias_30_sin_divergencia ? (
                <CheckCircle size={14} className={styles.iconOk} />
              ) : (
                <AlertCircle size={14} className={styles.iconPending} />
              )}
              <span>30 días sin divergencia</span>
            </div>
            <div>
              {metricas?.criterio_deprecacion?.cobertura_80_porciento ? (
                <CheckCircle size={14} className={styles.iconOk} />
              ) : (
                <AlertCircle size={14} className={styles.iconPending} />
              )}
              <span>Cobertura ≥ 80%</span>
            </div>
            <div>
              {metricas?.criterio_deprecacion?.aprobacion_usuarios_clave ? (
                <CheckCircle size={14} className={styles.iconOk} />
              ) : (
                <AlertCircle size={14} className={styles.iconPending} />
              )}
              <span>Aprobación usuarios clave (manual)</span>
            </div>
          </div>
        </div>
      </div>

      {/* Filters + acción primaria */}
      <FiltersBar
        actions={
          canForzar && (
            <button
              className={styles.btnPrimary}
              onClick={() => setConfirmForzar(true)}
              disabled={forzando}
            >
              <Play size={14} /> Forzar reconciliación
            </button>
          )
        }
      >
        <input
          type="date"
          className={styles.input}
          value={filtroDesde}
          onChange={(e) => setFiltroDesde(e.target.value)}
          title="Desde"
          aria-label="Desde"
        />
        <input
          type="date"
          className={styles.input}
          value={filtroHasta}
          onChange={(e) => setFiltroHasta(e.target.value)}
          title="Hasta"
          aria-label="Hasta"
        />
        <label className={styles.checkboxLabel}>
          <input
            type="checkbox"
            checked={soloDivergencias}
            onChange={(e) => setSoloDivergencias(e.target.checked)}
          />
          <span>Solo divergencias</span>
        </label>
      </FiltersBar>

      {forzarError && <div className={styles.errorBanner}>{forzarError}</div>}
      {forzarResult && (
        <div className={styles.successBanner}>
          Reconciliación ejecutada: {forzarResult.proveedores_procesados || 0} proveedores,{' '}
          {forzarResult.divergencias || 0} divergencias,{' '}
          {forzarResult.alertas_creadas || 0} alertas creadas.
        </div>
      )}

      {ccError && <div className={styles.errorBanner}>{ccError}</div>}

      {/* Tabla logs */}
      {ccLoading && logs.length === 0 ? (
        <LoadingBlock text="Cargando reconciliaciones…" />
      ) : (
        <DataTable
          columns={COLUMNS}
          rows={logs}
          renderCell={(log, col) => {
            switch (col.key) {
              case 'fecha':
                return <span className={styles.tdSecondary}>{formatDate(log.fecha_corrida)}</span>;
              case 'proveedor':
                return log.proveedor_nombre || `#${log.proveedor_id}`;
              case 'moneda':
                return log.moneda;
              case 'libro_mayor':
                return formatMoneda(log.saldo_libro_mayor, log.moneda);
              case 'snapshot':
                return formatMoneda(log.saldo_snapshot, log.moneda);
              case 'diferencia':
                return formatMoneda(log.diferencia, log.moneda);
              case 'tolerancia':
                return formatMoneda(log.tolerancia_aplicada, log.moneda);
              case 'estado':
                return (
                  <span
                    className={log.estado === 'ok' ? styles.badgeOk : styles.badgeDivergencia}
                  >
                    {log.estado}
                  </span>
                );
              default:
                return null;
            }
          }}
          empty={{
            icon: <Inbox size={28} strokeWidth={1.5} />,
            title: 'Sin corridas de reconciliación en este periodo.',
          }}
          minWidth="1100px"
        />
      )}

      {/* Modal confirmación forzar */}
      {confirmForzar && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>Forzar reconciliación</span>
              <button
                className={styles.modalCloseBtn}
                onClick={() => setConfirmForzar(false)}
                aria-label="Cerrar"
                type="button"
              >
                <X size={18} />
              </button>
            </div>
            <p className={styles.confirmMessage}>
              Esto ejecuta el cron de reconciliación para el día de hoy comparando libro
              mayor vs snapshot ERP. Puede tardar algunos segundos. ¿Continuar?
            </p>
            <div className={styles.formActions}>
              <button
                type="button"
                className={styles.btnSecondary}
                onClick={() => setConfirmForzar(false)}
                disabled={forzando}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnPrimary}
                onClick={handleForzar}
                disabled={forzando}
              >
                {forzando ? 'Ejecutando...' : 'Sí, forzar ahora'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
