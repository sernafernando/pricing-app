import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI } from '../services/api';
import { Palmtree, Plus, RefreshCw, Check, X, Ban, Calendar } from 'lucide-react';
import styles from './RRHHVacaciones.module.css';

const CURRENT_YEAR = new Date().getFullYear();

const STATUS_MAP = {
  pendiente: { label: 'Pendiente', className: 'statusPendiente' },
  aprobada: { label: 'Aprobada', className: 'statusAprobada' },
  rechazada: { label: 'Rechazada', className: 'statusRechazada' },
  cancelada: { label: 'Cancelada', className: 'statusCancelada' },
  gozada: { label: 'Gozada', className: 'statusGozada' },
};

const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
};

export default function RRHHVacaciones() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rrhh.gestionar');

  // ── Tab state ──
  const [activeTab, setActiveTab] = useState('periodos');

  // ── Periodos state ──
  const [periodos, setPeriodos] = useState([]);
  const [loadingPeriodos, setLoadingPeriodos] = useState(true);
  const [filtroPeriodoAnio, setFiltroPeriodoAnio] = useState(CURRENT_YEAR);

  // ── Generate state ──
  const [genAnio, setGenAnio] = useState(CURRENT_YEAR);
  const [genLoading, setGenLoading] = useState(false);
  const [genResult, setGenResult] = useState(null);

  // ── Solicitudes state ──
  const [solicitudes, setSolicitudes] = useState([]);
  const [totalSolicitudes, setTotalSolicitudes] = useState(0);
  const [loadingSolicitudes, setLoadingSolicitudes] = useState(true);
  const [filtroSolAnio, setFiltroSolAnio] = useState(CURRENT_YEAR);
  const [filtroSolEstado, setFiltroSolEstado] = useState('');
  const [solPage, setSolPage] = useState(1);
  const SOL_PAGE_SIZE = 50;

  // ── Empleados for selects ──
  const [empleados, setEmpleados] = useState([]);

  // ── Create modal ──
  const [crearModalOpen, setCrearModalOpen] = useState(false);
  const [crearForm, setCrearForm] = useState({
    empleado_id: '',
    periodo_id: '',
    fecha_desde: '',
    fecha_hasta: '',
  });
  const [crearSaving, setCrearSaving] = useState(false);
  const [crearError, setCrearError] = useState(null);
  const [empleadoPeriodos, setEmpleadoPeriodos] = useState([]);

  // ── Reject modal ──
  const [rechazarModalOpen, setRechazarModalOpen] = useState(false);
  const [rechazarSolicitudId, setRechazarSolicitudId] = useState(null);
  const [rechazarMotivo, setRechazarMotivo] = useState('');
  const [rechazarSaving, setRechazarSaving] = useState(false);

  // ── Fetch empleados (for selects) ──
  useEffect(() => {
    const fetchEmpleados = async () => {
      try {
        const { data } = await rrhhAPI.listarEmpleados({ page_size: 200, estado: 'activo' });
        setEmpleados(data.items || []);
      } catch {
        // silently fail, selects will be empty
      }
    };
    fetchEmpleados();
  }, []);

  // ── Fetch periodos ──
  const fetchPeriodos = useCallback(async () => {
    setLoadingPeriodos(true);
    try {
      const { data } = await rrhhAPI.listarVacacionesPeriodos({
        anio: filtroPeriodoAnio || undefined,
      });
      setPeriodos(data.items || []);
    } catch {
      setPeriodos([]);
    } finally {
      setLoadingPeriodos(false);
    }
  }, [filtroPeriodoAnio]);

  useEffect(() => {
    fetchPeriodos();
  }, [fetchPeriodos]);

  // ── Fetch solicitudes ──
  const fetchSolicitudes = useCallback(async () => {
    setLoadingSolicitudes(true);
    try {
      const { data } = await rrhhAPI.listarVacacionesSolicitudes({
        anio: filtroSolAnio || undefined,
        estado: filtroSolEstado || undefined,
        page: solPage,
        page_size: SOL_PAGE_SIZE,
      });
      setSolicitudes(data.items || []);
      setTotalSolicitudes(data.total || 0);
    } catch {
      setSolicitudes([]);
      setTotalSolicitudes(0);
    } finally {
      setLoadingSolicitudes(false);
    }
  }, [filtroSolAnio, filtroSolEstado, solPage]);

  useEffect(() => {
    fetchSolicitudes();
  }, [fetchSolicitudes]);

  // ── Generate periodos ──
  const handleGenerar = async () => {
    setGenLoading(true);
    setGenResult(null);
    try {
      const { data } = await rrhhAPI.generarPeriodos({ anio: genAnio });
      setGenResult(`${data.generados} generados, ${data.existentes} ya existentes`);
      fetchPeriodos();
    } catch (err) {
      setGenResult(`Error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setGenLoading(false);
    }
  };

  // ── Create solicitud ──
  const handleEmpleadoChange = async (empId) => {
    setCrearForm((prev) => ({ ...prev, empleado_id: empId, periodo_id: '' }));
    if (!empId) {
      setEmpleadoPeriodos([]);
      return;
    }
    try {
      const { data } = await rrhhAPI.listarVacacionesPeriodos({ empleado_id: empId });
      setEmpleadoPeriodos(data.items || []);
    } catch {
      setEmpleadoPeriodos([]);
    }
  };

  const handleCrear = async (e) => {
    e.preventDefault();
    setCrearSaving(true);
    setCrearError(null);
    try {
      await rrhhAPI.crearSolicitudVacaciones({
        empleado_id: Number(crearForm.empleado_id),
        periodo_id: Number(crearForm.periodo_id),
        fecha_desde: crearForm.fecha_desde,
        fecha_hasta: crearForm.fecha_hasta,
      });
      setCrearModalOpen(false);
      setCrearForm({ empleado_id: '', periodo_id: '', fecha_desde: '', fecha_hasta: '' });
      setEmpleadoPeriodos([]);
      fetchSolicitudes();
      fetchPeriodos();
    } catch (err) {
      setCrearError(err.response?.data?.detail || 'Error al crear solicitud');
    } finally {
      setCrearSaving(false);
    }
  };

  // ── Approve ──
  const handleAprobar = async (id) => {
    try {
      await rrhhAPI.aprobarSolicitud(id);
      fetchSolicitudes();
      fetchPeriodos();
    } catch {
      // error silently
    }
  };

  // ── Reject ──
  const openRechazar = (id) => {
    setRechazarSolicitudId(id);
    setRechazarMotivo('');
    setRechazarModalOpen(true);
  };

  const handleRechazar = async (e) => {
    e.preventDefault();
    setRechazarSaving(true);
    try {
      await rrhhAPI.rechazarSolicitud(rechazarSolicitudId, { motivo: rechazarMotivo });
      setRechazarModalOpen(false);
      fetchSolicitudes();
    } catch {
      // error silently
    } finally {
      setRechazarSaving(false);
    }
  };

  // ── Cancel ──
  const handleCancelar = async (id) => {
    try {
      await rrhhAPI.cancelarSolicitud(id);
      fetchSolicitudes();
      fetchPeriodos();
    } catch {
      // error silently
    }
  };

  // ── Year options for selects ──
  const yearOptions = [];
  for (let y = CURRENT_YEAR + 1; y >= CURRENT_YEAR - 5; y--) {
    yearOptions.push(y);
  }

  const totalSolPages = Math.ceil(totalSolicitudes / SOL_PAGE_SIZE);

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Palmtree size={24} />
          <h1>Vacaciones</h1>
        </div>
        {puedeGestionar && (
          <div className={styles.headerActions}>
            <button
              className={styles.btnCreate}
              onClick={() => {
                setCrearError(null);
                setCrearForm({ empleado_id: '', periodo_id: '', fecha_desde: '', fecha_hasta: '' });
                setEmpleadoPeriodos([]);
                setCrearModalOpen(true);
              }}
            >
              <Plus size={16} /> Nueva Solicitud
            </button>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className={styles.tabs}>
        <button
          className={activeTab === 'periodos' ? styles.tabActive : styles.tab}
          onClick={() => setActiveTab('periodos')}
        >
          <Calendar size={14} /> Periodos
        </button>
        <button
          className={activeTab === 'solicitudes' ? styles.tabActive : styles.tab}
          onClick={() => setActiveTab('solicitudes')}
        >
          <Palmtree size={14} /> Solicitudes
          {totalSolicitudes > 0 && <span className={styles.badge}>{totalSolicitudes}</span>}
        </button>
      </div>

      {/* ── TAB: Periodos ── */}
      {activeTab === 'periodos' && (
        <>
          {/* Generate card */}
          {puedeGestionar && (
            <div className={styles.generateCard}>
              <label>Generar periodos para:</label>
              <select
                className={styles.select}
                value={genAnio}
                onChange={(e) => setGenAnio(Number(e.target.value))}
              >
                {yearOptions.map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
              <button
                className={styles.btnGenerate}
                onClick={handleGenerar}
                disabled={genLoading}
              >
                <RefreshCw size={14} /> {genLoading ? 'Generando...' : 'Generar'}
              </button>
              {genResult && <span className={styles.generateResult}>{genResult}</span>}
            </div>
          )}

          {/* Periodo filters */}
          <div className={styles.filters}>
            <select
              className={styles.select}
              value={filtroPeriodoAnio}
              onChange={(e) => setFiltroPeriodoAnio(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">Todos los anos</option>
              {yearOptions.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>

          {/* Periodos table */}
          {loadingPeriodos ? (
            <div className={styles.loading}>Cargando periodos...</div>
          ) : periodos.length === 0 ? (
            <div className={styles.empty}>No hay periodos para mostrar</div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Empleado</th>
                  <th>Ano</th>
                  <th>Antiguedad</th>
                  <th>Dias Correspondientes</th>
                  <th>Dias Gozados</th>
                  <th>Dias Pendientes</th>
                  <th>Progreso</th>
                </tr>
              </thead>
              <tbody>
                {periodos.map((p) => {
                  const pct = p.dias_correspondientes > 0
                    ? Math.round((p.dias_gozados / p.dias_correspondientes) * 100)
                    : 0;
                  return (
                    <tr key={p.id}>
                      <td>{p.empleado_nombre || `#${p.empleado_id}`}</td>
                      <td>{p.anio}</td>
                      <td>{p.antiguedad_anios} {p.antiguedad_anios === 1 ? 'ano' : 'anos'}</td>
                      <td>{p.dias_correspondientes}</td>
                      <td>{p.dias_gozados}</td>
                      <td>{p.dias_pendientes}</td>
                      <td>
                        <div className={styles.daysProgress}>
                          <div className={styles.daysBar}>
                            <div
                              className={styles.daysBarFill}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className={styles.daysText}>{pct}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </>
      )}

      {/* ── TAB: Solicitudes ── */}
      {activeTab === 'solicitudes' && (
        <>
          {/* Solicitudes filters */}
          <div className={styles.filters}>
            <select
              className={styles.select}
              value={filtroSolAnio}
              onChange={(e) => { setFiltroSolAnio(e.target.value ? Number(e.target.value) : ''); setSolPage(1); }}
            >
              <option value="">Todos los anos</option>
              {yearOptions.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
            <select
              className={styles.select}
              value={filtroSolEstado}
              onChange={(e) => { setFiltroSolEstado(e.target.value); setSolPage(1); }}
            >
              <option value="">Todos los estados</option>
              <option value="pendiente">Pendiente</option>
              <option value="aprobada">Aprobada</option>
              <option value="rechazada">Rechazada</option>
              <option value="cancelada">Cancelada</option>
              <option value="gozada">Gozada</option>
            </select>
          </div>

          {/* Solicitudes table */}
          {loadingSolicitudes ? (
            <div className={styles.loading}>Cargando solicitudes...</div>
          ) : solicitudes.length === 0 ? (
            <div className={styles.empty}>No hay solicitudes para mostrar</div>
          ) : (
            <>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Empleado</th>
                    <th>Periodo</th>
                    <th>Desde</th>
                    <th>Hasta</th>
                    <th>Dias</th>
                    <th>Estado</th>
                    <th>Motivo Rechazo</th>
                    {puedeGestionar && <th>Acciones</th>}
                  </tr>
                </thead>
                <tbody>
                  {solicitudes.map((s) => {
                    const st = STATUS_MAP[s.estado] || { label: s.estado, className: 'statusBadge' };
                    return (
                      <tr key={s.id}>
                        <td>{s.empleado_nombre || `#${s.empleado_id}`}</td>
                        <td>{s.periodo_anio || '-'}</td>
                        <td>{formatDate(s.fecha_desde)}</td>
                        <td>{formatDate(s.fecha_hasta)}</td>
                        <td>{s.dias_solicitados}</td>
                        <td><span className={styles[st.className]}>{st.label}</span></td>
                        <td>{s.motivo_rechazo || '-'}</td>
                        {puedeGestionar && (
                          <td>
                            <div className={styles.actions}>
                              {s.estado === 'pendiente' && (
                                <>
                                  <button
                                    className={styles.btnApprove}
                                    onClick={() => handleAprobar(s.id)}
                                    title="Aprobar"
                                  >
                                    <Check size={14} /> Aprobar
                                  </button>
                                  <button
                                    className={styles.btnReject}
                                    onClick={() => openRechazar(s.id)}
                                    title="Rechazar"
                                  >
                                    <X size={14} /> Rechazar
                                  </button>
                                </>
                              )}
                              {(s.estado === 'pendiente' || s.estado === 'aprobada') && (
                                <button
                                  className={styles.btnCancelAction}
                                  onClick={() => handleCancelar(s.id)}
                                  title="Cancelar"
                                >
                                  <Ban size={14} /> Cancelar
                                </button>
                              )}
                            </div>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {/* Pagination */}
              {totalSolPages > 1 && (
                <div className={styles.filters} style={{ justifyContent: 'center', marginTop: 'var(--spacing-md)' }}>
                  <button
                    className={styles.btnPage}
                    onClick={() => setSolPage((p) => Math.max(1, p - 1))}
                    disabled={solPage <= 1}
                  >
                    Anterior
                  </button>
                  <span className={styles.daysText}>
                    Pagina {solPage} de {totalSolPages}
                  </span>
                  <button
                    className={styles.btnPage}
                    onClick={() => setSolPage((p) => Math.min(totalSolPages, p + 1))}
                    disabled={solPage >= totalSolPages}
                  >
                    Siguiente
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* ── Modal: Crear Solicitud ── */}
      {crearModalOpen && (
        <div className="modal-overlay-tesla" onClick={() => setCrearModalOpen(false)}>
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Nueva Solicitud de Vacaciones</h2>
              <button className="btn-close-tesla" onClick={() => setCrearModalOpen(false)} aria-label="Cerrar">✕</button>
            </div>
            <form onSubmit={handleCrear}>
              <div className="modal-body-tesla">
                {crearError && <div className={styles.errorMsg}>{crearError}</div>}

                <div className={styles.formGroup}>
                  <label>Empleado</label>
                  <select
                    className={styles.select}
                    value={crearForm.empleado_id}
                    onChange={(e) => handleEmpleadoChange(e.target.value)}
                    required
                  >
                    <option value="">Seleccionar empleado...</option>
                    {empleados.map((emp) => (
                      <option key={emp.id} value={emp.id}>
                        {emp.apellido}, {emp.nombre} ({emp.legajo})
                      </option>
                    ))}
                  </select>
                </div>

                <div className={styles.formGroup}>
                  <label>Periodo</label>
                  <select
                    className={styles.select}
                    value={crearForm.periodo_id}
                    onChange={(e) => setCrearForm((prev) => ({ ...prev, periodo_id: e.target.value }))}
                    required
                    disabled={!crearForm.empleado_id}
                  >
                    <option value="">Seleccionar periodo...</option>
                    {empleadoPeriodos.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.anio} - {p.dias_pendientes} dias pendientes de {p.dias_correspondientes}
                      </option>
                    ))}
                  </select>
                </div>

                <div className={styles.formRow}>
                  <div className={styles.formGroup}>
                    <label>Fecha Desde</label>
                    <input
                      type="date"
                      className={styles.input}
                      value={crearForm.fecha_desde}
                      onChange={(e) => setCrearForm((prev) => ({ ...prev, fecha_desde: e.target.value }))}
                      required
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label>Fecha Hasta</label>
                    <input
                      type="date"
                      className={styles.input}
                      value={crearForm.fecha_hasta}
                      onChange={(e) => setCrearForm((prev) => ({ ...prev, fecha_hasta: e.target.value }))}
                      required
                    />
                  </div>
                </div>
              </div>
              <div className="modal-footer-tesla">
                <button type="button" className={styles.btnCancel} onClick={() => setCrearModalOpen(false)}>
                  Cancelar
                </button>
                <button type="submit" className={styles.btnSave} disabled={crearSaving}>
                  {crearSaving ? 'Creando...' : 'Crear Solicitud'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Modal: Rechazar ── */}
      {rechazarModalOpen && (
        <div className="modal-overlay-tesla" onClick={() => setRechazarModalOpen(false)}>
          <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Rechazar Solicitud</h2>
              <button className="btn-close-tesla" onClick={() => setRechazarModalOpen(false)} aria-label="Cerrar">✕</button>
            </div>
            <form onSubmit={handleRechazar}>
              <div className="modal-body-tesla">
                <div className={styles.formGroup}>
                  <label>Motivo del rechazo</label>
                  <textarea
                    className={styles.textarea}
                    value={rechazarMotivo}
                    onChange={(e) => setRechazarMotivo(e.target.value)}
                    required
                    placeholder="Indique el motivo del rechazo..."
                  />
                </div>
              </div>
              <div className="modal-footer-tesla">
                <button type="button" className={styles.btnCancel} onClick={() => setRechazarModalOpen(false)}>
                  Cancelar
                </button>
                <button type="submit" className={styles.btnReject} disabled={rechazarSaving || !rechazarMotivo.trim()}>
                  {rechazarSaving ? 'Rechazando...' : 'Rechazar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
