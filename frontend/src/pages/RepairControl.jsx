import { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import { publicacionRepairAPI } from '../services/api';
import { TableShell, StatusPill, Pagination } from '../components/kit';
import styles from './RepairControl.module.css';

const STATUS_TONE = {
  success: 'success',
  partial: 'warning',
  failed: 'danger',
  running: 'info',
};

const STATUS_LABEL = {
  success: 'Correcto',
  partial: 'Parcial',
  failed: 'Falló',
  running: 'En curso',
};

const ACTION_LABEL = {
  changed: 'Cambiado',
  skipped: 'Omitido',
  error: 'Error',
};

const JOB_LABEL = { envio: 'Envío', sku: 'SKU' };

function fmtDate(v) {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' });
}

function duration(start, finish) {
  if (!start || !finish) return '—';
  const ms = new Date(finish) - new Date(start);
  if (ms < 0) return '—';
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

function fmtValue(v) {
  const s = v === undefined ? '∅' : JSON.stringify(v);
  return s.length > 60 ? `${s.slice(0, 57)}…` : s;
}

function changedKeys(before, after) {
  const b = before || {};
  const a = after || {};
  const keys = new Set([...Object.keys(b), ...Object.keys(a)]);
  return [...keys].filter((k) => JSON.stringify(b[k]) !== JSON.stringify(a[k]));
}

function compactDiff(before, after) {
  const keys = changedKeys(before, after);
  if (keys.length === 0) return 'sin cambios';
  return keys.map((k) => `${k}: ${fmtValue((before || {})[k])} → ${fmtValue((after || {})[k])}`).join('; ');
}

export default function RepairControl() {
  const runsAbort = useRef(null);
  const detailAbort = useRef(null);
  const mlaAbort = useRef(null);
  const [jobType, setJobType] = useState('');
  const [status, setStatus] = useState('');
  const [desde, setDesde] = useState('');
  const [hasta, setHasta] = useState('');
  const [mlaSearch, setMlaSearch] = useState('');
  const [mlaQuery, setMlaQuery] = useState('');

  const [runs, setRuns] = useState({ items: [], total: 0 });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [selectedRun, setSelectedRun] = useState(null);
  const [runDetail, setRunDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailPage, setDetailPage] = useState(1);
  const [detailPageSize, setDetailPageSize] = useState(50);
  const [detailFilterAction, setDetailFilterAction] = useState('');
  const [detailFilterDetail, setDetailFilterDetail] = useState('');
  const [detailError, setDetailError] = useState(null);
  const [mlaError, setMlaError] = useState(null);

  const [mlaEvents, setMlaEvents] = useState(null);
  const [mlaLoading, setMlaLoading] = useState(false);
  const [expandedEvents, setExpandedEvents] = useState(new Set());

  const loadRuns = useCallback(async () => {
    runsAbort.current?.abort();
    const controller = new AbortController();
    runsAbort.current = controller;
    setLoading(true);
    setError(null);
    try {
      const { data } = await publicacionRepairAPI.runs(
        {
          job_type: jobType || undefined,
          status: status || undefined,
          desde: desde || undefined,
          hasta: hasta || undefined,
          page,
          page_size: pageSize,
        },
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      setRuns({ items: data.items || [], total: data.total || 0 });
    } catch (err) {
      if (controller.signal.aborted || err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') return;
      setError(err?.response?.status === 403 ? 'Sin permiso para ver el control de reparación.' : 'Error al cargar las corridas.');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [jobType, status, desde, hasta, page, pageSize]);

  useEffect(() => {
    if (mlaQuery) return;
    loadRuns();
  }, [loadRuns, mlaQuery]);

  const loadRunDetail = useCallback(async (runId) => {
    detailAbort.current?.abort();
    const controller = new AbortController();
    detailAbort.current = controller;
    setDetailLoading(true);
    setDetailError(null);
    try {
      const { data } = await publicacionRepairAPI.run(
        runId,
        {
        action: detailFilterAction || undefined,
        detail: detailFilterAction ? detailFilterDetail : undefined,
          page: detailPage,
          page_size: detailPageSize,
        },
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      setRunDetail(data);
    } catch (err) {
      if (controller.signal.aborted || err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') return;
      setRunDetail(null);
      setDetailError(err?.response?.status === 403 ? 'Sin permiso.' : 'Error al cargar el detalle.');
    } finally {
      if (!controller.signal.aborted) setDetailLoading(false);
    }
  }, [detailFilterAction, detailFilterDetail, detailPage, detailPageSize]);

  useEffect(() => {
    if (selectedRun != null) loadRunDetail(selectedRun);
  }, [selectedRun, loadRunDetail]);

  const loadMla = useCallback(async (mla) => {
    mlaAbort.current?.abort();
    const controller = new AbortController();
    mlaAbort.current = controller;
    setMlaLoading(true);
    setMlaError(null);
    try {
      const { data } = await publicacionRepairAPI.eventsByMla(mla, { page: 1, page_size: 100 }, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setMlaEvents(data);
    } catch (err) {
      if (controller.signal.aborted || err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') return;
      setMlaEvents(null);
      setMlaError(err?.response?.status === 403 ? 'Sin permiso.' : 'Error al cargar los eventos del MLA.');
    } finally {
      if (!controller.signal.aborted) setMlaLoading(false);
    }
  }, []);

  const handleSearchMla = (e) => {
    e?.preventDefault?.();
    const v = mlaSearch.trim();
    setMlaQuery(v);
    if (v) loadMla(v);
    else setMlaEvents(null);
  };

  const clearMla = () => {
    setMlaSearch('');
    setMlaQuery('');
    setMlaEvents(null);
  };

  const runColumns = [
    { key: 'inicio', header: 'Inicio', width: 150, render: (r) => fmtDate(r.started_at) },
    { key: 'fin', header: 'Fin (duración)', width: 180, render: (r) => (r.finished_at ? `${fmtDate(r.finished_at)} (${duration(r.started_at, r.finished_at)})` : 'En curso') },
    { key: 'tipo', header: 'Tipo', width: 80, render: (r) => JOB_LABEL[r.job_type] || r.job_type },
    {
      key: 'estado', header: 'Estado', width: 100,
      render: (r) => <StatusPill tone={STATUS_TONE[r.status] || 'neutral'}>{STATUS_LABEL[r.status] || r.status}</StatusPill>,
    },
    { key: 'revisados', header: 'Revisados', width: 90, align: 'right', render: (r) => r.scanned },
    { key: 'cambiados', header: 'Cambiados', width: 90, align: 'right', render: (r) => r.changed },
    { key: 'omitidos', header: 'Omitidos', width: 90, align: 'right', render: (r) => r.skipped },
    { key: 'errores', header: 'Errores', width: 80, align: 'right', render: (r) => <span style={{ color: r.errors > 0 ? 'var(--cf-danger)' : undefined, fontWeight: r.errors > 0 ? 600 : undefined }}>{r.errors}</span> },
    { key: 'error', header: 'Error', width: 220, render: (r) => r.error_message || '—' },
  ];

  const eventColumns = [
    {
      key: 'mla', header: 'MLA', width: 140,
      render: (e) => (
        <Link to={`/ml-publicaciones?q=${encodeURIComponent(e.mla_id)}`} className={styles.link}>
          {e.mla_id}
        </Link>
      ),
    },
    { key: 'accion', header: 'Acción', width: 90, render: (e) => ACTION_LABEL[e.action] || e.action },
    { key: 'motivo', header: 'Motivo', width: 160, render: (e) => e.detail || '—' },
    {
      key: 'diff', header: 'Antes → Después', width: 320,
      render: (e) => {
        const open = expandedEvents.has(e.id);
        return (
          <div>
            <div>{compactDiff(e.before, e.after)}</div>
            <button
              type="button"
              className="btn-tesla ghost sm"
              onClick={() => {
                setExpandedEvents((prev) => {
                  const next = new Set(prev);
                  if (next.has(e.id)) next.delete(e.id);
                  else next.add(e.id);
                  return next;
                });
              }}
            >
              {open ? 'Ocultar JSON' : 'Ver JSON'}
            </button>
            {open && (
              <div className={styles.jsonBlock}>
                <div><strong>Antes</strong></div>
                <pre className={styles.payload}>{JSON.stringify(e.before, null, 2)}</pre>
                <div><strong>Después</strong></div>
                <pre className={styles.payload}>{JSON.stringify(e.after, null, 2)}</pre>
              </div>
            )}
          </div>
        );
      },
    },
    { key: 'hora', header: 'Hora', width: 140, render: (e) => fmtDate(e.created_at) },
  ];

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Control de reparación</h1>

      <div className={styles.filterBar}>
        <label>
          Tipo
          <select className={styles.control} value={jobType} onChange={(e) => { setJobType(e.target.value); setPage(1); }}>
            <option value="">Todos</option>
            <option value="envio">Envío</option>
            <option value="sku">SKU</option>
          </select>
        </label>
        <label>
          Estado
          <select className={styles.control} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">Todos</option>
            <option value="success">{STATUS_LABEL.success}</option>
            <option value="partial">{STATUS_LABEL.partial}</option>
            <option value="failed">{STATUS_LABEL.failed}</option>
            <option value="running">{STATUS_LABEL.running}</option>
          </select>
        </label>
        <label>
          Desde
          <input className={styles.control} type="date" value={desde} onChange={(e) => { setDesde(e.target.value); setPage(1); }} />
        </label>
        <label>
          Hasta
          <input className={styles.control} type="date" value={hasta} onChange={(e) => { setHasta(e.target.value); setPage(1); }} />
        </label>
        <form onSubmit={handleSearchMla} className={styles.searchForm}>
          <label className={styles.srOnly} htmlFor="mla-search">Buscar MLA</label>
          <Search size={14} aria-hidden="true" />
          <input
            id="mla-search"
            className={styles.control}
            type="text"
            placeholder="Buscar MLA"
            value={mlaSearch}
            onChange={(e) => setMlaSearch(e.target.value)}
          />
          <button type="submit" className="btn-tesla primary sm">Buscar</button>
          {mlaQuery && (
            <button type="button" className="btn-tesla ghost sm" onClick={clearMla}>Limpiar</button>
          )}
        </form>
        <button type="button" className="btn-tesla ghost sm" aria-label="Actualizar" title="Actualizar" onClick={() => (mlaQuery ? loadMla(mlaQuery) : loadRuns())}>
          <RefreshCw size={14} aria-hidden="true" />
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {mlaQuery ? (
        <div className={styles.section}>
          <h2 className={styles.subtitle}>Eventos de {mlaQuery}</h2>
          {mlaLoading && <div className={styles.loading}>Cargando…</div>}
          {mlaError && <div className={styles.error}>{mlaError}</div>}
          {!mlaLoading && mlaEvents && (
            <>
              <TableShell
                columns={eventColumns}
                rows={mlaEvents.events || []}
                getRowKey={(r) => r.id}
                emptyMessage="Sin eventos para este MLA"
                ariaLabel="Eventos de reparación por MLA"
              />
              <div className={styles.writes}>
                <h3 className={styles.subtitle}>Escrituras confirmadas en ML</h3>
                {(mlaEvents.ml_writes || []).length === 0 && <div className={styles.empty}>Sin escrituras</div>}
                {(mlaEvents.ml_writes || []).map((w) => (
                  <div key={w.id} className={styles.writeRow}>
                    <span className={styles.writeAction}>{w.action}</span>
                    <span className={styles.writeTime}>{fmtDate(w.created_at)}</span>
                    <pre className={styles.payload}>{JSON.stringify(w.payload, null, 2)}</pre>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      ) : (
        <div className={styles.section}>
          {loading && <div className={styles.loading}>Cargando…</div>}
          {!loading && (
            <>
              <TableShell
                columns={runColumns}
                rows={runs.items}
                getRowKey={(r) => r.id}
                getRowTone={(r) => (r.errors > 0 || r.status === 'failed' ? { marker: 'var(--cf-danger)' } : null)}
                onRowClick={(r) => {
                  if (r.id === selectedRun) {
                    setSelectedRun(null);
                    setRunDetail(null);
                  } else {
                    setDetailFilterAction('');
                    setDetailFilterDetail('');
                    setDetailPage(1);
                    setSelectedRun(r.id);
                  }
                }}
                selectedKey={selectedRun}
                emptyMessage="Sin corridas"
                ariaLabel="Corridas de reparación"
              />
              <Pagination
                total={runs.total}
                offset={(page - 1) * pageSize}
                pageSize={pageSize}
                summary={`mostrando ${runs.total === 0 ? 0 : (page - 1) * pageSize + 1}-${Math.min(page * pageSize, runs.total)} de ${runs.total} corridas`}
                onOffsetChange={(o) => setPage(Math.floor(o / pageSize) + 1)}
                onPageSizeChange={(s) => { setPageSize(s); setPage(1); }}
              />
            </>
          )}

          {selectedRun != null && (
            <div className={styles.detail}>
              <div className={styles.detailHeader}>
                <h2 className={styles.subtitle}>Corrida #{selectedRun}</h2>
                <button type="button" className="btn-tesla ghost sm" onClick={() => { setDetailFilterAction(''); setDetailFilterDetail(''); setDetailPage(1); setSelectedRun(null); setRunDetail(null); }}>
                  Cerrar
                </button>
              </div>
              {detailLoading && <div className={styles.loading}>Cargando…</div>}
              {detailError && <div className={styles.error}>{detailError}</div>}
              {!detailLoading && runDetail && (
                <>
                  <div className={styles.breakdown}>
                    {(runDetail.breakdown || []).map((b) => {
                      const detailValue = b.detail === null ? '' : (b.detail || '');
                      const active = detailFilterAction === b.action && detailFilterDetail === detailValue;
                      const label = b.detail === null ? 'sin motivo' : (b.detail || '—');
                      return (
                        <button
                          key={`${b.action}|${b.detail}`}
                          type="button"
                          className={`btn-tesla ghost sm ${active ? 'primary' : ''}`}
                          onClick={() => {
                            if (active) {
                              setDetailFilterAction('');
                              setDetailFilterDetail('');
                            } else {
                              setDetailFilterAction(b.action);
                              setDetailFilterDetail(detailValue);
                            }
                            setDetailPage(1);
                          }}
                        >
                          {(ACTION_LABEL[b.action] || b.action)} · {label} ({b.count})
                        </button>
                      );
                    })}
                    {(detailFilterAction || detailFilterDetail) && (
                      <button type="button" className="btn-tesla ghost sm" onClick={() => { setDetailFilterAction(''); setDetailFilterDetail(''); setDetailPage(1); }}>
                        Limpiar filtro
                      </button>
                    )}
                  </div>
                  <TableShell
                    columns={eventColumns}
                    rows={runDetail.events || []}
                    getRowKey={(r) => r.id}
                    emptyMessage="Sin eventos"
                    ariaLabel="Eventos de la corrida"
                  />
                  <Pagination
                    total={runDetail.total || 0}
                    offset={(detailPage - 1) * detailPageSize}
                    pageSize={detailPageSize}
                    summary={`mostrando ${runDetail.total ? (detailPage - 1) * detailPageSize + 1 : 0}-${Math.min(detailPage * detailPageSize, runDetail.total || 0)} de ${runDetail.total || 0} eventos`}
                    onOffsetChange={(o) => setDetailPage(Math.floor(o / detailPageSize) + 1)}
                    onPageSizeChange={(s) => { setDetailPageSize(s); setDetailPage(1); }}
                  />
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
