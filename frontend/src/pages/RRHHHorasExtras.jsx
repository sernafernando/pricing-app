import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePermisos } from '../contexts/PermisosContext';
import { horasExtrasApi } from '../services/api';
import {
  Clock,
  RotateCcw,
  Check,
  X,
  Eye,
  AlertTriangle,
  Bell,
  FileSpreadsheet,
  CheckCheck,
  Undo2,
  Trash2,
  PenLine,
  CalendarDays,
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
  { key: 'pendientes', label: 'Pendientes' },
  { key: 'aprobadas', label: 'Aprobadas' },
  { key: 'liquidadas', label: 'Liquidadas' },
  { key: 'anomalias', label: 'Anomalías' },
  { key: 'alertas', label: 'Alertas' },
];

// `pendiente_asignacion_turno` va al tab Anomalías (junto con `error_fichadas`):
// son casos que requieren intervención humana antes de que haya HE aprobables.
const ESTADOS_POR_TAB = {
  pendientes: 'detectada',
  aprobadas: 'aprobada',
  liquidadas: 'liquidada',
  anomalias: 'error_fichadas,pendiente_asignacion_turno',
};

const PAGE_SIZE = 500;
const MAX_PAGES = 10; // safety cap

// ── Helpers de período / formato ─────────────────────────
function currentPeriodo() {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function periodoToInputMonth(p) {
  // "202605" -> "2026-05"
  if (!p || p.length !== 6) return '';
  return `${p.slice(0, 4)}-${p.slice(4, 6)}`;
}

function inputMonthToPeriodo(v) {
  // "2026-05" -> "202605"
  if (!v || v.length !== 7) return '';
  return v.replace('-', '');
}

function mesToRango(periodoYYYYMM) {
  const yyyy = parseInt(periodoYYYYMM.slice(0, 4), 10);
  const mm = parseInt(periodoYYYYMM.slice(4, 6), 10);
  if (Number.isNaN(yyyy) || Number.isNaN(mm)) {
    return { fecha_desde: '', fecha_hasta: '' };
  }
  const desde = new Date(Date.UTC(yyyy, mm - 1, 1));
  const hasta = new Date(Date.UTC(yyyy, mm, 0));
  const fmt = (d) => d.toISOString().slice(0, 10);
  return { fecha_desde: fmt(desde), fecha_hasta: fmt(hasta) };
}

function periodoLabel(periodoYYYYMM) {
  const yyyy = periodoYYYYMM.slice(0, 4);
  const mm = parseInt(periodoYYYYMM.slice(4, 6), 10);
  const meses = [
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
  ];
  const nombre = meses[mm - 1] || mm;
  return `${nombre} ${yyyy}`;
}

function fmtHoras(min) {
  // null = no calculado (pendiente_asignacion_turno o error_fichadas).
  // Distinto de "0 minutos calculados" — usamos guion para que se vea claro.
  if (min == null || Number.isNaN(min)) return '—';
  const total = Math.max(0, Math.round(min));
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${String(m).padStart(2, '0')}m`;
}

function fmtFechaCorta(iso) {
  if (!iso) return '-';
  const d = new Date(iso + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return iso;
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dia = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'][d.getDay()];
  return `${dd}/${mm} ${dia}`;
}

function fmtHora(timestampISO) {
  if (!timestampISO) return '—';
  const d = new Date(timestampISO);
  if (Number.isNaN(d.getTime())) return '—';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function fmtTimestamp(ts) {
  if (!ts) return '-';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// Clasifica un bloque entre 50% y 100% para los totales por empleado.
function clasificarRecargo(b) {
  const min = b.extras_minutos || 0;
  if (b.tipo_dia === 'habil_50') return { p50: min, p100: 0 };
  if (
    b.tipo_dia === 'sabado_100' ||
    b.tipo_dia === 'domingo_100' ||
    b.tipo_dia === 'feriado_100'
  ) {
    return { p50: 0, p100: min };
  }
  // manual u otros: clasificar por porcentaje_recargo
  const pct = Number(b.porcentaje_recargo) || 0;
  if (pct >= 100) return { p50: 0, p100: min };
  return { p50: min, p100: 0 };
}

const TIPO_DIA_BADGE = {
  habil_50: { label: '50%', cls: 'tipoDiaInfo' },
  sabado_100: { label: 'Sábado 100%', cls: 'tipoDiaWarn' },
  domingo_100: { label: 'Domingo 100%', cls: 'tipoDiaWarn' },
  feriado_100: { label: 'Feriado 100%', cls: 'tipoDiaWarn' },
  manual: { label: 'Manual', cls: 'tipoDiaNeutral' },
};

function tipoDiaBadge(tipo) {
  const meta = TIPO_DIA_BADGE[tipo] || { label: tipo || '-', cls: 'tipoDiaNeutral' };
  return { label: meta.label, cls: styles[meta.cls] || styles.tipoDiaNeutral };
}

export default function RRHHHorasExtras() {
  const { tienePermiso } = usePermisos();
  const navigate = useNavigate();

  // Permisos puntuales
  const puedeVer = tienePermiso('rrhh.ver_horas_extras');
  const puedeGestionar = tienePermiso('rrhh.gestionar_horas_extras');
  const puedeAprobar = tienePermiso('rrhh.aprobar_horas_extras');
  const puedeLiquidar = tienePermiso('rrhh.liquidar_horas_extras');

  // ── Tab + período ─────────────────────────
  const [activeTab, setActiveTab] = useState('pendientes');
  const [periodo, setPeriodo] = useState(currentPeriodo());

  // ── Datos: bloques (todas las tabs no-alertas) ──
  const [bloques, setBloques] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Alertas
  const [alertas, setAlertas] = useState([]);
  const [loadingAlertas, setLoadingAlertas] = useState(false);
  const [verLeidas, setVerLeidas] = useState(false);

  // Counts para badges (cantidad de empleados con bloques en el mes/tab)
  const [counts, setCounts] = useState({
    pendientes: 0,
    aprobadas: 0,
    liquidadas: 0,
    anomalias: 0,
    alertas: 0,
  });

  // ── Selección bulk ─────────────────────────
  // Modelo dual para preservar la decisión del usuario entre refreshes:
  //   - tab "pendientes": default = TODOS tildados. Usamos `excludedIds`
  //     (ids destildados manualmente). Así un refresh no re-tilda lo que
  //     el usuario destildó.
  //   - tab "aprobadas": default = NINGUNO tildado. Usamos `manualSelectedIds`
  //     (selección manual desde cero, comportamiento estándar).
  // Reset de ambos en cambio de tab o período.
  const [excludedIds, setExcludedIds] = useState(new Set());
  const [manualSelectedIds, setManualSelectedIds] = useState(new Set());

  // Modal state
  const [modal, setModal] = useState(null);

  const { fecha_desde, fecha_hasta } = useMemo(() => mesToRango(periodo), [periodo]);

  // ── Fetch helpers ─────────────────────────
  const fetchBloquesEstado = useCallback(
    async (estado) => {
      const acc = [];
      let pageNum = 1;
      // Loop conservador: page_size=500, hasta MAX_PAGES.
      // En la práctica un mes tiene <1000 bloques, así que con 1-2 páginas alcanza.
      while (pageNum <= MAX_PAGES) {
        const { data } = await horasExtrasApi.list({
          estado,
          fecha_desde,
          fecha_hasta,
          page: pageNum,
          page_size: PAGE_SIZE,
        });
        const items = data.items || [];
        acc.push(...items);
        const total = data.total ?? items.length;
        if (acc.length >= total || items.length === 0) break;
        pageNum += 1;
      }
      return acc;
    },
    [fecha_desde, fecha_hasta],
  );

  const fetchList = useCallback(async () => {
    if (!puedeVer || activeTab === 'alertas') return;
    setLoading(true);
    setError(null);
    try {
      const estado = ESTADOS_POR_TAB[activeTab];
      if (!estado) {
        setBloques([]);
        return;
      }
      const items = await fetchBloquesEstado(estado);
      setBloques(items);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Error al cargar bloques');
      setBloques([]);
    } finally {
      setLoading(false);
    }
  }, [puedeVer, activeTab, fetchBloquesEstado]);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  const fetchAlertas = useCallback(async () => {
    if (!puedeVer || activeTab !== 'alertas') return;
    setLoadingAlertas(true);
    setError(null);
    try {
      const { data } = await horasExtrasApi.alertasList({
        solo_no_leidas: !verLeidas,
        page: 1,
        page_size: PAGE_SIZE,
      });
      setAlertas(data.items || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Error al cargar alertas');
      setAlertas([]);
    } finally {
      setLoadingAlertas(false);
    }
  }, [puedeVer, activeTab, verLeidas]);

  useEffect(() => {
    fetchAlertas();
  }, [fetchAlertas]);

  // Counts: cantidad de empleados distintos con bloques en el mes por tab.
  // Una única llamada al endpoint /resumen que agrega por estado en backend.
  const fetchCounts = useCallback(async () => {
    if (!puedeVer) return;
    try {
      const { data } = await horasExtrasApi.resumen(periodo);
      const porEstado = Object.fromEntries(
        (data.estados || []).map((e) => [e.estado, e.empleados]),
      );
      setCounts({
        // Caveat: el backend devuelve empleados distintos POR estado, no globalmente.
        // Sumar estados en anomalías puede sobrecontar si un empleado tiene bloques
        // en ambos (error_fichadas + pendiente_asignacion_turno) — raro, y solo
        // afecta el badge cosmético.
        pendientes: porEstado.detectada || 0,
        aprobadas: porEstado.aprobada || 0,
        liquidadas: porEstado.liquidada || 0,
        anomalias:
          (porEstado.error_fichadas || 0) + (porEstado.pendiente_asignacion_turno || 0),
        alertas: data.empleados_con_alertas || 0,
      });
    } catch (err) {
      // Counts son cosméticos: no bloqueamos UI, solo logueamos.
      console.error('Error cargando resumen mensual:', err);
    }
  }, [puedeVer, periodo]);

  useEffect(() => {
    fetchCounts();
  }, [fetchCounts]);

  // ── Refresh helper ────────────────────────
  const refresh = useCallback(() => {
    fetchList();
    fetchAlertas();
    fetchCounts();
  }, [fetchList, fetchAlertas, fetchCounts]);

  // ── Agrupación por empleado ───────────────
  const empleadosAgrupados = useMemo(() => {
    const acc = new Map();
    for (const b of bloques) {
      if (!acc.has(b.empleado_id)) {
        acc.set(b.empleado_id, {
          empleado_id: b.empleado_id,
          empleado_nombre: b.empleado_nombre || `#${b.empleado_id}`,
          empleado_legajo: b.empleado_legajo || '-',
          bloques: [],
          total_minutos_50: 0,
          total_minutos_100: 0,
        });
      }
      const ref = acc.get(b.empleado_id);
      ref.bloques.push(b);
      const { p50, p100 } = clasificarRecargo(b);
      ref.total_minutos_50 += p50;
      ref.total_minutos_100 += p100;
    }
    return Array.from(acc.values())
      .sort((a, b) => a.empleado_nombre.localeCompare(b.empleado_nombre, 'es'))
      .map((e) => ({
        ...e,
        bloques: [...e.bloques].sort((a, b) => {
          const cmp = a.fecha.localeCompare(b.fecha);
          if (cmp !== 0) return cmp;
          return (a.id || 0) - (b.id || 0);
        }),
      }));
  }, [bloques]);

  // selectedIds derivado del modelo dual.
  //   - pendientes: aprobables (estado=detectada) - excluidos por el user
  //   - aprobadas:  manualSelectedIds (intersección con bloques visibles para
  //                 evitar ids "fantasma" que sobreviven a un refresh)
  //   - resto:      vacío (no hay bulk select)
  const selectedIds = useMemo(() => {
    if (activeTab === 'pendientes') {
      const aprobables = bloques
        .filter((b) => b.estado === 'detectada')
        .map((b) => b.id);
      return new Set(aprobables.filter((id) => !excludedIds.has(id)));
    }
    if (activeTab === 'aprobadas') {
      const visibles = new Set(bloques.map((b) => b.id));
      return new Set(
        Array.from(manualSelectedIds).filter((id) => visibles.has(id)),
      );
    }
    return new Set();
  }, [activeTab, bloques, excludedIds, manualSelectedIds]);

  // Reset de ambos sets al cambiar de tab o período.
  useEffect(() => {
    setExcludedIds(new Set());
    setManualSelectedIds(new Set());
  }, [activeTab, periodo]);

  // Agrupación de alertas por empleado
  const alertasFiltradas = useMemo(() => {
    // Filtra al mes seleccionado por la fecha de la alerta cuando está disponible.
    const inRange = (iso) => {
      if (!iso) return true;
      return iso >= fecha_desde && iso <= fecha_hasta;
    };
    return alertas.filter((a) => inRange(a.fecha));
  }, [alertas, fecha_desde, fecha_hasta]);

  const alertasAgrupadas = useMemo(() => {
    const acc = new Map();
    for (const a of alertasFiltradas) {
      const key = a.empleado_id || 0;
      if (!acc.has(key)) {
        acc.set(key, {
          empleado_id: a.empleado_id,
          empleado_nombre: a.empleado_nombre || (a.empleado_id ? `#${a.empleado_id}` : 'Sin empleado'),
          empleado_legajo: a.empleado_legajo || '-',
          alertas: [],
        });
      }
      acc.get(key).alertas.push(a);
    }
    return Array.from(acc.values()).sort((a, b) =>
      (a.empleado_nombre || '').localeCompare(b.empleado_nombre || '', 'es'),
    );
  }, [alertasFiltradas]);

  // ── Selección bulk helpers ────────────────
  // Toggle: en "pendientes" mutamos `excludedIds` (lógica invertida);
  // en "aprobadas" mutamos `manualSelectedIds` (lógica directa).
  const toggleSelectId = useCallback(
    (id) => {
      if (activeTab === 'pendientes') {
        setExcludedIds((prev) => {
          const next = new Set(prev);
          // Si está excluido → re-tildar (quitar del exclude set).
          // Si no está excluido → destildar (agregar al exclude set).
          if (next.has(id)) next.delete(id);
          else next.add(id);
          return next;
        });
      } else if (activeTab === 'aprobadas') {
        setManualSelectedIds((prev) => {
          const next = new Set(prev);
          if (next.has(id)) next.delete(id);
          else next.add(id);
          return next;
        });
      }
    },
    [activeTab],
  );

  const toggleSelectEmpleado = useCallback(
    (emp) => {
      const ids = emp.bloques
        .filter(
          (b) => b.estado !== 'error_fichadas' && b.estado !== 'pendiente_asignacion_turno',
        )
        .map((b) => b.id);
      if (ids.length === 0) return;

      if (activeTab === 'pendientes') {
        // En pendientes: si TODOS están tildados (= ninguno está en excluded),
        // los destildamos a todos (los agregamos a excluded).
        // Si alguno está destildado, los re-tildamos a todos (los quitamos de excluded).
        setExcludedIds((prev) => {
          const next = new Set(prev);
          const allOn = ids.every((id) => !next.has(id));
          if (allOn) ids.forEach((id) => next.add(id));
          else ids.forEach((id) => next.delete(id));
          return next;
        });
      } else if (activeTab === 'aprobadas') {
        setManualSelectedIds((prev) => {
          const next = new Set(prev);
          const allOn = ids.every((id) => next.has(id));
          if (allOn) ids.forEach((id) => next.delete(id));
          else ids.forEach((id) => next.add(id));
          return next;
        });
      }
    },
    [activeTab],
  );

  // Helper: limpia selección actual (según tab activo).
  // En "pendientes" eso significa destildar todo (excluir todos los aprobables).
  // En "aprobadas" significa vaciar el set manual.
  const clearSelection = useCallback(() => {
    if (activeTab === 'pendientes') {
      const aprobables = bloques
        .filter((b) => b.estado === 'detectada')
        .map((b) => b.id);
      setExcludedIds(new Set(aprobables));
    } else if (activeTab === 'aprobadas') {
      setManualSelectedIds(new Set());
    }
  }, [activeTab, bloques]);

  // Helper: tras una acción bulk exitosa, los ids procesados ya no están
  // en `bloques`, pero mantenemos los sets coherentes (no acumular basura).
  const resetSelection = useCallback(() => {
    setExcludedIds(new Set());
    setManualSelectedIds(new Set());
  }, []);

  // ── Actions ────────────────────────────────
  const handleAprobarIndividual = useCallback(
    async (id, body = {}) => {
      await horasExtrasApi.aprobar(id, body);
      refresh();
    },
    [refresh],
  );

  const handleRechazarIndividual = useCallback(
    async (id, motivo) => {
      await horasExtrasApi.rechazar(id, { motivo });
      refresh();
    },
    [refresh],
  );

  const handleReabrir = useCallback(
    async (id, motivo) => {
      await horasExtrasApi.reabrir(id, { motivo });
      refresh();
    },
    [refresh],
  );

  const handleBulkAprobar = useCallback(
    async (body) => {
      const ids = Array.from(selectedIds);
      await horasExtrasApi.bulkAprobar({ ids, ...body });
      resetSelection();
      refresh();
    },
    [selectedIds, refresh, resetSelection],
  );

  const handleBulkRechazar = useCallback(
    async (motivo) => {
      const ids = Array.from(selectedIds);
      await horasExtrasApi.bulkRechazar({ ids, motivo });
      resetSelection();
      refresh();
    },
    [selectedIds, refresh, resetSelection],
  );

  const handleBulkReabrir = useCallback(
    async (motivo) => {
      const ids = Array.from(selectedIds);
      // Una sola llamada al endpoint bulk: errores parciales vienen en `fallidos`,
      // no como excepción global. Un fallido individual no aborta al resto.
      const { data } = await horasExtrasApi.bulkReabrir({ ids, motivo });
      const fallidos = data?.fallidos || [];
      if (fallidos.length > 0) {
        const detalle = fallidos
          .slice(0, 5)
          .map((f) => `#${f.id}: ${f.detail || f.status}`)
          .join('; ');
        const extra = fallidos.length > 5 ? ` (+${fallidos.length - 5} más)` : '';
        setError(`No se pudieron reabrir ${fallidos.length} bloque(s): ${detalle}${extra}`);
      }
      resetSelection();
      refresh();
    },
    [selectedIds, refresh, resetSelection],
  );

  const handleCompletarFichada = useCallback(
    async (id, body) => {
      await horasExtrasApi.completarFichada(id, body);
      refresh();
    },
    [refresh],
  );

  const handleDescartarDia = useCallback(
    async (id, motivo) => {
      await horasExtrasApi.descartarDia(id, { motivo });
      refresh();
    },
    [refresh],
  );

  const handleRecalcular = useCallback(
    async (body) => {
      const { data } = await horasExtrasApi.recalcular(body);
      refresh();
      return data;
    },
    [refresh],
  );

  const handleLiquidar = useCallback(
    async (body) => {
      await horasExtrasApi.liquidar(body);
      resetSelection();
      refresh();
    },
    [refresh, resetSelection],
  );

  const handleAlertaMarcarLeida = useCallback(
    async (id) => {
      try {
        await horasExtrasApi.alertaMarcarLeida(id);
        fetchAlertas();
        fetchCounts();
      } catch (err) {
        setError(err?.response?.data?.detail || 'Error al marcar la alerta');
      }
    },
    [fetchAlertas, fetchCounts],
  );

  // Export Excel — usa el periodo global (siempre disponible).
  const handleExportar = useCallback(async () => {
    if (!periodo || !/^\d{6}$/.test(periodo)) {
      setError('Período inválido para exportar.');
      return;
    }
    try {
      const res = await horasExtrasApi.exportarXlsx({ periodo });
      const blob = new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `horas_extras_${periodo}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Error al exportar Excel');
    }
  }, [periodo]);

  // ── Render ────────────────────────────────
  const isAlertasTab = activeTab === 'alertas';
  const isAnomaliasTab = activeTab === 'anomalias';
  const isPendientesTab = activeTab === 'pendientes';
  const isAprobadasTab = activeTab === 'aprobadas';
  const isLiquidadasTab = activeTab === 'liquidadas';
  const showBulkBar =
    !isAlertasTab && !isAnomaliasTab && selectedIds.size > 0 && (isPendientesTab || isAprobadasTab);

  if (!puedeVer) {
    return (
      <div className={styles.container}>
        <div className={styles.deniedMsg}>
          No tenés permiso para ver el módulo de Horas Extras.
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Clock size={24} />
          <h1>RRHH › Horas Extras</h1>
        </div>
        <div className={styles.headerActions}>
          <label className={styles.monthPickerLabel}>
            Mes
            <input
              type="month"
              className={styles.input}
              value={periodoToInputMonth(periodo)}
              onChange={(e) => {
                const next = inputMonthToPeriodo(e.target.value);
                if (next) setPeriodo(next);
              }}
            />
          </label>
          {puedeGestionar && (
            <button
              className={styles.btnPrimary}
              onClick={() => setModal({ type: 'recalcular' })}
            >
              <RotateCcw size={14} /> Recalcular período
            </button>
          )}
          {isLiquidadasTab && (
            <button className={styles.btnPrimary} onClick={handleExportar}>
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

      {/* Bulk bar */}
      {showBulkBar && (
        <div className={styles.bulkBar}>
          <span className={styles.bulkCount}>
            {selectedIds.size} bloque{selectedIds.size === 1 ? '' : 's'} seleccionado{selectedIds.size === 1 ? '' : 's'}
          </span>
          {isPendientesTab && puedeAprobar && (
            <>
              <button
                className={styles.btnApprove}
                onClick={() => setModal({ type: 'aprobar', ids: Array.from(selectedIds) })}
              >
                <CheckCheck size={14} /> Aprobar seleccionados
              </button>
              <button
                className={styles.btnReject}
                onClick={() => setModal({ type: 'rechazar', target: 'bulk', ids: Array.from(selectedIds) })}
              >
                <X size={14} /> Rechazar seleccionados
              </button>
            </>
          )}
          {isAprobadasTab && puedeLiquidar && (
            <button
              className={styles.btnPrimary}
              onClick={() => setModal({ type: 'liquidar', ids: Array.from(selectedIds) })}
            >
              <FileSpreadsheet size={14} /> Liquidar seleccionados
            </button>
          )}
          {isAprobadasTab && puedeAprobar && (
            <button
              className={styles.btnWarning}
              onClick={() => setModal({ type: 'reabrirBulk', ids: Array.from(selectedIds) })}
            >
              <Undo2 size={14} /> Reabrir seleccionados
            </button>
          )}
          <button
            className={styles.btnSecondary}
            onClick={clearSelection}
          >
            Limpiar selección
          </button>
        </div>
      )}

      {/* Toggle ver leídas (alertas) */}
      {isAlertasTab && (
        <div className={styles.filters}>
          <label className={styles.checkboxRow}>
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
      {isAlertasTab ? (
        <AlertasView
          loading={loadingAlertas}
          empleados={alertasAgrupadas}
          puedeAprobar={puedeAprobar}
          puedeGestionar={puedeGestionar}
          periodoLabel={periodoLabel(periodo)}
          onMarcarLeida={handleAlertaMarcarLeida}
          onAbrirDetalle={(heId) => setModal({ type: 'detalle', id: heId })}
          onReabrir={(heId, eraLiquidada) =>
            setModal({ type: 'reabrir', id: heId, era_liquidada: eraLiquidada })
          }
        />
      ) : (
        <EmpleadosView
          loading={loading}
          empleados={empleadosAgrupados}
          activeTab={activeTab}
          selectedIds={selectedIds}
          onToggleSelectId={toggleSelectId}
          onToggleSelectEmpleado={toggleSelectEmpleado}
          puedeAprobar={puedeAprobar}
          puedeGestionar={puedeGestionar}
          puedeLiquidar={puedeLiquidar}
          periodoLabelText={periodoLabel(periodo)}
          onAprobar={(id) => setModal({ type: 'aprobar', id })}
          onRechazar={(id) => setModal({ type: 'rechazar', target: 'individual', id })}
          onReabrir={(id, eraLiquidada) =>
            setModal({ type: 'reabrir', id, era_liquidada: eraLiquidada })
          }
          onCompletar={(id) => setModal({ type: 'completar', id })}
          onDescartar={(id) => setModal({ type: 'descartar', id })}
          onAsignarTurno={() => navigate('/rrhh/horarios')}
          onDetalle={(id) => setModal({ type: 'detalle', id })}
          onLiquidar={(ids) => setModal({ type: 'liquidar', ids })}
        />
      )}

      {/* ── Modals ───────────────────────────── */}
      <HEModalAprobar
        open={modal?.type === 'aprobar'}
        bulkCount={modal?.type === 'aprobar' && modal.ids ? modal.ids.length : null}
        defaultPorcentaje={
          modal?.type === 'aprobar' && modal.id
            ? bloques.find((i) => i.id === modal.id)?.porcentaje_recargo
            : null
        }
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
        title={
          modal?.target === 'bulk'
            ? `Rechazar ${modal.ids?.length || 0} bloques`
            : 'Rechazar bloque'
        }
        confirmLabel="Rechazar"
        confirmVariant="danger"
        placeholder="Motivo del rechazo..."
        bulkCount={modal?.target === 'bulk' ? modal.ids?.length || 0 : null}
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
        warning={
          modal?.era_liquidada
            ? 'Este bloque fue liquidado. Reabrirlo afecta una liquidación cerrada.'
            : null
        }
        onClose={() => setModal(null)}
        onConfirm={async (motivo) => {
          if (modal?.id) {
            await handleReabrir(modal.id, motivo);
          }
          setModal(null);
        }}
      />

      <HEModalMotivo
        open={modal?.type === 'reabrirBulk'}
        title={`Reabrir ${modal?.ids?.length || 0} bloques`}
        confirmLabel="Reabrir"
        confirmVariant="warning"
        placeholder="Motivo de la reapertura..."
        bulkCount={modal?.type === 'reabrirBulk' ? modal.ids?.length || 0 : null}
        onClose={() => setModal(null)}
        onConfirm={async (motivo) => {
          await handleBulkReabrir(motivo);
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
// Subcomponente: empleados con acordeones (tabs de bloques)
// ─────────────────────────────────────────────────────────
function EmpleadosView({
  loading,
  empleados,
  activeTab,
  selectedIds,
  onToggleSelectId,
  onToggleSelectEmpleado,
  puedeAprobar,
  puedeGestionar,
  puedeLiquidar,
  periodoLabelText,
  onAprobar,
  onRechazar,
  onReabrir,
  onCompletar,
  onDescartar,
  onAsignarTurno,
  onDetalle,
  onLiquidar,
}) {
  if (loading) {
    return <div className={styles.loading}>Cargando bloques de {periodoLabelText}...</div>;
  }
  if (empleados.length === 0) {
    const tabName = {
      pendientes: 'pendientes',
      aprobadas: 'aprobadas',
      liquidadas: 'liquidadas',
      anomalias: 'anomalías',
    }[activeTab] || 'el período';
    return (
      <div className={styles.emptyState}>
        No hay horas extras {tabName} en {periodoLabelText}.
      </div>
    );
  }

  const showCheckbox = activeTab === 'pendientes' || activeTab === 'aprobadas';
  const onlyOne = empleados.length === 1;

  return (
    <div className={styles.empleadosList}>
      {empleados.map((e) => (
        <EmpleadoAcordeon
          key={e.empleado_id}
          empleado={e}
          activeTab={activeTab}
          showCheckbox={showCheckbox}
          openDefault={onlyOne}
          selectedIds={selectedIds}
          onToggleSelectId={onToggleSelectId}
          onToggleSelectEmpleado={onToggleSelectEmpleado}
          puedeAprobar={puedeAprobar}
          puedeGestionar={puedeGestionar}
          puedeLiquidar={puedeLiquidar}
          onAprobar={onAprobar}
          onRechazar={onRechazar}
          onReabrir={onReabrir}
          onCompletar={onCompletar}
          onDescartar={onDescartar}
          onAsignarTurno={onAsignarTurno}
          onDetalle={onDetalle}
          onLiquidar={onLiquidar}
        />
      ))}
    </div>
  );
}

function EmpleadoAcordeon({
  empleado,
  activeTab,
  showCheckbox,
  openDefault,
  selectedIds,
  onToggleSelectId,
  onToggleSelectEmpleado,
  puedeAprobar,
  puedeGestionar,
  puedeLiquidar,
  onAprobar,
  onRechazar,
  onReabrir,
  onCompletar,
  onDescartar,
  onAsignarTurno,
  onDetalle,
  onLiquidar,
}) {
  const idsAprobables = empleado.bloques
    .filter((b) => b.estado !== 'error_fichadas' && b.estado !== 'pendiente_asignacion_turno')
    .map((b) => b.id);
  const allEmpSelected = idsAprobables.length > 0 && idsAprobables.every((id) => selectedIds.has(id));
  const someEmpSelected = idsAprobables.some((id) => selectedIds.has(id));

  const idsAprobados = empleado.bloques
    .filter((b) => b.estado === 'aprobada')
    .map((b) => b.id);

  return (
    <details className={styles.empleadoCard} open={openDefault}>
      <summary className={styles.empleadoHeader}>
        <div className={styles.empleadoHeaderLeft}>
          {showCheckbox && (
            <input
              type="checkbox"
              checked={allEmpSelected}
              ref={(el) => {
                if (el) el.indeterminate = !allEmpSelected && someEmpSelected;
              }}
              onChange={(e) => {
                e.stopPropagation();
                onToggleSelectEmpleado(empleado);
              }}
              onClick={(e) => e.stopPropagation()}
              aria-label={`Seleccionar bloques de ${empleado.empleado_nombre}`}
            />
          )}
          <div className={styles.empleadoIdent}>
            <span className={styles.empleadoNombre}>{empleado.empleado_nombre}</span>
            <span className={styles.empleadoLegajo}>Legajo {empleado.empleado_legajo}</span>
          </div>
        </div>
        <div className={styles.empleadoTotales}>
          <span className={styles.totalBadge50}>
            50% — {fmtHoras(empleado.total_minutos_50)}
          </span>
          <span className={styles.totalBadge100}>
            100% — {fmtHoras(empleado.total_minutos_100)}
          </span>
          <span className={styles.totalBadgeNeutral}>
            {empleado.bloques.length} bloque{empleado.bloques.length === 1 ? '' : 's'}
          </span>
          {activeTab === 'aprobadas' && puedeLiquidar && idsAprobados.length > 0 && (
            <button
              className={styles.btnPrimary}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onLiquidar(idsAprobados);
              }}
              title={`Liquidar los ${idsAprobados.length} bloques aprobados de ${empleado.empleado_nombre}`}
            >
              <FileSpreadsheet size={14} /> Liquidar mes
            </button>
          )}
        </div>
      </summary>

      <BloquesTable
        bloques={empleado.bloques}
        activeTab={activeTab}
        showCheckbox={showCheckbox}
        selectedIds={selectedIds}
        onToggleSelectId={onToggleSelectId}
        puedeAprobar={puedeAprobar}
        puedeGestionar={puedeGestionar}
        onAprobar={onAprobar}
        onRechazar={onRechazar}
        onReabrir={onReabrir}
        onCompletar={onCompletar}
        onDescartar={onDescartar}
        onAsignarTurno={onAsignarTurno}
        onDetalle={onDetalle}
      />
    </details>
  );
}

function BloquesTable({
  bloques,
  activeTab,
  showCheckbox,
  selectedIds,
  onToggleSelectId,
  puedeAprobar,
  puedeGestionar,
  onAprobar,
  onRechazar,
  onReabrir,
  onCompletar,
  onDescartar,
  onAsignarTurno,
  onDetalle,
}) {
  return (
    <div className={styles.bloquesTableWrap}>
      <table className={styles.bloquesTable}>
        <thead>
          <tr>
            {showCheckbox && <th className={styles.colCheck} aria-label="Seleccionar" />}
            <th className={styles.colFecha}>Fecha</th>
            <th>Entrada → Salida</th>
            <th>Tipo</th>
            <th className={styles.colMinutos}>HE</th>
            <th className={styles.colPct}>%</th>
            {activeTab === 'anomalias' && <th>Error</th>}
            {activeTab === 'aprobadas' && <th>Aprobado por</th>}
            {activeTab === 'liquidadas' && <th>Período liq.</th>}
            {activeTab === 'liquidadas' && <th>Liquidado por</th>}
            <th>Estado</th>
            <th className={styles.colActions}>Acciones</th>
          </tr>
        </thead>
        <tbody>
          {bloques.map((b) => {
            const tipo = tipoDiaBadge(b.tipo_dia);
            const selectable =
              showCheckbox &&
              b.estado !== 'error_fichadas' &&
              b.estado !== 'pendiente_asignacion_turno';
            const isSelected = selectedIds.has(b.id);
            return (
              <tr key={b.id} className={isSelected ? styles.rowSelected : undefined}>
                {showCheckbox && (
                  <td className={styles.colCheck}>
                    {selectable ? (
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => onToggleSelectId(b.id)}
                        aria-label={`Seleccionar bloque ${b.id}`}
                      />
                    ) : null}
                  </td>
                )}
                <td className={styles.colFecha}>{fmtFechaCorta(b.fecha)}</td>
                <td className={styles.colHorario}>
                  <span className={styles.horarioRange}>
                    {fmtHora(b.fichada_entrada?.timestamp)}
                    <span className={styles.horarioArrow}>→</span>
                    {fmtHora(b.fichada_salida?.timestamp)}
                  </span>
                </td>
                <td>
                  <span className={tipo.cls}>{tipo.label}</span>
                </td>
                <td className={styles.colMinutos}>{fmtHoras(b.extras_minutos)}</td>
                <td className={styles.colPct}>
                  {b.porcentaje_recargo != null ? `${b.porcentaje_recargo}%` : '-'}
                </td>
                {activeTab === 'anomalias' && <td>{b.error_tipo || '-'}</td>}
                {activeTab === 'aprobadas' && (
                  <td>{b.aprobado_por_nombre || '-'}</td>
                )}
                {activeTab === 'liquidadas' && <td>{b.liquidacion_periodo || '-'}</td>}
                {activeTab === 'liquidadas' && (
                  <td>
                    {b.aprobado_por_nombre || '-'}
                    {b.liquidado_at && (
                      <div className={styles.subtle}>{fmtTimestamp(b.liquidado_at)}</div>
                    )}
                  </td>
                )}
                <td>
                  <span className={styles[`estado--${b.estado}`] || styles.estadoBadge}>
                    {b.estado}
                  </span>
                </td>
                <td className={styles.colActions}>
                  <div className={styles.actions}>
                    <button
                      className={styles.btnIcon}
                      onClick={() => onDetalle(b.id)}
                      title="Ver detalle"
                      aria-label="Ver detalle"
                    >
                      <Eye size={14} />
                    </button>

                    {activeTab === 'pendientes' &&
                      b.estado === 'detectada' &&
                      puedeAprobar && (
                        <>
                          <button
                            className={styles.btnApprove}
                            onClick={() => onAprobar(b.id)}
                            title="Aprobar"
                            aria-label="Aprobar"
                          >
                            <Check size={14} />
                          </button>
                          <button
                            className={styles.btnReject}
                            onClick={() => onRechazar(b.id)}
                            title="Rechazar"
                            aria-label="Rechazar"
                          >
                            <X size={14} />
                          </button>
                        </>
                      )}

                    {activeTab === 'anomalias' && (
                      <>
                        {b.estado === 'pendiente_asignacion_turno' ? (
                          puedeGestionar && (
                            <button
                              className={styles.btnPrimary}
                              onClick={() => onAsignarTurno()}
                              title="Asignar turno al empleado"
                            >
                              <CalendarDays size={14} /> Asignar turno
                            </button>
                          )
                        ) : (
                          <>
                            {puedeGestionar && (
                              <button
                                className={styles.btnPrimary}
                                onClick={() => onCompletar(b.id)}
                                title="Completar fichada"
                              >
                                <PenLine size={14} /> Completar
                              </button>
                            )}
                            {puedeAprobar && (
                              <button
                                className={styles.btnWarning}
                                onClick={() => onDescartar(b.id)}
                                title="Descartar día"
                                aria-label="Descartar día"
                              >
                                <Trash2 size={14} />
                              </button>
                            )}
                          </>
                        )}
                      </>
                    )}

                    {activeTab === 'aprobadas' && puedeAprobar && (
                      <button
                        className={styles.btnWarning}
                        onClick={() => onReabrir(b.id, false)}
                        title="Reabrir"
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
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// Subcomponente: alertas agrupadas por empleado
// ─────────────────────────────────────────────────────────
function AlertasView({
  loading,
  empleados,
  puedeAprobar,
  puedeGestionar,
  periodoLabel: periodoLabelText,
  onMarcarLeida,
  onAbrirDetalle,
  onReabrir,
}) {
  if (loading) {
    return <div className={styles.loading}>Cargando alertas...</div>;
  }
  if (empleados.length === 0) {
    return (
      <div className={styles.emptyState}>
        No hay alertas para mostrar en {periodoLabelText}.
      </div>
    );
  }

  const REOPEN_TIPOS = new Set([
    'liquidacion_afectada_por_cambio_turno',
    'fichada_modificada_post_aprobacion',
  ]);

  const onlyOne = empleados.length === 1;

  return (
    <div className={styles.empleadosList}>
      {empleados.map((emp) => (
        <details
          key={emp.empleado_id || 'sin-empleado'}
          className={styles.empleadoCard}
          open={onlyOne}
        >
          <summary className={styles.empleadoHeader}>
            <div className={styles.empleadoHeaderLeft}>
              <div className={styles.empleadoIdent}>
                <span className={styles.empleadoNombre}>{emp.empleado_nombre}</span>
                <span className={styles.empleadoLegajo}>Legajo {emp.empleado_legajo}</span>
              </div>
            </div>
            <div className={styles.empleadoTotales}>
              <span className={styles.totalBadgeNeutral}>
                {emp.alertas.length} alerta{emp.alertas.length === 1 ? '' : 's'}
              </span>
            </div>
          </summary>

          <div className={styles.bloquesTableWrap}>
            <table className={styles.bloquesTable}>
              <thead>
                <tr>
                  <th>Severidad</th>
                  <th>Tipo</th>
                  <th>Mensaje</th>
                  <th>Fecha bloque</th>
                  <th>Generada</th>
                  <th className={styles.colActions}>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {emp.alertas.map((a) => {
                  const sevClass = styles[`sev--${a.severidad}`] || styles.sevBadge;
                  const puedeReabrirAlerta = REOPEN_TIPOS.has(a.tipo);
                  return (
                    <tr key={a.id} className={a.leida_at ? styles.rowFaded : undefined}>
                      <td>
                        <span className={sevClass}>{a.severidad}</span>
                      </td>
                      <td>{a.tipo}</td>
                      <td>{a.mensaje}</td>
                      <td>{fmtFechaCorta(a.fecha)}</td>
                      <td>{fmtTimestamp(a.created_at)}</td>
                      <td className={styles.colActions}>
                        <div className={styles.actions}>
                          {a.he_id && (
                            <button
                              className={styles.btnIcon}
                              onClick={() => onAbrirDetalle(a.he_id)}
                              title={`Abrir bloque #${a.he_id}`}
                              aria-label="Abrir bloque"
                            >
                              <Eye size={14} />
                            </button>
                          )}
                          {!a.leida_at && (puedeGestionar || puedeAprobar) && (
                            <button
                              className={styles.btnSecondary}
                              onClick={() => onMarcarLeida(a.id)}
                              title="Marcar leída"
                            >
                              <Check size={14} /> Marcar leída
                            </button>
                          )}
                          {a.he_id && puedeReabrirAlerta && puedeAprobar && (
                            <button
                              className={styles.btnWarning}
                              onClick={() => onReabrir(a.he_id, true)}
                              title="Reabrir bloque"
                            >
                              <Undo2 size={14} /> Reabrir bloque
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      ))}
    </div>
  );
}
