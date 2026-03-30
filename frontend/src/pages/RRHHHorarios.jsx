import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI } from '../services/api';
import {
  Clock, Plus, RefreshCw, Trash2, Edit2, Link, Unlink,
  Fingerprint, Settings, CalendarOff, LogIn, LogOut,
  ArrowUpDown, Check, X, Timer, Users, UserPlus, UserMinus,
  ChevronDown, ChevronUp, MapPin,
} from 'lucide-react';
import styles from './RRHHHorarios.module.css';

const formatFichadaDate = (ts) => {
  if (!ts) return '-';
  const d = new Date(ts);
  return d.toLocaleDateString('es-AR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
  });
};

const formatFichadaTime = (ts) => {
  if (!ts) return '-';
  const d = new Date(ts);
  return d.toLocaleTimeString('es-AR', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  });
};

const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
};

const formatTime = (timeStr) => {
  if (!timeStr) return '-';
  return timeStr.slice(0, 5);
};

const formatHorasDia = (horas) => {
  if (horas == null) return '-';
  const h = Math.floor(horas);
  const m = Math.round((horas - h) * 60);
  return `${h}h ${m.toString().padStart(2, '0')}m`;
};

const DIAS_SEMANA_MAP = {
  1: 'Lun', 2: 'Mar', 3: 'Mié', 4: 'Jue', 5: 'Vie', 6: 'Sáb', 7: 'Dom',
};

const formatDiasSemana = (dias) => {
  if (!dias) return '-';
  return dias.split(',').map((d) => DIAS_SEMANA_MAP[d.trim()] || d).join(', ');
};

const PAGE_SIZE = 50;

const PUNTUALIDAD_STYLE = {
  a_tiempo: 'fichadaHoraOk',
  tolerancia: 'fichadaHoraTolerancia',
  tarde: 'fichadaHoraTarde',
};

const getErrorMessage = (err, fallback) => {
  const data = err?.response?.data;
  if (typeof data === 'string' && data.trim()) return data;
  if (data && typeof data === 'object') {
    if (typeof data.detail === 'string' && data.detail.trim()) return data.detail;
    if (typeof data.message === 'string' && data.message.trim()) return data.message;
  }
  if (typeof err?.message === 'string' && err.message.trim()) return err.message;
  return fallback;
};

