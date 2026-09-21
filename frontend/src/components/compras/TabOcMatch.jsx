import { useEffect, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Inbox,
  RefreshCw,
} from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import useOcMatch from '../../hooks/useOcMatch';
import DataTable from './_shared/DataTable';
import FiltersBar from './_shared/FiltersBar';
import LoadingBlock from './_shared/LoadingBlock';
import styles from './TabOcMatch.module.css';

const PAGE_SIZE = 50;

const STATUS_FILTERS = [
  { value: '', label: 'Activos (sin omitidos)' },
  { value: 'queued', label: 'En cola' },
  { value: 'running', label: 'Procesando' },
  { value: 'done', label: 'Listo' },
  { value: 'error', label: 'Error' },
  { value: 'skipped', label: 'Omitidos' },
];

const STATUS_LABEL = {
  queued: 'En cola',
  running: 'Procesando',
  done: 'Listo',
  error: 'Error',
  skipped: 'Omitido',
};

const STATUS_CLASS = {
  queued: 'badgeQueued',
  running: 'badgeRunning',
  done: 'badgeDone',
  error: 'badgeError',
  skipped: 'badgeSkipped',
};

const PHASE_LABEL = {
  extracting: 'Extrayendo',
  matching: 'Matcheando',
  excel: 'Excel',
};

const COLUMNS = [
  { key: 'id', label: 'Job', width: '72px' },
  { key: 'pedido_numero', label: 'Pedido', width: '160px' },
  { key: 'attachment_id', label: 'Adjunto', width: '84px' },
  { key: 'status', label: 'Estado', width: '120px' },
  { key: 'created_at', label: 'Creado', width: '148px' },
  { key: 'error_message', label: 'Error' },
];

const RENGLON_COLUMNS = [
  { key: 'indice', label: '#', width: '40px' },
  { key: 'ean', label: 'EAN', width: '128px' },
  { key: 'descripcion', label: 'Descripción', width: '180px' },
  { key: 'cantidad', label: 'Cantidad', width: '72px', align: 'right' },
  { key: 'precio_unitario', label: 'P Unit', width: '80px', align: 'right' },
  { key: 'moneda', label: 'Moneda', width: '64px' },
  { key: 'match_estado', label: 'Match', width: '88px' },
  { key: 'confianza', label: 'Confianza', width: '88px' },
  { key: 'item_id', label: 'Item', width: '72px' },
];

function canRetryJob(job, puedeGestionar) {
  return Boolean(puedeGestionar && job && (job.retryable || job.status === 'error'));
}

function formatDateTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('es-AR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    return iso;
  }
}

const formatCantidad = (v) => {
  if (v == null || v === '') return '—';
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : n.toLocaleString('es-AR', { maximumFractionDigits: 2 });
};

const formatPrecioUnitario = (v) => {
  if (v == null || v === '') return '—';
  const n = Number(v);
  return Number.isNaN(n)
    ? String(v)
    : n.toLocaleString('es-AR', {
        minimumFractionDigits: 4,
        maximumFractionDigits: 4,
      });
};

function StatusBadge({ status, progressPhase }) {
  const cls = STATUS_CLASS[status] || 'badgeSkipped';
  const phaseLabel = status === 'running' ? PHASE_LABEL[progressPhase] : null;
  return (
    <span className={styles.statusCell}>
      <span className={`${styles.badge} ${styles[cls]}`}>
        {STATUS_LABEL[status] || status}
      </span>
      {phaseLabel ? <span className={styles.phaseSubtitle}>{phaseLabel}</span> : null}
    </span>
  );
}

const CONFIANZA_CLASS = {
  alta: 'confianzaAlta',
  media: 'confianzaMedia',
  baja: 'confianzaBaja',
};

function ConfianzaBadge({ confianza, motivo }) {
  if (!confianza) return '—';
  const key = String(confianza).toLowerCase();
  const cls = CONFIANZA_CLASS[key] || 'confianzaBaja';
  return (
    <span className={`${styles.badge} ${styles[cls]}`} title={motivo || undefined}>
      {key}
    </span>
  );
}

