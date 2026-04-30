import { useState, useEffect, useCallback, useMemo } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI, horasExtrasApi } from '../services/api';
import {
  Clock,
  RotateCcw,
  Check,
  X,
  Eye,
  AlertTriangle,
  Bell,
  Percent,
  FileSpreadsheet,
  CheckCheck,
  Undo2,
  Trash2,
  PenLine,
} from 'lucide-react';
import styles from './RRHHHorasExtras.module.css';
import HEModalMotivo from './components/HEModalMotivo';
import HEModalAprobar from './components/HEModalAprobar';
import HEModalCompletarFichada from './components/HEModalCompletarFichada';
import HEModalRecalcular from './components/HEModalRecalcular';
import HEModalLiquidar from './components/HEModalLiquidar';
import HEModalHistorial from './components/HEModalHistorial';

// ── Constantes ───────────────────────────────────────────
const TABS = [
  { key: 'pendientes', label: 'Pendientes', estados: ['detectada', 'error_fichadas', 'pendiente_asignacion_turno'] },
  { key: 'aprobadas', label: 'Aprobadas', estados: ['aprobada'] },
  { key: 'liquidadas', label: 'Liquidadas', estados: ['liquidada'] },
  { key: 'anomalias', label: 'Anomalías', estados: ['error_fichadas'] },
  { key: 'alertas', label: 'Alertas', estados: null },
];

const PAGE_SIZE = 50;