export default function RRHHHorarios() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rrhh.gestionar');
  const puedeConfig = tienePermiso('rrhh.config');

  // ── Tab state ──
  const [activeTab, setActiveTab] = useState('fichadas');

  // ── Fichadas ──
  const [fichadas, setFichadas] = useState([]);
  const [fichadasTotal, setFichadasTotal] = useState(0);
  const [loadingFichadas, setLoadingFichadas] = useState(true);
  const [fichadasPage, setFichadasPage] = useState(1);
  const [filtroEmpleadoId, setFiltroEmpleadoId] = useState('');
  const [filtroFechaDesde, setFiltroFechaDesde] = useState('');
  const [filtroFechaHasta, setFiltroFechaHasta] = useState('');
  const [filtroOrigen, setFiltroOrigen] = useState('');
  const [fichadasOrden, setFichadasOrden] = useState('desc');

  // ── Inline motivo editing ──
  const [editingMotivoId, setEditingMotivoId] = useState(null);
  const [editingMotivoValue, setEditingMotivoValue] = useState('');
  const [savingMotivo, setSavingMotivo] = useState(false);

  // ── Manual fichada modal ──
  const [fichadaModalOpen, setFichadaModalOpen] = useState(false);
  const [fichadaForm, setFichadaForm] = useState({
    empleado_id: '', timestamp: '', tipo: 'entrada', motivo_manual: '',
  });
  const [fichadaSaving, setFichadaSaving] = useState(false);
  const [fichadaError, setFichadaError] = useState(null);

  // ── Hikvision sync ──
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);

  // ── Horarios ──
  const [horarios, setHorarios] = useState([]);
  const [loadingHorarios, setLoadingHorarios] = useState(true);

  // ── Horario modal ──
  const [horarioModalOpen, setHorarioModalOpen] = useState(false);
  const [horarioEditing, setHorarioEditing] = useState(null);
  const [horarioForm, setHorarioForm] = useState({
    nombre: '', hora_entrada: '08:00', hora_salida: '17:00',
    tolerancia_minutos: '15', dias_semana: '1,2,3,4,5', activo: true,
  });
  const [horarioSaving, setHorarioSaving] = useState(false);
  const [horarioError, setHorarioError] = useState(null);

  // ── Empleados por horario (asignación de turnos) ──
  const [expandedHorarioId, setExpandedHorarioId] = useState(null);
  const [empleadosHorario, setEmpleadosHorario] = useState([]);
  const [loadingEmpleadosHorario, setLoadingEmpleadosHorario] = useState(false);
  const [asignandoEmpleado, setAsignandoEmpleado] = useState(false);
  const [nuevoEmpleadoHorario, setNuevoEmpleadoHorario] = useState('');
  const [nuevaPrioridad, setNuevaPrioridad] = useState('1');
  const [asignacionError, setAsignacionError] = useState(null);

  // ── Excepciones ──
  const [excepciones, setExcepciones] = useState([]);
  const [loadingExcepciones, setLoadingExcepciones] = useState(true);
  const [filtroAnioExcep, setFiltroAnioExcep] = useState(String(new Date().getFullYear()));

  // ── Excepción modal ──
  const [excepModalOpen, setExcepModalOpen] = useState(false);
  const [excepEditing, setExcepEditing] = useState(null);
  const [excepForm, setExcepForm] = useState({
    fecha: '', tipo: 'feriado', descripcion: '', es_laborable: false,
  });
  const [excepSaving, setExcepSaving] = useState(false);
  const [excepError, setExcepError] = useState(null);

  // ── Hikvision mapping ──
  const [hikUsers, setHikUsers] = useState([]);
  const [loadingHik, setLoadingHik] = useState(false);
  const [hikError, setHikError] = useState(null);
  const [mappingSelections, setMappingSelections] = useState({});

  // ── Empleados list (for selects) ──
  const [empleados, setEmpleados] = useState([]);

  // ── Confirmation modal ──
  const [confirmAction, setConfirmAction] = useState(null); // { title, message, onConfirm }
  const [actionError, setActionError] = useState(null);

  const updateMappingSelection = (employeeNo, value) => {
    setMappingSelections((prev) => ({ ...prev, [employeeNo]: value }));
  };

  useEffect(() => {
    const fetchEmpleados = async () => {
      try {
        const { data } = await rrhhAPI.listarEmpleados({ page_size: 200, estado: 'activo' });
        setEmpleados(Array.isArray(data) ? data : data.items || []);
      } catch {
        setEmpleados([]);
      }
    };
    fetchEmpleados();
  }, []);

  // ── Fetch fichadas ──
  const cargarFichadas = useCallback(async () => {
    setLoadingFichadas(true);
    try {
      const params = { page: fichadasPage, page_size: PAGE_SIZE, orden: fichadasOrden };
      if (filtroEmpleadoId) params.empleado_id = filtroEmpleadoId;
      if (filtroFechaDesde) params.fecha_desde = filtroFechaDesde;
      if (filtroFechaHasta) params.fecha_hasta = filtroFechaHasta;
      if (filtroOrigen) params.origen = filtroOrigen;
      const { data } = await rrhhAPI.listarFichadas(params);
      setFichadas(data.items || []);
      setFichadasTotal(data.total || 0);
    } catch {
      setFichadas([]);
      setFichadasTotal(0);
    } finally {
      setLoadingFichadas(false);
    }
  }, [fichadasPage, fichadasOrden, filtroEmpleadoId, filtroFechaDesde, filtroFechaHasta, filtroOrigen]);

  useEffect(() => {
    if (activeTab === 'fichadas') cargarFichadas();
  }, [activeTab, cargarFichadas]);

  // ── Fetch horarios ──
  const cargarHorarios = useCallback(async () => {
    setLoadingHorarios(true);
    try {
      const { data } = await rrhhAPI.listarHorarios({ solo_activos: false });
      setHorarios(Array.isArray(data) ? data : []);
    } catch {
      setHorarios([]);
    } finally {
      setLoadingHorarios(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'horarios') cargarHorarios();
  }, [activeTab, cargarHorarios]);

  // ── Fetch excepciones ──
  const cargarExcepciones = useCallback(async () => {
    setLoadingExcepciones(true);
    try {
      const params = {};
      if (filtroAnioExcep) params.anio = parseInt(filtroAnioExcep, 10);
      const { data } = await rrhhAPI.listarExcepciones(params);
      setExcepciones(Array.isArray(data) ? data : []);
    } catch {
      setExcepciones([]);
    } finally {
      setLoadingExcepciones(false);
    }
  }, [filtroAnioExcep]);

  useEffect(() => {
    if (activeTab === 'excepciones') cargarExcepciones();
  }, [activeTab, cargarExcepciones]);

  // ── Fetch Hikvision users from LOCAL CACHE (fast, no ISAPI call) ──
  const cargarHikUsersCache = useCallback(async () => {
    try {
      const { data } = await rrhhAPI.listarUsuariosHikvisionCache();
      setHikUsers(Array.isArray(data) ? data : []);
    } catch {
      setHikUsers([]);
    }
  }, []);

  // Cargar cache al montar (nombres Hikvision para fichadas + tab mapeo)
  useEffect(() => {
    cargarHikUsersCache();
  }, [cargarHikUsersCache]);

  // ── Fetch Hikvision users from DEVICE (ISAPI call — manual only) ──
  const [syncingUsers, setSyncingUsers] = useState(false);
  const [syncUsersResult, setSyncUsersResult] = useState(null);

  const handleSyncHikUsers = async () => {
    setSyncingUsers(true);
    setHikError(null);
    setSyncUsersResult(null);
    try {
      const { data } = await rrhhAPI.syncUsuariosHikvision();
      setSyncUsersResult(data);
      cargarHikUsersCache();
    } catch (err) {
      setHikError(getErrorMessage(err, 'Error al sincronizar con Hikvision'));
    } finally {
      setSyncingUsers(false);
    }
  };

  // Legacy: cargarHikUsers for tab that needs fresh ISAPI data for mapping
  const cargarHikUsers = useCallback(async () => {
    setLoadingHik(true);
    setHikError(null);
    try {
      const { data } = await rrhhAPI.listarUsuariosHikvision();
      setHikUsers(Array.isArray(data) ? data : []);
    } catch (err) {
      setHikError(getErrorMessage(err, 'Error al conectar con Hikvision'));
      setHikUsers([]);
    } finally {
      setLoadingHik(false);
    }
  }, []);

  // Mapa employee_no → nombre Hikvision (para fichadas sin mapear)
  const hikNameMap = {};
  for (const u of hikUsers) {
    if (u.employee_no && u.name) hikNameMap[u.employee_no] = u.name;
  }

  // ── Handler: Fichada manual ──
  const handleOpenFichadaModal = () => {
    setFichadaForm({
      empleado_id: '', timestamp: '', tipo: 'entrada', motivo_manual: '',
    });
    setFichadaError(null);
    setFichadaModalOpen(true);
  };

  const handleSubmitFichada = async (e) => {
    e.preventDefault();
    setFichadaSaving(true);
    setFichadaError(null);
    try {
      await rrhhAPI.registrarFichadaManual({
        empleado_id: parseInt(fichadaForm.empleado_id, 10),
        timestamp: fichadaForm.timestamp,
        tipo: fichadaForm.tipo,
        motivo_manual: fichadaForm.motivo_manual,
      });
      setFichadaModalOpen(false);
      cargarFichadas();
    } catch (err) {
      setFichadaError(err.response?.data?.detail || 'Error al registrar fichada');
    } finally {
      setFichadaSaving(false);
    }
  };

  const handleDeleteFichada = (fichadaId) => {
    setActionError(null);
    setConfirmAction({
      title: 'Eliminar fichada',
      message: '¿Eliminar esta fichada manual? Esta acción no se puede deshacer.',
      onConfirm: async () => {
        try {
          await rrhhAPI.eliminarFichada(fichadaId);
          setConfirmAction(null);
          cargarFichadas();
        } catch (err) {
          setActionError(err.response?.data?.detail || 'Error al eliminar fichada');
        }
      },
    });
  };

  // ── Handler: Inline motivo edit ──
  const handleStartEditMotivo = (fichada) => {
    setEditingMotivoId(fichada.id);
    setEditingMotivoValue(fichada.motivo_manual || '');
  };

  const handleCancelEditMotivo = () => {
    setEditingMotivoId(null);
    setEditingMotivoValue('');
  };

  const handleSaveMotivo = async (fichadaId) => {
    if (!editingMotivoValue.trim()) return;
    setSavingMotivo(true);
    try {
      await rrhhAPI.actualizarMotivoFichada(fichadaId, {
        motivo_manual: editingMotivoValue.trim(),
      });
      setEditingMotivoId(null);
      setEditingMotivoValue('');
      cargarFichadas();
    } catch {
      setActionError('Error al actualizar motivo');
    } finally {
      setSavingMotivo(false);
    }
  };

  const handleToggleOrden = () => {
    setFichadasOrden((prev) => (prev === 'desc' ? 'asc' : 'desc'));
    setFichadasPage(1);
  };

  // ── Handler: Hikvision sync ──
  const handleSyncHikvision = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const { data } = await rrhhAPI.syncHikvision({});
      setSyncResult(data);
      cargarFichadas();
    } catch (err) {
      setSyncResult({ error: getErrorMessage(err, 'Error de conexión con Hikvision') });
    } finally {
      setSyncing(false);
    }
  };

  // ── Handler: Horario CRUD ──
  const handleOpenHorarioModal = (horario = null) => {
    if (horario) {
      setHorarioEditing(horario);
      setHorarioForm({
        nombre: horario.nombre,
        hora_entrada: formatTime(horario.hora_entrada),
        hora_salida: formatTime(horario.hora_salida),
        tolerancia_minutos: String(horario.tolerancia_minutos),
        dias_semana: horario.dias_semana,
        activo: horario.activo,
      });
    } else {
      setHorarioEditing(null);
      setHorarioForm({
        nombre: '', hora_entrada: '08:00', hora_salida: '17:00',
        tolerancia_minutos: '15', dias_semana: '1,2,3,4,5', activo: true,
      });
    }
    setHorarioError(null);
    setHorarioModalOpen(true);
  };

  const handleSubmitHorario = async (e) => {
    e.preventDefault();
    setHorarioSaving(true);
    setHorarioError(null);
    try {
      const payload = {
        nombre: horarioForm.nombre,
        hora_entrada: horarioForm.hora_entrada + ':00',
        hora_salida: horarioForm.hora_salida + ':00',
        tolerancia_minutos: parseInt(horarioForm.tolerancia_minutos, 10),
        dias_semana: horarioForm.dias_semana,
        activo: horarioForm.activo,
      };
      if (horarioEditing) {
        await rrhhAPI.actualizarHorario(horarioEditing.id, payload);
      } else {
        await rrhhAPI.crearHorario(payload);
      }
      setHorarioModalOpen(false);
      cargarHorarios();
    } catch (err) {
      setHorarioError(err.response?.data?.detail || 'Error al guardar horario');
    } finally {
      setHorarioSaving(false);
    }
  };

  const handleDeleteHorario = (horarioId) => {
    setActionError(null);
    setConfirmAction({
      title: 'Desactivar horario',
      message: '¿Desactivar este horario? Los empleados asignados quedarán sin horario.',
      onConfirm: async () => {
        try {
          await rrhhAPI.eliminarHorario(horarioId);
          setConfirmAction(null);
          cargarHorarios();
        } catch (err) {
          setActionError(err.response?.data?.detail || 'Error al desactivar horario');
        }
      },
    });
  };

  // ── Handler: Empleados ↔ Horario (Turnos asignados) ──
  const cargarEmpleadosHorario = useCallback(async (horarioId) => {
    setLoadingEmpleadosHorario(true);
    setAsignacionError(null);
    try {
      const { data } = await rrhhAPI.listarEmpleadosHorario(horarioId);
      setEmpleadosHorario(Array.isArray(data) ? data : []);
    } catch {
      setEmpleadosHorario([]);
    } finally {
      setLoadingEmpleadosHorario(false);
    }
  }, []);

  const handleToggleEmpleadosHorario = (horarioId) => {
    if (expandedHorarioId === horarioId) {
      setExpandedHorarioId(null);
      setEmpleadosHorario([]);
      setAsignacionError(null);
    } else {
      setExpandedHorarioId(horarioId);
      setNuevoEmpleadoHorario('');
      setNuevaPrioridad('1');
      cargarEmpleadosHorario(horarioId);
    }
  };

  const handleAsignarEmpleado = async (horarioId) => {
    if (!nuevoEmpleadoHorario) return;
    setAsignandoEmpleado(true);
    setAsignacionError(null);
    try {
      await rrhhAPI.asignarHorarioEmpleado(parseInt(nuevoEmpleadoHorario, 10), {
        horario_config_id: horarioId,
        prioridad: parseInt(nuevaPrioridad, 10),
      });
      setNuevoEmpleadoHorario('');
      setNuevaPrioridad('1');
      cargarEmpleadosHorario(horarioId);
    } catch (err) {
      setAsignacionError(getErrorMessage(err, 'Error al asignar empleado'));
    } finally {
      setAsignandoEmpleado(false);
    }
  };

  const handleDesasignarEmpleado = (asignacionId, nombreEmpleado, horarioId) => {
    setActionError(null);
    setConfirmAction({
      title: 'Desasignar empleado',
      message: `¿Quitar a ${nombreEmpleado} de este turno?`,
      onConfirm: async () => {
        try {
          await rrhhAPI.desasignarHorarioEmpleado(asignacionId);
          setConfirmAction(null);
          cargarEmpleadosHorario(horarioId);
        } catch (err) {
          setActionError(getErrorMessage(err, 'Error al desasignar'));
        }
      },
    });
  };

  // ── Handler: Excepción CRUD ──
  const handleOpenExcepModal = (excep = null) => {
    if (excep) {
      setExcepEditing(excep);
      setExcepForm({
        fecha: excep.fecha,
        tipo: excep.tipo,
        descripcion: excep.descripcion,
        es_laborable: excep.es_laborable,
      });
    } else {
      setExcepEditing(null);
      setExcepForm({
        fecha: '', tipo: 'feriado', descripcion: '', es_laborable: false,
      });
    }
    setExcepError(null);
    setExcepModalOpen(true);
  };

  const handleSubmitExcep = async (e) => {
    e.preventDefault();
    setExcepSaving(true);
    setExcepError(null);
    try {
      const payload = {
        fecha: excepForm.fecha,
        tipo: excepForm.tipo,
        descripcion: excepForm.descripcion,
        es_laborable: excepForm.es_laborable,
      };
      if (excepEditing) {
        await rrhhAPI.actualizarExcepcion(excepEditing.id, {
          tipo: payload.tipo,
          descripcion: payload.descripcion,
          es_laborable: payload.es_laborable,
        });
      } else {
        await rrhhAPI.crearExcepcion(payload);
      }
      setExcepModalOpen(false);
      cargarExcepciones();
    } catch (err) {
      setExcepError(err.response?.data?.detail || 'Error al guardar excepción');
    } finally {
      setExcepSaving(false);
    }
  };

  const handleDeleteExcep = (excepId) => {
    setActionError(null);
    setConfirmAction({
      title: 'Eliminar excepción',
      message: '¿Eliminar esta excepción del calendario?',
      onConfirm: async () => {
        try {
          await rrhhAPI.eliminarExcepcion(excepId);
          setConfirmAction(null);
          cargarExcepciones();
        } catch (err) {
          setActionError(err.response?.data?.detail || 'Error al eliminar excepción');
        }
      },
    });
  };

  // ── Handler: Hikvision mapping ──
  const handleMapearHikvision = async (hikEmployeeNo) => {
    const selectedId = mappingSelections[hikEmployeeNo];
    if (!selectedId) return;
    try {
      await rrhhAPI.mapearEmpleadoHikvision({
        empleado_id: parseInt(selectedId, 10),
        hikvision_employee_no: hikEmployeeNo,
      });
      setMappingSelections((prev) => {
        const next = { ...prev };
        delete next[hikEmployeeNo];
        return next;
      });
      cargarHikUsers();
    } catch (err) {
      setHikError(err.response?.data?.detail || 'Error al vincular');
    }
  };

  const handleDesmapearHikvision = (empleadoId) => {
    setActionError(null);
    setConfirmAction({
      title: 'Desvincular empleado',
      message: '¿Desvincular este empleado del dispositivo Hikvision?',
      onConfirm: async () => {
        try {
          await rrhhAPI.desmapearEmpleadoHikvision(empleadoId);
          setConfirmAction(null);
          cargarHikUsers();
        } catch (err) {
          setActionError(err.response?.data?.detail || 'Error al desvincular');
        }
      },
    });
  };

  // ── RENDER ──
  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Clock size={24} />
          <h1>Horarios y Fichadas</h1>
        </div>
        <div className={styles.headerActions}>
          {puedeGestionar && activeTab === 'fichadas' && (
            <>
              <button className={styles.btnSync} onClick={handleSyncHikvision} disabled={syncing}>
                <Fingerprint size={16} /> {syncing ? 'Sincronizando...' : 'Sync Hikvision'}
              </button>
              <button className={styles.btnCreate} onClick={handleOpenFichadaModal}>
                <Plus size={16} /> Fichada Manual
              </button>
            </>
          )}
          {puedeConfig && activeTab === 'horarios' && (
            <button className={styles.btnCreate} onClick={() => handleOpenHorarioModal()}>
              <Plus size={16} /> Nuevo Horario
            </button>
          )}
          {puedeConfig && activeTab === 'excepciones' && (
            <button className={styles.btnCreate} onClick={() => handleOpenExcepModal()}>
              <Plus size={16} /> Nueva Excepción
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className={styles.tabs}>
        {tienePermiso('rrhh.ver') && (
          <button
            className={`${styles.tab} ${activeTab === 'fichadas' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('fichadas')}
          >
            <Fingerprint size={16} /> Fichadas
          </button>
        )}
        {tienePermiso('rrhh.ver') && (
          <button
            className={`${styles.tab} ${activeTab === 'horarios' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('horarios')}
          >
            <Settings size={16} /> Horarios
          </button>
        )}
        {tienePermiso('rrhh.ver') && (
          <button
            className={`${styles.tab} ${activeTab === 'excepciones' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('excepciones')}
          >
            <CalendarOff size={16} /> Excepciones
          </button>
        )}
        {puedeGestionar && (
          <button
            className={`${styles.tab} ${activeTab === 'hikvision' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('hikvision')}
          >
            <Link size={16} /> Hikvision
          </button>
        )}
      </div>

      {/* ─── TAB: Fichadas ─── */}
      {activeTab === 'fichadas' && (
        <>
          {/* Sync result */}
          {syncResult && (
            <div className={styles.syncResult}>
              {syncResult.error ? (
                <p style={{ color: 'var(--cf-accent-red)' }}>{syncResult.error}</p>
              ) : (
                <>
                  <p><strong>Nuevas:</strong> {syncResult.nuevas}</p>
                  <p><strong>Duplicadas:</strong> {syncResult.duplicadas}</p>
                  <p><strong>Sin empleado:</strong> {syncResult.sin_empleado}</p>
                  <p><strong>Errores:</strong> {syncResult.errores}</p>
                </>
              )}
            </div>
          )}

          {/* Filters */}
          <div className={styles.filters}>
            <select
              className={styles.select}
              value={filtroEmpleadoId}
              onChange={(e) => { setFiltroEmpleadoId(e.target.value); setFichadasPage(1); }}
            >
              <option value="">Todos los empleados</option>
              {empleados.map((emp) => (
                <option key={emp.id} value={emp.id}>
                  {emp.legajo} - {emp.apellido}, {emp.nombre}
                </option>
              ))}
            </select>
            <input
              className={styles.input}
              type="date"
              value={filtroFechaDesde}
              onChange={(e) => { setFiltroFechaDesde(e.target.value); setFichadasPage(1); }}
              title="Fecha desde"
            />
            <input
              className={styles.input}
              type="date"
              value={filtroFechaHasta}
              onChange={(e) => { setFiltroFechaHasta(e.target.value); setFichadasPage(1); }}
              title="Fecha hasta"
            />
            <select
              className={styles.select}
              value={filtroOrigen}
              onChange={(e) => { setFiltroOrigen(e.target.value); setFichadasPage(1); }}
            >
              <option value="">Todos los orígenes</option>
              <option value="hikvision">Hikvision</option>
              <option value="manual">Manual</option>
            </select>
            <button
              className={styles.btnSort}
              onClick={handleToggleOrden}
              title={`Orden: ${fichadasOrden === 'desc' ? 'Más recientes primero' : 'Más antiguas primero'}`}
            >
              <ArrowUpDown size={14} />
              {fichadasOrden === 'desc' ? 'Recientes' : 'Antiguas'}
            </button>
            <button className={styles.btnRefresh} onClick={cargarFichadas} title="Refrescar">
              <RefreshCw size={16} />
            </button>
          </div>

          {loadingFichadas ? (
            <div className={styles.loading}>Cargando fichadas...</div>
          ) : fichadas.length === 0 ? (
            <div className={styles.empty}>No hay fichadas registradas</div>
          ) : (
            <div className={styles.tableContainer}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Fichada</th>
                    <th>Empleado</th>
                    <th>Origen</th>
                    <th>Ubic.</th>
                    <th>Hs Día</th>
                    <th>Motivo</th>
                    {puedeGestionar && <th>Acciones</th>}
                  </tr>
                </thead>
                <tbody>
                  {fichadas.map((f) => (
                    <tr key={f.id}>
                      <td className={styles.cellFecha}>{formatFichadaDate(f.timestamp)}</td>
                      <td>
                        <div className={styles.fichadaCell}>
                          <span className={f.tipo === 'entrada' ? styles.badgeEntrada : styles.badgeSalida}>
                            {f.tipo === 'entrada' ? <LogIn size={12} /> : <LogOut size={12} />}
                            {' '}{f.tipo}
                          </span>
                          <span
                            className={styles[PUNTUALIDAD_STYLE[f.puntualidad]] || styles.fichadaHora}
                            title={f.minutos_tarde > 0 ? `${f.minutos_tarde} min tarde` : undefined}
                          >
                            {formatFichadaTime(f.timestamp)}
                          </span>
                        </div>
                      </td>
                      <td>
                        <div className={styles.empleadoCell}>
                          {f.empleado_nombre ? (
                            <>
                              <span>{f.empleado_nombre}</span>
                              <span className={styles.empleadoLegajo}>{f.empleado_legajo}</span>
                            </>
                          ) : (
                            <>
                              <span className={styles.empleadoSinMapear}>
                                {f.hikvision_employee_no && hikNameMap[f.hikvision_employee_no]
                                  ? hikNameMap[f.hikvision_employee_no]
                                  : 'Sin mapear'}
                              </span>
                              {f.hikvision_employee_no && (
                                <span className={styles.empleadoLegajo}>
                                  Hik #{f.hikvision_employee_no}
                                </span>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                      <td>
                        <span className={f.origen === 'hikvision' ? styles.badgeHikvision : (f.origen === 'mobile' ? styles.badgeMobile : styles.badgeManual)}>
                          {f.origen}
                        </span>
                      </td>
                      <td>
                        {f.latitud != null && f.longitud != null ? (
                          <a
                            href={`https://www.google.com/maps?q=${f.latitud},${f.longitud}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={styles.geoLink}
                            title={f.distancia_oficina_metros != null
                              ? `A ${Math.round(f.distancia_oficina_metros)}m de la oficina`
                              : 'Ver en Google Maps'}
                          >
                            <MapPin size={14} />
                            {f.distancia_oficina_metros != null && (
                              <span className={styles.geoDistance}>
                                {f.distancia_oficina_metros < 1000
                                  ? `${Math.round(f.distancia_oficina_metros)}m`
                                  : `${(f.distancia_oficina_metros / 1000).toFixed(1)}km`}
                              </span>
                            )}
                          </a>
                        ) : (
                          <span style={{ color: 'var(--cf-text-tertiary)' }}>-</span>
                        )}
                      </td>
                      <td className={styles.cellHoras}>
                        {f.horas_dia != null ? (
                          <span className={styles.horasValue}>
                            <Timer size={12} />
                            {formatHorasDia(f.horas_dia)}
                          </span>
                        ) : '-'}
                      </td>
                      <td className={styles.cellMotivo}>
                        {editingMotivoId === f.id ? (
                          <div className={styles.motivoEditRow}>
                            <input
                              className={styles.motivoInput}
                              type="text"
                              value={editingMotivoValue}
                              onChange={(e) => setEditingMotivoValue(e.target.value)}
                              maxLength={500}
                              autoFocus
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') handleSaveMotivo(f.id);
                                if (e.key === 'Escape') handleCancelEditMotivo();
                              }}
                            />
                            <button
                              className={styles.btnMotivoSave}
                              onClick={() => handleSaveMotivo(f.id)}
                              disabled={savingMotivo || !editingMotivoValue.trim()}
                              title="Guardar"
                            >
                              <Check size={14} />
                            </button>
                            <button
                              className={styles.btnMotivoCancel}
                              onClick={handleCancelEditMotivo}
                              title="Cancelar"
                            >
                              <X size={14} />
                            </button>
                          </div>
                        ) : (
                          <div className={styles.motivoDisplay}>
                            <span className={styles.motivoText}>
                              {f.motivo_manual || (f.device_serial ? `Device: ${f.device_serial}` : '-')}
                            </span>
                            {puedeGestionar && (
                              <button
                                className={styles.btnMotivoEdit}
                                onClick={() => handleStartEditMotivo(f)}
                                title="Editar motivo"
                              >
                                <Edit2 size={12} />
                              </button>
                            )}
                            {f.registrado_por_nombre && (
                              <div className={styles.motivoMeta}>
                                Por: {f.registrado_por_nombre}
                              </div>
                            )}
                          </div>
                        )}
                      </td>
                      {puedeGestionar && (
                        <td>
                          {f.origen === 'manual' && (
                            <button
                              className={styles.btnDeleteAction}
                              onClick={() => handleDeleteFichada(f.id)}
                              title="Eliminar fichada"
                            >
                              <Trash2 size={14} />
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
              {fichadasTotal > PAGE_SIZE && (
                <div className={styles.pagination}>
                  <span className={styles.paginationInfo}>
                    Mostrando {Math.min(fichadasPage * PAGE_SIZE, fichadasTotal)} de {fichadasTotal}
                  </span>
                  <div className={styles.paginationButtons}>
                    <button
                      className={styles.btnPage}
                      disabled={fichadasPage <= 1}
                      onClick={() => setFichadasPage((p) => p - 1)}
                    >
                      Anterior
                    </button>
                    <button
                      className={styles.btnPage}
                      disabled={fichadasPage * PAGE_SIZE >= fichadasTotal}
                      onClick={() => setFichadasPage((p) => p + 1)}
                    >
                      Siguiente
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* ─── TAB: Horarios ─── */}
      {activeTab === 'horarios' && (
        <>
          {loadingHorarios ? (
            <div className={styles.loading}>Cargando horarios...</div>
          ) : horarios.length === 0 ? (
            <div className={styles.empty}>No hay horarios configurados</div>
          ) : (
            <div className={styles.horariosGrid}>
              {horarios.map((h) => (
                <div key={h.id} className={styles.horarioCard}>
                  <div className={styles.horarioCardHeader}>
                    <h3 className={styles.horarioCardTitle}>{h.nombre}</h3>
                    <span className={h.activo ? styles.badgeActivo : styles.badgeInactivo}>
                      {h.activo ? 'Activo' : 'Inactivo'}
                    </span>
                  </div>
                  <div className={styles.horarioTime}>
                    {formatTime(h.hora_entrada)} - {formatTime(h.hora_salida)}
                  </div>
                  <div className={styles.horarioCardDetail}>
                    <Clock size={14} />
                    Tolerancia: {h.tolerancia_minutos} min
                  </div>
                  <div className={styles.horarioCardDetail}>
                    <CalendarOff size={14} />
                    Días: {formatDiasSemana(h.dias_semana)}
                  </div>
                  <div className={styles.horarioCardActions}>
                    <button
                      className={styles.btnEmpleados}
                      onClick={() => handleToggleEmpleadosHorario(h.id)}
                    >
                      <Users size={12} />
                      {expandedHorarioId === h.id ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                      Empleados
                    </button>
                    {puedeConfig && (
                      <>
                        <button
                          className={styles.btnEdit}
                          onClick={() => handleOpenHorarioModal(h)}
                        >
                          <Edit2 size={12} /> Editar
                        </button>
                        {h.activo && (
                          <button
                            className={styles.btnDeactivate}
                            onClick={() => handleDeleteHorario(h.id)}
                            title="Desactivar horario"
                          >
                            <Trash2 size={12} /> Desactivar
                          </button>
                        )}
                      </>
                    )}
                  </div>

                  {/* Empleados asignados (expandible) */}
                  {expandedHorarioId === h.id && (
                    <div className={styles.empleadosSection}>
                      {asignacionError && (
                        <div className={styles.formError}>{asignacionError}</div>
                      )}

                      {loadingEmpleadosHorario ? (
                        <div className={styles.empleadosLoading}>Cargando empleados...</div>
                      ) : empleadosHorario.length === 0 ? (
                        <div className={styles.empleadosEmpty}>
                          Sin empleados asignados a este turno
                        </div>
                      ) : (
                        <ul className={styles.empleadosList}>
                          {empleadosHorario.map((a) => (
                            <li key={a.asignacion_id} className={styles.empleadoItem}>
                              <div className={styles.empleadoItemInfo}>
                                <span className={styles.empleadoItemLegajo}>{a.legajo}</span>
                                <span className={styles.empleadoItemNombre}>{a.nombre_completo}</span>
                                {a.prioridad > 1 && (
                                  <span className={styles.empleadoItemPrioridad}>
                                    P{a.prioridad}
                                  </span>
                                )}
                              </div>
                              {puedeGestionar && (
                                <button
                                  className={styles.btnDesasignar}
                                  onClick={() => handleDesasignarEmpleado(a.asignacion_id, a.nombre_completo, h.id)}
                                  title="Desasignar"
                                >
                                  <UserMinus size={12} />
                                </button>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}

                      {puedeGestionar && h.activo && (
                        <div className={styles.asignarRow}>
                          <select
                            className={styles.select}
                            value={nuevoEmpleadoHorario}
                            onChange={(e) => setNuevoEmpleadoHorario(e.target.value)}
                          >
                            <option value="">Asignar empleado...</option>
                            {empleados
                              .filter((emp) => !empleadosHorario.some((a) => a.empleado_id === emp.id))
                              .map((emp) => (
                                <option key={emp.id} value={emp.id}>
                                  {emp.legajo} - {emp.apellido}, {emp.nombre}
                                </option>
                              ))}
                          </select>
                          <select
                            className={styles.select}
                            value={nuevaPrioridad}
                            onChange={(e) => setNuevaPrioridad(e.target.value)}
                            title="Prioridad (1 = principal)"
                            style={{ width: '70px' }}
                          >
                            <option value="1">P1</option>
                            <option value="2">P2</option>
                            <option value="3">P3</option>
                          </select>
                          <button
                            className={styles.btnAsignar}
                            onClick={() => handleAsignarEmpleado(h.id)}
                            disabled={!nuevoEmpleadoHorario || asignandoEmpleado}
                            title="Asignar"
                          >
                            <UserPlus size={14} />
                            {asignandoEmpleado ? '...' : 'Asignar'}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* ─── TAB: Excepciones ─── */}
      {activeTab === 'excepciones' && (
        <>
          <div className={styles.filters}>
            <input
              className={styles.input}
              type="number"
              min="2020"
              max="2100"
              value={filtroAnioExcep}
              onChange={(e) => setFiltroAnioExcep(e.target.value)}
              placeholder="Año"
              style={{ width: '100px' }}
            />
            <button className={styles.btnRefresh} onClick={cargarExcepciones} title="Refrescar">
              <RefreshCw size={16} />
            </button>
          </div>

          {loadingExcepciones ? (
            <div className={styles.loading}>Cargando excepciones...</div>
          ) : excepciones.length === 0 ? (
            <div className={styles.empty}>No hay excepciones para {filtroAnioExcep}</div>
          ) : (
            <div className={styles.tableContainer}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Tipo</th>
                    <th>Descripción</th>
                    <th>Laborable</th>
                    {puedeConfig && <th>Acciones</th>}
                  </tr>
                </thead>
                <tbody>
                  {excepciones.map((exc) => (
                    <tr key={exc.id}>
                      <td>{formatDate(exc.fecha)}</td>
                      <td>
                        <span className={exc.tipo === 'feriado' ? styles.badgeFeriado : styles.badgeDiaEspecial}>
                          {exc.tipo === 'feriado' ? 'Feriado' : 'Día especial'}
                        </span>
                      </td>
                      <td>{exc.descripcion}</td>
                      <td>{exc.es_laborable ? 'Sí' : 'No'}</td>
                      {puedeConfig && (
                        <td>
                          <button
                            className={styles.btnEditAction}
                            onClick={() => handleOpenExcepModal(exc)}
                            title="Editar"
                          >
                            <Edit2 size={14} />
                          </button>
                          <button
                            className={styles.btnDeleteAction}
                            onClick={() => handleDeleteExcep(exc.id)}
                            title="Eliminar"
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ─── TAB: Hikvision Mapping ─── */}
      {activeTab === 'hikvision' && (
        <>
          <p style={{ fontSize: 'var(--font-sm)', color: 'var(--cf-text-secondary)', marginBottom: 'var(--spacing-md)' }}>
            Vincular usuarios del dispositivo Hikvision con empleados de la app.
            Usá &quot;Sync dispositivo&quot; cuando registres un empleado nuevo en el Hikvision.
          </p>

          {hikError && <div className={styles.error}>{hikError}</div>}
          {syncUsersResult && (
            <div className={styles.syncResultPanel}>
              Sync completado: {syncUsersResult.total_dispositivo} usuarios en dispositivo,
              {' '}{syncUsersResult.nuevos} nuevos, {syncUsersResult.actualizados} actualizados.
            </div>
          )}

          <div className={styles.filters}>
            <button
              className={styles.btnCreate}
              onClick={handleSyncHikUsers}
              disabled={syncingUsers}
              title="Consultar dispositivo Hikvision y actualizar cache local"
            >
              <RefreshCw size={16} className={syncingUsers ? styles.spinning : ''} />
              {syncingUsers ? 'Sincronizando...' : 'Sync dispositivo'}
            </button>
            <button className={styles.btnRefresh} onClick={cargarHikUsers} title="Refrescar desde dispositivo (ISAPI directo)">
              <RefreshCw size={16} />
            </button>
          </div>

          {loadingHik ? (
            <div className={styles.loading}>Conectando con Hikvision...</div>
          ) : hikUsers.length === 0 && !hikError ? (
            <div className={styles.empty}>No hay usuarios en cache. Usá &quot;Sync dispositivo&quot; para cargar.</div>
          ) : (
            <div className={styles.tableContainer}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>ID Hikvision</th>
                    <th>Nombre en dispositivo</th>
                    <th>Tipo</th>
                    <th>Empleado vinculado</th>
                    <th>Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {hikUsers.map((u) => (
                    <tr key={u.employee_no}>
                      <td><strong>{u.employee_no}</strong></td>
                      <td>{u.name}</td>
                      <td>{u.user_type}</td>
                      <td>
                        {u.empleado_nombre ? (
                          <span className={styles.badgeActivo}>
                            <Link size={12} /> {u.empleado_nombre}
                          </span>
                        ) : (
                          <span className={styles.badgeInactivo}>Sin vincular</span>
                        )}
                      </td>
                      <td>
                        {u.empleado_id ? (
                          <button
                            className={styles.btnUnlink}
                            onClick={() => handleDesmapearHikvision(u.empleado_id)}
                            title="Desvincular"
                          >
                            <Unlink size={14} />
                          </button>
                        ) : (
                          <div style={{ display: 'flex', gap: 'var(--spacing-xs)', alignItems: 'center' }}>
                            <select
                              className={styles.select}
                              value={mappingSelections[u.employee_no] || ''}
                              onChange={(e) => updateMappingSelection(u.employee_no, e.target.value)}
                              style={{ minWidth: '200px' }}
                            >
                              <option value="">Seleccionar empleado...</option>
                              {empleados
                                .filter((emp) => !hikUsers.some((hu) => hu.empleado_id === emp.id))
                                .map((emp) => (
                                  <option key={emp.id} value={emp.id}>
                                    {emp.legajo} - {emp.apellido}, {emp.nombre}
                                  </option>
                                ))}
                            </select>
                            <button
                              className={styles.btnLink}
                              onClick={() => handleMapearHikvision(u.employee_no)}
                              disabled={!mappingSelections[u.employee_no]}
                              title="Vincular"
                            >
                              <Link size={12} /> Vincular
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ─── MODAL: Fichada Manual ─── */}
      {fichadaModalOpen && (
        <div className="modal-overlay-tesla" onClick={() => setFichadaModalOpen(false)}>
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Fichada Manual</h2>
              <button className="btn-close-tesla" onClick={() => setFichadaModalOpen(false)} aria-label="Cerrar">✕</button>
            </div>
            <form onSubmit={handleSubmitFichada}>
              <div className="modal-body-tesla">
                {fichadaError && <div className={styles.formError}>{fichadaError}</div>}
                <div className={styles.formGroup}>
                  <label>Empleado</label>
                  <select
                    className={styles.select}
                    value={fichadaForm.empleado_id}
                    onChange={(e) => setFichadaForm({ ...fichadaForm, empleado_id: e.target.value })}
                    required
                  >
                    <option value="">Seleccionar...</option>
                    {empleados.map((emp) => (
                      <option key={emp.id} value={emp.id}>
                        {emp.legajo} - {emp.apellido}, {emp.nombre}
                      </option>
                    ))}
                  </select>
                </div>
                <div className={styles.formGroup}>
                  <label>Fecha y hora</label>
                  <input
                    className={styles.input}
                    type="datetime-local"
                    value={fichadaForm.timestamp}
                    onChange={(e) => setFichadaForm({ ...fichadaForm, timestamp: e.target.value })}
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Tipo</label>
                  <select
                    className={styles.select}
                    value={fichadaForm.tipo}
                    onChange={(e) => setFichadaForm({ ...fichadaForm, tipo: e.target.value })}
                  >
                    <option value="entrada">Entrada</option>
                    <option value="salida">Salida</option>
                  </select>
                </div>
                <div className={styles.formGroup}>
                  <label>Motivo</label>
                  <textarea
                    className={styles.textarea}
                    value={fichadaForm.motivo_manual}
                    onChange={(e) => setFichadaForm({ ...fichadaForm, motivo_manual: e.target.value })}
                    maxLength={500}
                    placeholder="Razón de la fichada manual"
                    required
                  />
                </div>
              </div>
              <div className="modal-footer-tesla">
                <button
                  type="button"
                  className={styles.btnCancel}
                  onClick={() => setFichadaModalOpen(false)}
                >
                  Cancelar
                </button>
                <button type="submit" className={styles.btnSave} disabled={fichadaSaving}>
                  {fichadaSaving ? 'Guardando...' : 'Registrar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ─── MODAL: Horario ─── */}
      {horarioModalOpen && (
        <div className="modal-overlay-tesla" onClick={() => setHorarioModalOpen(false)}>
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">{horarioEditing ? 'Editar Horario' : 'Nuevo Horario'}</h2>
              <button className="btn-close-tesla" onClick={() => setHorarioModalOpen(false)} aria-label="Cerrar">✕</button>
            </div>
            <form onSubmit={handleSubmitHorario}>
              <div className="modal-body-tesla">
                {horarioError && <div className={styles.formError}>{horarioError}</div>}
                <div className={styles.formGroup}>
                  <label>Nombre</label>
                  <input
                    className={styles.input}
                    type="text"
                    maxLength={100}
                    value={horarioForm.nombre}
                    onChange={(e) => setHorarioForm({ ...horarioForm, nombre: e.target.value })}
                    placeholder="Turno Mañana 8-17"
                    required
                  />
                </div>
                <div className={styles.formRow}>
                  <div className={styles.formGroup}>
                    <label>Hora entrada</label>
                    <input
                      className={styles.input}
                      type="time"
                      value={horarioForm.hora_entrada}
                      onChange={(e) => setHorarioForm({ ...horarioForm, hora_entrada: e.target.value })}
                      required
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label>Hora salida</label>
                    <input
                      className={styles.input}
                      type="time"
                      value={horarioForm.hora_salida}
                      onChange={(e) => setHorarioForm({ ...horarioForm, hora_salida: e.target.value })}
                      required
                    />
                  </div>
                </div>
                <div className={styles.formGroup}>
                  <label>Tolerancia (minutos)</label>
                  <input
                    className={styles.input}
                    type="number"
                    min="0"
                    max="120"
                    value={horarioForm.tolerancia_minutos}
                    onChange={(e) => setHorarioForm({ ...horarioForm, tolerancia_minutos: e.target.value })}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Días laborables (1=Lun ... 7=Dom)</label>
                  <input
                    className={styles.input}
                    type="text"
                    value={horarioForm.dias_semana}
                    onChange={(e) => setHorarioForm({ ...horarioForm, dias_semana: e.target.value })}
                    placeholder="1,2,3,4,5"
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-xs)' }}>
                    <input
                      type="checkbox"
                      checked={horarioForm.activo}
                      onChange={(e) => setHorarioForm({ ...horarioForm, activo: e.target.checked })}
                    />
                    Activo
                  </label>
                </div>
              </div>
              <div className="modal-footer-tesla">
                <button
                  type="button"
                  className={styles.btnCancel}
                  onClick={() => setHorarioModalOpen(false)}
                >
                  Cancelar
                </button>
                <button type="submit" className={styles.btnSave} disabled={horarioSaving}>
                  {horarioSaving ? 'Guardando...' : horarioEditing ? 'Actualizar' : 'Crear'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ─── MODAL: Excepción ─── */}
      {excepModalOpen && (
        <div className="modal-overlay-tesla" onClick={() => setExcepModalOpen(false)}>
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">{excepEditing ? 'Editar Excepción' : 'Nueva Excepción'}</h2>
              <button className="btn-close-tesla" onClick={() => setExcepModalOpen(false)} aria-label="Cerrar">✕</button>
            </div>
            <form onSubmit={handleSubmitExcep}>
              <div className="modal-body-tesla">
                {excepError && <div className={styles.formError}>{excepError}</div>}
                <div className={styles.formGroup}>
                  <label>Fecha</label>
                  <input
                    className={styles.input}
                    type="date"
                    value={excepForm.fecha}
                    onChange={(e) => setExcepForm({ ...excepForm, fecha: e.target.value })}
                    required
                    disabled={!!excepEditing}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Tipo</label>
                  <select
                    className={styles.select}
                    value={excepForm.tipo}
                    onChange={(e) => setExcepForm({ ...excepForm, tipo: e.target.value })}
                  >
                    <option value="feriado">Feriado</option>
                    <option value="dia_especial">Día especial</option>
                  </select>
                </div>
                <div className={styles.formGroup}>
                  <label>Descripción</label>
                  <input
                    className={styles.input}
                    type="text"
                    maxLength={255}
                    value={excepForm.descripcion}
                    onChange={(e) => setExcepForm({ ...excepForm, descripcion: e.target.value })}
                    placeholder="Día del Trabajador"
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-xs)' }}>
                    <input
                      type="checkbox"
                      checked={excepForm.es_laborable}
                      onChange={(e) => setExcepForm({ ...excepForm, es_laborable: e.target.checked })}
                    />
                    Es laborable (se trabaja igual)
                  </label>
                </div>
              </div>
              <div className="modal-footer-tesla">
                <button
                  type="button"
                  className={styles.btnCancel}
                  onClick={() => setExcepModalOpen(false)}
                >
                  Cancelar
                </button>
                <button type="submit" className={styles.btnSave} disabled={excepSaving}>
                  {excepSaving ? 'Guardando...' : excepEditing ? 'Actualizar' : 'Crear'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ─── MODAL: Confirmación ─── */}
      {confirmAction && (
        <div className="modal-overlay-tesla" onClick={() => setConfirmAction(null)}>
          <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">{confirmAction.title}</h2>
              <button className="btn-close-tesla" onClick={() => setConfirmAction(null)} aria-label="Cerrar">✕</button>
            </div>
            <div className="modal-body-tesla">
              <p style={{ color: 'var(--cf-text-secondary)', fontSize: 'var(--font-sm)' }}>
                {confirmAction.message}
              </p>
              {actionError && <div className={styles.formError}>{actionError}</div>}
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setConfirmAction(null)}>Cancelar</button>
              <button className={styles.btnDeactivate} onClick={confirmAction.onConfirm}>Confirmar</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