export default function TabOcMatch() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('administracion.gestionar_ordenes_compra');

  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);

  const {
    jobs,
    total,
    selected,
    selectedId,
    setSelectedId,
    loading,
    error,
    refresh,
    retry,
    downloadExcel,
  } = useOcMatch({ status, page, pageSize: PAGE_SIZE });

  useEffect(() => {
    setPage(1);
  }, [status]);

  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);

  const handleRetry = async () => {
    if (!selected) return;
    setActionError(null);
    setBusy(true);
    try {
      await retry(selected.id);
    } catch (err) {
      const msg = err.response?.data?.detail;
      setActionError(typeof msg === 'string' ? msg : 'No se pudo reintentar el job.');
    } finally {
      setBusy(false);
    }
  };

  const handleDownload = async () => {
    if (!selected) return;
    setActionError(null);
    setBusy(true);
    try {
      await downloadExcel(selected.id);
    } catch (err) {
      const msg = err.response?.data?.detail;
      setActionError(typeof msg === 'string' ? msg : 'No se pudo descargar el Excel.');
    } finally {
      setBusy(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil((total || 0) / PAGE_SIZE));
  const showExcel = Boolean(selected?.excel_rel_path || selected?.status === 'done');
  const showRetry = canRetryJob(selected, puedeGestionar);

  return (
    <div className={styles.container}>
      <FiltersBar
        actions={
          <button type="button" className={styles.btnRefresh} onClick={refresh} aria-label="Actualizar">
            <RefreshCw size={14} />
            Actualizar
          </button>
        }
      >
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Estado</span>
          <select
            className={styles.select}
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            aria-label="Filtrar por estado"
          >
            {STATUS_FILTERS.map((opt) => (
              <option key={opt.value || 'default'} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
      </FiltersBar>

      {error && <div className={styles.errorBanner}>{error}</div>}
      {actionError && <div className={styles.errorBanner}>{actionError}</div>}

      <div className={styles.layout}>
        <div className={styles.listPane}>
          {loading && jobs.length === 0 ? (
            <LoadingBlock text="Cargando jobs de OC Match…" />
          ) : (
            <>
              <DataTable
                columns={COLUMNS}
                rows={jobs}
                onRowClick={(row) => setSelectedId(row.id)}
                minWidth="640px"
                empty={{
                  icon: <Inbox size={28} strokeWidth={1.5} />,
                  title: 'No hay jobs de OC Match.',
                  subtitle: 'Se crean al subir un PDF o imagen a un pedido.',
                }}
                renderCell={(job, col) => {
                  switch (col.key) {
                    case 'id':
                      return (
                        <span className={job.id === selectedId ? styles.selectedId : styles.tdMono}>
                          #{job.id}
                        </span>
                      );
                    case 'pedido_numero':
                      return <span className={styles.tdMono}>{job.pedido_numero || '—'}</span>;
                    case 'attachment_id':
                      return <span className={styles.tdMono}>{job.attachment_id}</span>;
                    case 'status':
                      return <StatusBadge status={job.status} progressPhase={job.progress_phase} />;
                    case 'created_at':
                      return <span className={styles.tdSecondary}>{formatDateTime(job.created_at)}</span>;
                    case 'error_message':
                      return (
                        <span className={styles.tdError} title={job.error_message || ''}>
                          {job.error_message || '—'}
                        </span>
                      );
                    default:
                      return null;
                  }
                }}
              />
              {totalPages > 1 && (
                <div className={styles.pagination}>
                  <span>
                    {total} jobs — Página {page} de {totalPages}
                  </span>
                  <div className={styles.paginationBtns}>
                    <button
                      type="button"
                      className={styles.pageBtn}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page === 1}
                      aria-label="Página anterior"
                    >
                      <ChevronLeft size={14} />
                    </button>
                    <button
                      type="button"
                      className={styles.pageBtn}
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      disabled={page === totalPages}
                      aria-label="Página siguiente"
                    >
                      <ChevronRight size={14} />
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {selected && (
          <div className={styles.detailBody}>
            <div className={styles.detailHeader}>
              <h2 className={styles.detailTitle}>Job #{selected.id}</h2>
              <StatusBadge status={selected.status} progressPhase={selected.progress_phase} />
            </div>
            <dl className={styles.meta}>
              <div>
                <dt>Pedido</dt>
                <dd>{selected.pedido_numero || '—'}</dd>
              </div>
              <div>
                <dt>Adjunto</dt>
                <dd>{selected.attachment_id}</dd>
              </div>
            </dl>
            {selected.error_message && (
              <p className={styles.detailError}>{selected.error_message}</p>
            )}
            <div className={styles.actions}>
              {showExcel && (
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={handleDownload}
                  disabled={busy}
                >
                  <Download size={14} />
                  Descargar Excel
                </button>
              )}
              {showRetry && (
                <button
                  type="button"
                  className={styles.btnPrimary}
                  onClick={handleRetry}
                  disabled={busy}
                >
                  <RefreshCw size={14} />
                  Reintentar
                </button>
              )}
            </div>
            <h3 className={styles.sectionTitle}>Renglones</h3>
            <DataTable
              columns={RENGLON_COLUMNS}
              rows={(selected.renglones || []).map((r) => ({ ...r, id: r.id ?? r.indice }))}
              minWidth="820px"
              empty={{
                icon: <Inbox size={20} strokeWidth={1.5} />,
                title: 'Sin renglones todavía.',
              }}
              renderCell={(row, col) => {
                if (col.key === 'confianza') {
                  return <ConfianzaBadge confianza={row.confianza} motivo={row.motivo} />;
                }
                if (col.key === 'ean') {
                  const value = row.ean;
                  return (
                    <span className={styles.tdMono}>{value == null || value === '' ? '—' : value}</span>
                  );
                }
                if (col.key === 'descripcion') {
                  const full = row.descripcion == null || row.descripcion === '' ? '' : String(row.descripcion);
                  return (
                    <span className={styles.tdTruncate} title={full}>
                      {full || '—'}
                    </span>
                  );
                }
                if (col.key === 'cantidad') {
                  return formatCantidad(row.cantidad);
                }
                if (col.key === 'precio_unitario') {
                  return formatPrecioUnitario(row.precio_unitario);
                }
                const value = row[col.key];
                if (value == null || value === '') return '—';
                return String(value);
              }}
            />
            <h3 className={styles.sectionTitle}>Acta</h3>
            <pre className={styles.acta}>{selected.acta || '—'}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