const formatFechaISO = (dateStr) => {
  if (!dateStr) return '-';
  try {
    const d = new Date(dateStr + 'T12:00:00');
    if (Number.isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch {
    return dateStr;
  }
};

const formatTimestamp = (ts) => {
  if (!ts) return '-';
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts;
    return d.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return ts;
  }
};

export default function RRHHHorasExtras() {
  const { tienePermiso } = usePermisos();

  // Permisos puntuales
  const puedeVer = tienePermiso('rrhh.ver_horas_extras');
  const puedeGestionar = tienePermiso('rrhh.gestionar_horas_extras');
  const puedeAprobar = tienePermiso('rrhh.aprobar_horas_extras');
  const puedeLiquidar = tienePermiso('rrhh.liquidar_horas_extras');

  // ── Tab state ─────────────────────────────
  const [activeTab, setActiveTab] = useState('pendientes');

  // ── Filtros ───────────────────────────────
  const [filtroEmpleadoId, setFiltroEmpleadoId] = useState('');
  const [filtroFechaDesde, setFiltroFechaDesde] = useState('');
  const [filtroFechaHasta, setFiltroFechaHasta] = useState('');
  const [filtroTipoDia, setFiltroTipoDia] = useState('');
  const [filtroPeriodo, setFiltroPeriodo] = useState('');
  const [empleados, setEmpleados] = useState([]);

  // ── Datos ─────────────────────────────────
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Alertas (tab dedicado)
  const [alertas, setAlertas] = useState([]);
  const [alertasTotal, setAlertasTotal] = useState(0);
  const [verLeidas, setVerLeidas] = useState(false);
  const [loadingAlertas, setLoadingAlertas] = useState(false);

  // Counts para badges de tabs
  const [counts, setCounts] = useState({
    pendientes: 0,
    aprobadas: 0,
    liquidadas: 0,
    anomalias: 0,
    alertas: 0,
  });

  // Selección múltiple
  const [selectedIds, setSelectedIds] = useState([]);

  // Edición inline %
  const [editingPctId, setEditingPctId] = useState(null);
  const [editingPctValue, setEditingPctValue] = useState('');

  // ── Modal state ───────────────────────────
  const [modal, setModal] = useState(null);
  // shapes:
  //  { type: 'rechazar', target: 'individual'|'bulk', id?: number, ids?: number[] }
  //  { type: 'reabrir', id, era_liquidada }
  //  { type: 'descartar', id }
  //  { type: 'completar', id }
  //  { type: 'aprobar', id?, ids? }
  //  { type: 'detalle', id }
  //  { type: 'recalcular' }
  //  { type: 'liquidar', ids }

  // ── Empleados (para filter select) ────────
  useEffect(() => {
    if (!puedeVer) return;
    rrhhAPI
      .listarEmpleados({ page_size: 200, estado: 'activo' })
      .then(({ data }) => {
        setEmpleados(Array.isArray(data) ? data : data.items || []);
      })
      .catch(() => setEmpleados([]));
  }, [puedeVer]);

  // ── Fetch list ─────────────────────────────
  const tab = useMemo(() => TABS.find((t) => t.key === activeTab), [activeTab]);

  const fetchList = useCallback(async () => {
    if (!puedeVer || activeTab === 'alertas') return;
    setLoading(true);
    setError(null);
    setSelectedIds([]);
    try {
      const params = {
        page,
        page_size: PAGE_SIZE,
      };
      if (tab && tab.estados) {
        params.estado = tab.estados.join(',');
      }
      if (filtroEmpleadoId) params.empleado_id = filtroEmpleadoId;
      if (filtroFechaDesde) params.fecha_desde = filtroFechaDesde;
      if (filtroFechaHasta) params.fecha_hasta = filtroFechaHasta;
      if (filtroTipoDia) params.tipo_dia = filtroTipoDia;
      if (activeTab === 'liquidadas' && filtroPeriodo) params.periodo = filtroPeriodo;

      const { data } = await horasExtrasApi.list(params);
      setItems(data.items || []);
      setTotal(data.total ?? (data.items?.length || 0));
    } catch (err) {
      setError(err?.response?.data?.detail || 'Error al cargar bloques');
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [puedeVer, activeTab, page, tab, filtroEmpleadoId, filtroFechaDesde, filtroFechaHasta, filtroTipoDia, filtroPeriodo]);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  // ── Fetch alertas ──────────────────────────
  const fetchAlertas = useCallback(async () => {
    if (!puedeVer || activeTab !== 'alertas') return;
    setLoadingAlertas(true);
    setError(null);
    try {
      const { data } = await horasExtrasApi.alertasList({
        page: 1,
        page_size: PAGE_SIZE,
        solo_no_leidas: !verLeidas,
      });
      setAlertas(data.items || []);
      setAlertasTotal(data.total ?? (data.items?.length || 0));
    } catch (err) {
      setError(err?.response?.data?.detail || 'Error al cargar alertas');
      setAlertas([]);
      setAlertasTotal(0);
    } finally {
      setLoadingAlertas(false);
    }
  }, [puedeVer, activeTab, verLeidas]);

  useEffect(() => {
    fetchAlertas();
  }, [fetchAlertas]);

  // ── Fetch counts (todos los tabs) ──────────
  const fetchCounts = useCallback(async () => {
    if (!puedeVer) return;
    try {
      const [pend, apr, liq, ano, alr] = await Promise.all([
        horasExtrasApi.list({ estado: 'detectada,error_fichadas,pendiente_asignacion_turno', page: 1, page_size: 1 }).catch(() => ({ data: { total: 0 } })),
        horasExtrasApi.list({ estado: 'aprobada', page: 1, page_size: 1 }).catch(() => ({ data: { total: 0 } })),
        horasExtrasApi.list({ estado: 'liquidada', page: 1, page_size: 1 }).catch(() => ({ data: { total: 0 } })),
        horasExtrasApi.list({ estado: 'error_fichadas', page: 1, page_size: 1 }).catch(() => ({ data: { total: 0 } })),
        horasExtrasApi.alertasList({ solo_no_leidas: true, page: 1, page_size: 1 }).catch(() => ({ data: { total: 0 } })),
      ]);
      setCounts({
        pendientes: pend.data?.total || 0,
        aprobadas: apr.data?.total || 0,
        liquidadas: liq.data?.total || 0,
        anomalias: ano.data?.total || 0,
        alertas: alr.data?.total || 0,
      });
    } catch {
      // silently
    }
  }, [puedeVer]);

  useEffect(() => {
    fetchCounts();
  }, [fetchCounts]);

  // ── Refresh helper ────────────────────────
  const refresh = useCallback(() => {
    fetchList();
    fetchAlertas();
    fetchCounts();
  }, [fetchList, fetchAlertas, fetchCounts]);

  // ── Permission gate ───────────────────────
  if (!puedeVer) {
    return (
      <div className={styles.container}>
        <div className={styles.deniedMsg}>
          No tenés permiso para ver el módulo de Horas Extras.
        </div>
      </div>
    );
  }

  // ── Selección bulk ────────────────────────
  const toggleSelect = (id) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const toggleSelectAll = () => {
    if (selectedIds.length === items.length && items.length > 0) {
      setSelectedIds([]);
    } else {
      setSelectedIds(items.map((it) => it.id));
    }
  };

  // ── Actions ────────────────────────────────
  const handleAprobarIndividual = async (id, body = {}) => {
    await horasExtrasApi.aprobar(id, body);
    refresh();
  };

  const handleRechazarIndividual = async (id, motivo) => {
    await horasExtrasApi.rechazar(id, { motivo });
    refresh();
  };

  const handleReabrir = async (id, motivo) => {
    await horasExtrasApi.reabrir(id, { motivo });
    refresh();
  };

  const handleBulkAprobar = async (body) => {
    await horasExtrasApi.bulkAprobar({ ids: selectedIds, ...body });
    setSelectedIds([]);
    refresh();
  };

  const handleBulkRechazar = async (motivo) => {
    await horasExtrasApi.bulkRechazar({ ids: selectedIds, motivo });
    setSelectedIds([]);
    refresh();
  };

  const handleCompletarFichada = async (id, body) => {
    await horasExtrasApi.completarFichada(id, body);
    refresh();
  };

  const handleDescartarDia = async (id, motivo) => {
    await horasExtrasApi.descartarDia(id, { motivo });
    refresh();
  };

  const handleRecalcular = async (body) => {
    const { data } = await horasExtrasApi.recalcular(body);
    refresh();
    return data;
  };

  const handleLiquidar = async (body) => {
    await horasExtrasApi.liquidar(body);
    setSelectedIds([]);
    refresh();
  };

  const handleAlertaMarcarLeida = async (id) => {
    try {
      await horasExtrasApi.alertaMarcarLeida(id);
      fetchAlertas();
      fetchCounts();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Error al marcar la alerta');
    }
  };

  // Edición inline %
  const startEditPct = (it) => {
    setEditingPctId(it.id);
    setEditingPctValue(String(it.porcentaje_recargo ?? ''));
  };

  const commitEditPct = async (id) => {
    const num = editingPctValue === '' ? null : Number(editingPctValue);
    if (num !== null && (Number.isNaN(num) || num < 0 || num > 500)) {
      setEditingPctId(null);
      return;
    }
    try {
      await horasExtrasApi.update(id, { porcentaje_recargo: num });
      setEditingPctId(null);
      refresh();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Error al guardar el porcentaje');
      setEditingPctId(null);
    }
  };

  // Export Excel
  const handleExportar = async () => {
    if (!filtroPeriodo || !/^\d{6}$/.test(filtroPeriodo)) {
      setError('Seleccioná un período válido (YYYYMM) para exportar.');
      return;
    }
    try {
      const res = await horasExtrasApi.exportarXlsx({ periodo: filtroPeriodo });
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `horas_extras_${filtroPeriodo}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Error al exportar Excel');
    }
  };

  // ── Render helpers ─────────────────────────
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const showBulkBar = selectedIds.length > 0 && (activeTab === 'pendientes' || activeTab === 'aprobadas');

  // ── Render ────────────────────────────────
  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Clock size={24} />
          <h1>RRHH › Horas Extras</h1>
        </div>
        <div className={styles.headerActions}>
          {puedeGestionar && (
            <button
              className={styles.btnPrimary}
              onClick={() => setModal({ type: 'recalcular' })}
            >
              <RotateCcw size={14} /> Recalcular período
            </button>
          )}
          {activeTab === 'liquidadas' && filtroPeriodo && (
            <button
              className={styles.btnPrimary}
              onClick={handleExportar}
            >
              <FileSpreadsheet size={14} /> Exportar Excel
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className={styles.tabs}>
        {TABS.map((t) => {
          const isActive = activeTab === t.key;
          const count = counts[t.key];
          let badgeClass = styles.tabBadge;
          if (t.key === 'anomalias' && count > 0) badgeClass = styles.tabBadgeWarning;
          if (t.key === 'alertas' && count > 0) badgeClass = styles.tabBadgeCritical;
          return (
            <button
              key={t.key}
              className={isActive ? styles.tabActive : styles.tab}
              onClick={() => {
                setActiveTab(t.key);
                setPage(1);
                setError(null);
              }}
            >
              {t.key === 'alertas' && <Bell size={14} />}
              {t.key === 'anomalias' && <AlertTriangle size={14} />}
              {t.label}
              {count > 0 && <span className={badgeClass}>{count}</span>}
            </button>
          );
        })}
      </div>

      {/* Error */}
      {error && <div className={styles.errorMsg}>{error}</div>}

      {/* Filtros (no aplican al tab Alertas) */}
      {activeTab !== 'alertas' && (
        <div className={styles.filters}>
          <select
            className={styles.select}
            value={filtroEmpleadoId}
            onChange={(e) => { setFiltroEmpleadoId(e.target.value); setPage(1); }}
          >
            <option value="">Todos los empleados</option>
            {empleados.map((emp) => (
              <option key={emp.id} value={emp.id}>
                {emp.apellido}, {emp.nombre} ({emp.legajo})
              </option>
            ))}
          </select>

          <input
            type="date"
            className={styles.input}
            value={filtroFechaDesde}
            onChange={(e) => { setFiltroFechaDesde(e.target.value); setPage(1); }}
            placeholder="Desde"
            aria-label="Fecha desde"
          />
          <input
            type="date"
            className={styles.input}
            value={filtroFechaHasta}
            onChange={(e) => { setFiltroFechaHasta(e.target.value); setPage(1); }}
            placeholder="Hasta"
            aria-label="Fecha hasta"
          />

          {(activeTab === 'pendientes' || activeTab === 'aprobadas') && (
            <select
              className={styles.select}
              value={filtroTipoDia}
              onChange={(e) => { setFiltroTipoDia(e.target.value); setPage(1); }}
            >
              <option value="">Todos los tipos</option>
              <option value="habil_50">Hábil 50%</option>
              <option value="sabado_50">Sábado 50%</option>
              <option value="sabado_100">Sábado 100%</option>
              <option value="domingo_100">Domingo 100%</option>
              <option value="feriado_100">Feriado 100%</option>
              <option value="manual">Manual</option>
            </select>
          )}

          {activeTab === 'liquidadas' && (
            <input
              type="text"
              className={styles.input}
              value={filtroPeriodo}
              onChange={(e) => { setFiltroPeriodo(e.target.value.replace(/[^0-9]/g, '').slice(0, 6)); setPage(1); }}
              placeholder="Período YYYYMM"
              maxLength={6}
            />
          )}
        </div>
      )}

      {/* Bulk bar */}
      {showBulkBar && (
        <div className={styles.bulkBar}>
          <span className={styles.bulkCount}>
            {selectedIds.length} seleccionado{selectedIds.length === 1 ? '' : 's'}
          </span>
          {activeTab === 'pendientes' && puedeAprobar && (
            <>
              <button
                className={styles.btnApprove}
                onClick={() => setModal({ type: 'aprobar', ids: selectedIds })}
              >
                <CheckCheck size={14} /> Aprobar selección
              </button>
              <button
                className={styles.btnReject}
                onClick={() => setModal({ type: 'rechazar', target: 'bulk', ids: selectedIds })}
              >
                <X size={14} /> Rechazar selección
              </button>
            </>
          )}
          {activeTab === 'pendientes' && puedeGestionar && (
            <button
              className={styles.btnPrimary}
              onClick={() => setModal({ type: 'aprobar', ids: selectedIds })}
              title="Aprobar con override de %"
            >
              <Percent size={14} /> Cambiar % al aprobar
            </button>
          )}
          {activeTab === 'aprobadas' && puedeLiquidar && (
            <button
              className={styles.btnPrimary}
              onClick={() => setModal({ type: 'liquidar', ids: selectedIds })}
            >
              <FileSpreadsheet size={14} /> Liquidar selección
            </button>
          )}
        </div>
      )}

      {/* Toggle ver leídas (alertas) */}
      {activeTab === 'alertas' && (
        <div className={styles.filters}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-xs)', fontSize: 'var(--font-sm)', color: 'var(--cf-text-secondary)' }}>
            <input
              type="checkbox"
              checked={verLeidas}
              onChange={(e) => setVerLeidas(e.target.checked)}
            />
            Mostrar también leídas
          </label>
        </div>
      )}

      {/* Tab content */}
      {activeTab === 'alertas' ? (
        <AlertasTable
          loading={loadingAlertas}
          alertas={alertas}
          total={alertasTotal}
          puedeAprobar={puedeAprobar}
          puedeGestionar={puedeGestionar}
          onMarcarLeida={handleAlertaMarcarLeida}
          onAbrirDetalle={(heId) => setModal({ type: 'detalle', id: heId })}
          onReabrir={(heId, eraLiquidada) => setModal({ type: 'reabrir', id: heId, era_liquidada: eraLiquidada })}
        />
      ) : (
        <BloquesTable
          loading={loading}
          items={items}
          activeTab={activeTab}
          selectedIds={selectedIds}
          onToggleSelect={toggleSelect}
          onToggleSelectAll={toggleSelectAll}
          puedeAprobar={puedeAprobar}
          puedeGestionar={puedeGestionar}
          puedeLiquidar={puedeLiquidar}
          editingPctId={editingPctId}
          editingPctValue={editingPctValue}
          setEditingPctValue={setEditingPctValue}
          startEditPct={startEditPct}
          commitEditPct={commitEditPct}
          onAprobar={(id) => setModal({ type: 'aprobar', id })}
          onRechazar={(id) => setModal({ type: 'rechazar', target: 'individual', id })}
          onReabrir={(id, eraLiquidada) => setModal({ type: 'reabrir', id, era_liquidada: eraLiquidada })}
          onCompletar={(id) => setModal({ type: 'completar', id })}
          onDescartar={(id) => setModal({ type: 'descartar', id })}
          onDetalle={(id) => setModal({ type: 'detalle', id })}
        />
      )}

      {/* Pagination */}
      {activeTab !== 'alertas' && totalPages > 1 && (
        <div className={styles.pagination}>
          <button
            className={styles.btnSecondary}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            Anterior
          </button>
          <span className={styles.pageInfo}>
            Página {page} de {totalPages} ({total} bloques)
          </span>
          <button
            className={styles.btnSecondary}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
          >
            Siguiente
          </button>
        </div>
      )}

      {/* ── Modals ───────────────────────────── */}
      <HEModalAprobar
        open={modal?.type === 'aprobar'}
        bulkCount={modal?.type === 'aprobar' && modal.ids ? modal.ids.length : null}
        defaultPorcentaje={modal?.type === 'aprobar' && modal.id ? items.find((i) => i.id === modal.id)?.porcentaje_recargo : null}
        onClose={() => setModal(null)}
        onConfirm={async (body) => {
          if (modal?.ids) {
            await handleBulkAprobar(body);
          } else if (modal?.id) {
            await handleAprobarIndividual(modal.id, body);
          }
          setModal(null);
        }}
      />

      <HEModalMotivo
        open={modal?.type === 'rechazar'}
        title={modal?.target === 'bulk' ? `Rechazar ${modal.ids?.length || 0} bloques` : 'Rechazar bloque'}
        confirmLabel="Rechazar"
        confirmVariant="danger"
        placeholder="Motivo del rechazo..."
        bulkCount={modal?.target === 'bulk' ? (modal.ids?.length || 0) : null}
        onClose={() => setModal(null)}
        onConfirm={async (motivo) => {
          if (modal?.target === 'bulk') {
            await handleBulkRechazar(motivo);
          } else if (modal?.id) {
            await handleRechazarIndividual(modal.id, motivo);
          }
          setModal(null);
        }}
      />

      <HEModalMotivo
        open={modal?.type === 'reabrir'}
        title="Reabrir bloque"
        confirmLabel="Reabrir"
        confirmVariant="warning"
        placeholder="Motivo de la reapertura..."
        warning={modal?.era_liquidada ? 'Este bloque fue liquidado. Reabrirlo afecta una liquidación cerrada.' : null}
        onClose={() => setModal(null)}
        onConfirm={async (motivo) => {
          if (modal?.id) {
            await handleReabrir(modal.id, motivo);
          }
          setModal(null);
        }}
      />

      <HEModalMotivo
        open={modal?.type === 'descartar'}
        title="Descartar día"
        confirmLabel="Descartar"
        confirmVariant="warning"
        placeholder="Motivo del descarte (ej: día sin obligación de fichar)..."
        onClose={() => setModal(null)}
        onConfirm={async (motivo) => {
          if (modal?.id) {
            await handleDescartarDia(modal.id, motivo);
          }
          setModal(null);
        }}
      />

      <HEModalCompletarFichada
        open={modal?.type === 'completar'}
        heId={modal?.id || null}
        onClose={() => setModal(null)}
        onConfirm={async (id, body) => {
          await handleCompletarFichada(id, body);
          setModal(null);
        }}
      />

      <HEModalRecalcular
        open={modal?.type === 'recalcular'}
        onClose={() => setModal(null)}
        onConfirm={handleRecalcular}
      />

      <HEModalLiquidar
        open={modal?.type === 'liquidar'}
        selectedIds={modal?.ids || []}
        onClose={() => setModal(null)}
        onConfirm={async (body) => {
          await handleLiquidar(body);
          setModal(null);
        }}
      />

      <HEModalHistorial
        open={modal?.type === 'detalle'}
        heId={modal?.id || null}
        puedeGestionar={puedeGestionar}
        onClose={() => setModal(null)}
        onUpdated={refresh}
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// Subcomponente: tabla de bloques
// ─────────────────────────────────────────────────────────
function BloquesTable({
  loading,
  items,
  activeTab,
  selectedIds,
  onToggleSelect,
  onToggleSelectAll,
  puedeAprobar,
  puedeGestionar,
  editingPctId,
  editingPctValue,
  setEditingPctValue,
  startEditPct,
  commitEditPct,
  onAprobar,
  onRechazar,
  onReabrir,
  onCompletar,
  onDescartar,
  onDetalle,
}) {
  if (loading) {
    return <div className={styles.loading}>Cargando bloques...</div>;
  }
  if (items.length === 0) {
    return <div className={styles.empty}>No hay bloques para mostrar</div>;
  }

  const showCheckbox = activeTab === 'pendientes' || activeTab === 'aprobadas';
  const allSelected = showCheckbox && selectedIds.length === items.length && items.length > 0;

  return (
    <div className={styles.tableContainer}>
      <table className={styles.table}>
        <thead>
          <tr>
            {showCheckbox && (
              <th>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={onToggleSelectAll}
                  aria-label="Seleccionar todos"
                />
              </th>
            )}
            <th>Legajo</th>
            <th>Empleado</th>
            <th>Fecha</th>
            <th>Tipo día</th>
            <th>Min</th>
            <th>%</th>
            {activeTab === 'anomalias' && <th>Error</th>}
            {activeTab === 'aprobadas' && <th>Aprobado por</th>}
            {activeTab === 'aprobadas' && <th>Aprobado el</th>}
            {activeTab === 'liquidadas' && <th>Período</th>}
            {activeTab === 'liquidadas' && <th>Liquidado por</th>}
            {activeTab === 'liquidadas' && <th>Liquidado el</th>}
            <th>Estado</th>
            <th>Acciones</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const selected = selectedIds.includes(it.id);
            return (
              <tr key={it.id} className={selected ? styles.rowSelected : undefined}>
                {showCheckbox && (
                  <td>
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => onToggleSelect(it.id)}
                      aria-label={`Seleccionar bloque ${it.id}`}
                    />
                  </td>
                )}
                <td>{it.legajo || '-'}</td>
                <td>{it.empleado_nombre || `#${it.empleado_id}`}</td>
                <td>{formatFechaISO(it.fecha)}</td>
                <td>{it.tipo_dia || '-'}</td>
                <td>{it.minutos_extra ?? '-'}</td>
                <td>
                  {editingPctId === it.id ? (
                    <input
                      type="number"
                      className={styles.inputInline}
                      value={editingPctValue}
                      onChange={(e) => setEditingPctValue(e.target.value)}
                      onBlur={() => commitEditPct(it.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') commitEditPct(it.id);
                        if (e.key === 'Escape') {
                          setEditingPctValue('');
                        }
                      }}
                      min={0}
                      max={500}
                      autoFocus
                    />
                  ) : (
                    <span
                      className={styles.pctCell}
                      onClick={() => {
                        if (puedeGestionar && (it.estado === 'detectada' || it.estado === 'error_fichadas' || it.estado === 'pendiente_asignacion_turno')) {
                          startEditPct(it);
                        }
                      }}
                      style={{
                        cursor: puedeGestionar && it.estado === 'detectada' ? 'pointer' : 'default',
                      }}
                    >
                      {it.porcentaje_recargo ?? '-'}
                      <span className={styles.pctSuffix}>%</span>
                    </span>
                  )}
                </td>
                {activeTab === 'anomalias' && <td>{it.error_tipo || '-'}</td>}
                {activeTab === 'aprobadas' && <td>{it.aprobado_por_nombre || it.aprobado_por_id || '-'}</td>}
                {activeTab === 'aprobadas' && <td>{formatTimestamp(it.aprobado_at)}</td>}
                {activeTab === 'liquidadas' && <td>{it.liquidacion_periodo || '-'}</td>}
                {activeTab === 'liquidadas' && <td>{it.liquidado_por_nombre || it.liquidado_por_id || '-'}</td>}
                {activeTab === 'liquidadas' && <td>{formatTimestamp(it.liquidado_at)}</td>}
                <td>
                  <span className={styles[`estado--${it.estado}`] || styles.estadoBadge}>
                    {it.estado}
                  </span>
                </td>
                <td>
                  <div className={styles.actions}>
                    <button
                      className={styles.btnIcon}
                      onClick={() => onDetalle(it.id)}
                      title="Ver detalle"
                      aria-label="Ver detalle"
                    >
                      <Eye size={14} />
                    </button>

                    {/* Pendientes / Anomalías */}
                    {activeTab === 'pendientes' && it.estado !== 'error_fichadas' && it.estado !== 'pendiente_asignacion_turno' && puedeAprobar && (
                      <>
                        <button
                          className={styles.btnApprove}
                          onClick={() => onAprobar(it.id)}
                          title="Aprobar"
                        >
                          <Check size={14} />
                        </button>
                        <button
                          className={styles.btnReject}
                          onClick={() => onRechazar(it.id)}
                          title="Rechazar"
                        >
                          <X size={14} />
                        </button>
                      </>
                    )}

                    {/* Anomalías tab */}
                    {activeTab === 'anomalias' && (
                      <>
                        {puedeGestionar && (
                          <button
                            className={styles.btnPrimary}
                            onClick={() => onCompletar(it.id)}
                            title="Completar fichada"
                          >
                            <PenLine size={14} /> Completar
                          </button>
                        )}
                        {puedeAprobar && (
                          <button
                            className={styles.btnWarning}
                            onClick={() => onDescartar(it.id)}
                            title="Descartar día"
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </>
                    )}

                    {/* Aprobadas */}
                    {activeTab === 'aprobadas' && puedeAprobar && (
                      <button
                        className={styles.btnWarning}
                        onClick={() => onReabrir(it.id, false)}
                        title="Reabrir"
                      >
                        <Undo2 size={14} /> Reabrir
                      </button>
                    )}

                    {/* Liquidadas: NO permite reabrir desde acá (read-only). */}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// Subcomponente: tabla de alertas
// ─────────────────────────────────────────────────────────
function AlertasTable({
  loading,
  alertas,
  total,
  puedeAprobar,
  puedeGestionar,
  onMarcarLeida,
  onAbrirDetalle,
  onReabrir,
}) {
  if (loading) {
    return <div className={styles.loading}>Cargando alertas...</div>;
  }
  if (alertas.length === 0) {
    return <div className={styles.empty}>No hay alertas para mostrar</div>;
  }

  return (
    <div className={styles.tableContainer}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Severidad</th>
            <th>Tipo</th>
            <th>Mensaje</th>
            <th>Bloque</th>
            <th>Fecha</th>
            <th>Acciones</th>
          </tr>
        </thead>
        <tbody>
          {alertas.map((a) => {
            const sevClass = styles[`sev--${a.severidad}`] || styles.sevBadge;
            const esCambioTurno = a.tipo === 'liquidacion_afectada_por_cambio_turno';
            return (
              <tr key={a.id} style={a.leida ? { opacity: 0.6 } : undefined}>
                <td><span className={sevClass}>{a.severidad}</span></td>
                <td>{a.tipo}</td>
                <td>
                  {a.mensaje}
                  {esCambioTurno && (
                    <span className={styles.warningBox} style={{ marginTop: 4, padding: '2px 8px', display: 'inline-flex' }}>
                      Revisar período liquidado
                    </span>
                  )}
                </td>
                <td>
                  {a.he_id ? (
                    <button
                      className={styles.btnIcon}
                      onClick={() => onAbrirDetalle(a.he_id)}
                      title="Abrir bloque"
                    >
                      #{a.he_id}
                    </button>
                  ) : '-'}
                </td>
                <td>{formatTimestamp(a.created_at)}</td>
                <td>
                  <div className={styles.actions}>
                    {!a.leida && (puedeGestionar || puedeAprobar) && (
                      <button
                        className={styles.btnSecondary}
                        onClick={() => onMarcarLeida(a.id)}
                        title="Marcar leída"
                      >
                        <Check size={14} /> Marcar leída
                      </button>
                    )}
                    {a.he_id && a.bloque_estado === 'liquidada' && puedeAprobar && (
                      <button
                        className={styles.btnWarning}
                        onClick={() => onReabrir(a.he_id, true)}
                        title="Reabrir bloque liquidado"
                      >
                        <Undo2 size={14} /> Reabrir
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className={styles.pageInfo} style={{ textAlign: 'center', padding: 'var(--spacing-sm)' }}>
        {total} alerta{total === 1 ? '' : 's'}
      </div>
    </div>
  );
}
