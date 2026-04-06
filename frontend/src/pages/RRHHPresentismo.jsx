import { useState, useEffect, useCallback, useRef } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI } from '../services/api';
import {
  CalendarDays,
  ClipboardList,
  AlertTriangle,
  Plus,
  RotateCcw,
  Eye,
  Edit3,
  Download,
  FileText,
  CalendarRange,
  X,
} from 'lucide-react';
import styles from './RRHHPresentismo.module.css';

const ESTADOS_PRESENTISMO = [
  { value: 'presente', label: 'P', fullLabel: 'Presente' },
  { value: 'ausente', label: 'A', fullLabel: 'Ausente' },
  { value: 'home_office', label: 'HO', fullLabel: 'Home Office' },
  { value: 'vacaciones', label: 'V', fullLabel: 'Vacaciones' },
  { value: 'art', label: 'ART', fullLabel: 'ART' },
  { value: 'licencia', label: 'L', fullLabel: 'Licencia' },
  { value: 'franco', label: 'F', fullLabel: 'Franco' },
  { value: 'feriado', label: 'FE', fullLabel: 'Feriado' },
];

const ESTADO_STYLE_MAP = {
  presente: 'estadoPresente',
  ausente: 'estadoAusente',
  home_office: 'estadoHomeOffice',
  vacaciones: 'estadoVacaciones',
  art: 'estadoArt',
  licencia: 'estadoLicencia',
  franco: 'estadoFranco',
  feriado: 'estadoFeriado',
};

const ART_STATUS_MAP = {
  abierto: 'statusAbierto',
  en_tratamiento: 'statusEnTratamiento',
  alta_medica: 'statusAltaMedica',
  cerrado: 'statusCerrado',
};

const formatDateShort = (dateStr) => {
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit' });
};

const getWeekRange = () => {
  const now = new Date();
  const day = now.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  const monday = new Date(now);
  monday.setDate(now.getDate() + diff);
  const friday = new Date(monday);
  friday.setDate(monday.getDate() + 4);
  return {
    desde: monday.toISOString().slice(0, 10),
    hasta: friday.toISOString().slice(0, 10),
  };
};

export default function RRHHPresentismo() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rrhh.gestionar');

  const [activeTab, setActiveTab] = useState('presentismo');

  // --- Presentismo state ---
  const defaultRange = getWeekRange();
  const [fechaDesde, setFechaDesde] = useState(defaultRange.desde);
  const [fechaHasta, setFechaHasta] = useState(defaultRange.hasta);
  const [grilla, setGrilla] = useState({ fechas: [], empleados: [], total_empleados: 0 });
  const [loadingGrilla, setLoadingGrilla] = useState(true);

  // Quick-mark dropdown
  const [dropdown, setDropdown] = useState(null); // { empleadoId, fecha, x, y }
  const dropdownRef = useRef(null);

  // --- ART state ---
  const [artCasos, setArtCasos] = useState([]);
  const [loadingArt, setLoadingArt] = useState(false);
  const [artPage, setArtPage] = useState(1);
  const [artModalOpen, setArtModalOpen] = useState(false);
  const [artForm, setArtForm] = useState({});
  const [artSaving, setArtSaving] = useState(false);
  const [artFormError, setArtFormError] = useState(null);
  const [artDetalle, setArtDetalle] = useState(null);

  // --- Error feedback ---
  const [markError, setMarkError] = useState(null);

  // --- Motivo ausencia modal ---
  const [motivosAusencia, setMotivosAusencia] = useState([]);
  const [ausenteModal, setAusenteModal] = useState(null); // { empleadoId, fecha }
  const [ausenteForm, setAusenteForm] = useState({ motivo_ausencia_id: '', observaciones: '' });
  const [ausenteSaving, setAusenteSaving] = useState(false);

  // ── Range marking modal ──
  const [rangoModalOpen, setRangoModalOpen] = useState(false);
  const [rangoForm, setRangoForm] = useState({
    empleado_id: '',
    estado: 'vacaciones',
    fecha_desde: '',
    fecha_hasta: '',
    observaciones: '',
  });
  const [rangoSaving, setRangoSaving] = useState(false);
  const [rangoError, setRangoError] = useState(null);
  const [rangoSuccess, setRangoSuccess] = useState(null);

  // --- Empleados for ART select ---
  const [empleados, setEmpleados] = useState([]);

  // ── Fetch empleados + motivos ausencia ──
  useEffect(() => {
    const fetchEmpleados = async () => {
      try {
        const { data } = await rrhhAPI.listarEmpleados({ page_size: 200, estado: 'activo' });
        setEmpleados(Array.isArray(data) ? data : data.items || []);
      } catch {
        setEmpleados([]);
      }
    };
    const fetchMotivos = async () => {
      try {
        const { data } = await rrhhAPI.listarMotivosAusencia({ activo: true });
        setMotivosAusencia(Array.isArray(data) ? data : []);
      } catch {
        setMotivosAusencia([]);
      }
    };
    fetchEmpleados();
    fetchMotivos();
  }, []);

  // ── Fetch presentismo grid ──
  const cargarGrilla = useCallback(async () => {
    if (!fechaDesde || !fechaHasta) return;
    setLoadingGrilla(true);
    try {
      const { data } = await rrhhAPI.obtenerGrillaPresentismo({
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta,
      });
      setGrilla(data);
    } catch {
      setGrilla({ fechas: [], empleados: [], total_empleados: 0 });
    } finally {
      setLoadingGrilla(false);
    }
  }, [fechaDesde, fechaHasta]);

  useEffect(() => {
    if (activeTab === 'presentismo') cargarGrilla();
  }, [cargarGrilla, activeTab]);

  // ── Fetch ART casos ──
  const cargarArtCasos = useCallback(async () => {
    setLoadingArt(true);
    try {
      const { data } = await rrhhAPI.listarArtCasos({ page: artPage, page_size: 50 });
      setArtCasos(data.items);
    } catch {
      setArtCasos([]);
    } finally {
      setLoadingArt(false);
    }
  }, [artPage]);

  useEffect(() => {
    if (activeTab === 'art') cargarArtCasos();
  }, [cargarArtCasos, activeTab]);

  // ── Close dropdown on outside click ──
  useEffect(() => {
    const handleClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdown(null);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // ── Mark presentismo ──
  const handleCellClick = (empleadoId, fecha, event) => {
    if (!puedeGestionar) return;
    const rect = event.currentTarget.getBoundingClientRect();
    setDropdown({
      empleadoId,
      fecha,
      x: rect.left,
      y: rect.bottom + 4,
    });
  };

  const handleEstadoSelect = async (estado) => {
    if (!dropdown) return;
    const { empleadoId, fecha } = dropdown;
    setDropdown(null);

    // Si es "ausente", abrir modal de motivo en vez de marcar directo
    if (estado === 'ausente') {
      setAusenteForm({ motivo_ausencia_id: '', observaciones: '' });
      setAusenteModal({ empleadoId, fecha });
      return;
    }

    try {
      await rrhhAPI.marcarPresentismo(empleadoId, fecha, { estado });
      setGrilla((prev) => ({
        ...prev,
        empleados: prev.empleados.map((emp) =>
          emp.empleado_id === empleadoId
            ? { ...emp, dias: { ...emp.dias, [fecha]: { estado, origen: 'manual' } } }
            : emp
        ),
      }));
    } catch {
      setMarkError('Error al marcar presentismo. Intentá de nuevo.');
      setTimeout(() => setMarkError(null), 4000);
    }
  };

  const handleAusenteSubmit = async () => {
    if (!ausenteModal) return;
    const { empleadoId, fecha } = ausenteModal;
    setAusenteSaving(true);
    try {
      const payload = {
        estado: 'ausente',
        motivo_ausencia_id: ausenteForm.motivo_ausencia_id ? Number(ausenteForm.motivo_ausencia_id) : null,
        observaciones: ausenteForm.observaciones || null,
      };
      await rrhhAPI.marcarPresentismo(empleadoId, fecha, payload);
      const motivoNombre = motivosAusencia.find((m) => m.id === Number(ausenteForm.motivo_ausencia_id))?.nombre || null;
      setGrilla((prev) => ({
        ...prev,
        empleados: prev.empleados.map((emp) =>
          emp.empleado_id === empleadoId
            ? {
                ...emp,
                dias: {
                  ...emp.dias,
                  [fecha]: {
                    estado: 'ausente',
                    origen: 'manual',
                    motivo_ausencia: motivoNombre,
                    observaciones: ausenteForm.observaciones || null,
                  },
                },
              }
            : emp
        ),
      }));
      setAusenteModal(null);
    } catch {
      setMarkError('Error al marcar ausente. Intentá de nuevo.');
      setTimeout(() => setMarkError(null), 4000);
    } finally {
      setAusenteSaving(false);
    }
  };

  const handleRangoSubmit = async () => {
    if (!rangoForm.empleado_id || !rangoForm.fecha_desde || !rangoForm.fecha_hasta) {
      setRangoError('Empleado, fecha desde y fecha hasta son obligatorios');
      return;
    }
    setRangoSaving(true);
    setRangoError(null);
    setRangoSuccess(null);
    try {
      const { data } = await rrhhAPI.marcarPresentismoRango({
        empleado_id: Number(rangoForm.empleado_id),
        estado: rangoForm.estado,
        fecha_desde: rangoForm.fecha_desde,
        fecha_hasta: rangoForm.fecha_hasta,
        observaciones: rangoForm.observaciones || null,
      });
      setRangoSuccess(`Se marcaron ${data.updated} dias como "${rangoForm.estado}"`);
      cargarGrilla();
    } catch (err) {
      setRangoError(err.response?.data?.detail || 'Error al marcar rango');
    } finally {
      setRangoSaving(false);
    }
  };

  // ── ART CRUD ──
  const handleArtSubmit = async (e) => {
    e.preventDefault();
    if (!artForm.empleado_id || !artForm.fecha_accidente) {
      setArtFormError('Empleado y fecha de accidente son requeridos');
      return;
    }
    setArtSaving(true);
    setArtFormError(null);
    try {
      if (artForm.id) {
        const { id, empleado_id: _Emp, creado_por_id: _Cpor, created_at: _Cat, updated_at: _Uat, documentos: _Docs, ...updateData } = artForm;
        await rrhhAPI.actualizarArtCaso(id, updateData);
      } else {
        await rrhhAPI.crearArtCaso(artForm);
      }
      setArtModalOpen(false);
      setArtForm({});
      cargarArtCasos();
    } catch (err) {
      setArtFormError(err?.response?.data?.detail || 'Error al guardar');
    } finally {
      setArtSaving(false);
    }
  };

  const openArtCreate = () => {
    setArtForm({ estado: 'abierto' });
    setArtFormError(null);
    setArtModalOpen(true);
  };

  const openArtEdit = (caso) => {
    setArtForm({ ...caso });
    setArtFormError(null);
    setArtModalOpen(true);
  };

  const openArtDetalle = async (casoId) => {
    try {
      const { data } = await rrhhAPI.obtenerArtCaso(casoId);
      setArtDetalle(data);
    } catch (err) {
      setMarkError(err.response?.data?.detail || 'Error al cargar detalle del caso');
      setTimeout(() => setMarkError(null), 4000);
    }
  };

  // ── RENDER: Presentismo Grid ──
  const renderPresentismoGrid = () => {
    if (loadingGrilla) return <div className={styles.loading}>Cargando presentismo...</div>;
    if (grilla.empleados.length === 0) return <div className={styles.empty}>No hay empleados activos</div>;

    return (
      <>
        <div className={styles.gridWrapper}>
          <table className={styles.grid}>
            <thead>
              <tr>
                <th>Empleado</th>
                {grilla.fechas.map((f) => (
                  <th key={f}>{formatDateShort(f)}</th>
                ))}
                <th title="Llegadas tarde (tolerancia / fuera de tolerancia)">Tardes</th>
              </tr>
            </thead>
            <tbody>
              {grilla.empleados.map((emp) => {
                let countTolerancia = 0;
                let countTarde = 0;
                const cells = grilla.fechas.map((f) => {
                  const dia = emp.dias[f];
                  const estado = dia?.estado || null;
                  const origen = dia?.origen || null;
                  const puntualidad = dia?.puntualidad || null;
                  const isAuto = origen === 'auto';

                  // Pick style: override "presente" with tardiness variant
                  let styleName = estado ? ESTADO_STYLE_MAP[estado] : 'estadoEmpty';
                  if (estado === 'presente' && puntualidad === 'tolerancia') {
                    styleName = 'estadoPresenteTolerancia';
                    countTolerancia += 1;
                  } else if (estado === 'presente' && puntualidad === 'tarde') {
                    styleName = 'estadoPresenteTarde';
                    countTarde += 1;
                  }

                  const label = estado
                    ? ESTADOS_PRESENTISMO.find((e) => e.value === estado)?.label || estado
                    : '-';
                  const fullLabel = estado
                    ? ESTADOS_PRESENTISMO.find((e) => e.value === estado)?.fullLabel
                    : 'Sin marcar';
                  const fichadaStr = dia?.fichada ? ` | ${dia.fichada}` : '';
                  const tardeStr = dia?.minutos_tarde > 0 ? ` (+${dia.minutos_tarde}min)` : '';
                  const motivoStr = dia?.motivo_ausencia ? ` — ${dia.motivo_ausencia}` : '';
                  const obsStr = dia?.observaciones ? ` (${dia.observaciones})` : '';
                  const title = isAuto
                    ? `${fullLabel} (auto)${fichadaStr}${tardeStr}`
                    : `${fullLabel}${motivoStr}${obsStr}${fichadaStr}${tardeStr}`;
                  return (
                    <td key={f}>
                      <div className={styles.cellWrapper} onClick={(e) => handleCellClick(emp.empleado_id, f, e)}>
                        <span
                          className={`${styles[styleName]} ${isAuto ? styles.autoCalc : ''}`}
                          title={title}
                        >
                          {label}
                        </span>
                        {dia?.fichada && (
                          <span className={styles.fichadaLabel}>{dia.fichada}</span>
                        )}
                      </div>
                    </td>
                  );
                });
                return (
                  <tr key={emp.empleado_id}>
                    <td>
                      <div className={styles.empleadoCell}>
                        <span className={styles.empleadoNombre}>{emp.nombre_completo}</span>
                        <span className={styles.empleadoLegajo}>{emp.legajo}</span>
                      </div>
                    </td>
                    {cells}
                    <td>
                      {(countTolerancia > 0 || countTarde > 0) ? (
                        <div className={styles.tardeCount}>
                          {countTolerancia > 0 && (
                            <span className={styles.tardeCountOrange} title={`${countTolerancia} dentro de tolerancia`}>
                              {countTolerancia}
                            </span>
                          )}
                          {countTarde > 0 && (
                            <span className={styles.tardeCountRed} title={`${countTarde} fuera de tolerancia`}>
                              {countTarde}
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className={styles.tardeEmpty}>-</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Legend */}
        <div className={styles.legend}>
          {ESTADOS_PRESENTISMO.map((e) => (
            <div key={e.value} className={styles.legendItem}>
              <span className={`${styles.legendDot} ${styles['dot' + e.fullLabel.replace(/\s/g, '')]}`} />
              {e.fullLabel}
            </div>
          ))}
          <div className={styles.legendItem}>
            <span className={styles.legendAutoSample} />
            Auto-calculado
          </div>
        </div>
      </>
    );
  };

  // ── RENDER: ART List ──
  const renderArtList = () => {
    if (loadingArt) return <div className={styles.loading}>Cargando casos ART...</div>;

    return (
      <div className={styles.artSection}>
        <div className={styles.artHeader}>
          <h2>Casos ART</h2>
          {puedeGestionar && (
            <button className={styles.btnCreate} onClick={openArtCreate}>
              <Plus size={16} /> Nuevo Caso
            </button>
          )}
        </div>

        {artCasos.length === 0 ? (
          <div className={styles.empty}>No hay casos ART registrados</div>
        ) : (
          <div className={styles.gridWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Siniestro</th>
                  <th>Empleado</th>
                  <th>Fecha accidente</th>
                  <th>ART</th>
                  <th>Estado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {artCasos.map((c) => (
                  <tr key={c.id}>
                    <td>{c.numero_siniestro || '-'}</td>
                    <td>Emp #{c.empleado_id}</td>
                    <td>{c.fecha_accidente}</td>
                    <td>{c.art_nombre || '-'}</td>
                    <td>
                      <span className={styles[ART_STATUS_MAP[c.estado]] || styles.statusBadge}>
                        {c.estado.replace('_', ' ')}
                      </span>
                    </td>
                    <td>
                      <button
                        className={styles.btnView}
                        onClick={() => openArtDetalle(c.id)}
                        title="Ver detalle"
                      >
                        <Eye size={14} />
                      </button>
                      {puedeGestionar && (
                        <button
                          className={styles.btnEditAction}
                          onClick={() => openArtEdit(c)}
                          title="Editar"
                        >
                          <Edit3 size={14} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {artCasos.length > 0 && (
          <div className={styles.filters} style={{ justifyContent: 'center', marginTop: 'var(--spacing-md)' }}>
            <button className={styles.btnRefresh} onClick={() => setArtPage((p) => Math.max(1, p - 1))} disabled={artPage <= 1}>
              Anterior
            </button>
            <span style={{ fontSize: 'var(--font-sm)', color: 'var(--cf-text-secondary)' }}>Página {artPage}</span>
            <button className={styles.btnRefresh} onClick={() => setArtPage((p) => p + 1)} disabled={artCasos.length < 50}>
              Siguiente
            </button>
          </div>
        )}
      </div>
    );
  };

  // ── RENDER: ART Detalle Modal ──
  const renderArtDetalleModal = () => {
    if (!artDetalle) return null;
    return (
      <div className="modal-overlay-tesla" onClick={() => setArtDetalle(null)}>
        <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header-tesla">
            <h3 className="modal-title-tesla">Caso ART #{artDetalle.id}</h3>
            <button className="btn-close-tesla" onClick={() => setArtDetalle(null)} aria-label="Cerrar"><X size={14} /></button>
          </div>
          <div className="modal-body-tesla">
            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label>Siniestro</label>
                <span>{artDetalle.numero_siniestro || '-'}</span>
              </div>
              <div className={styles.formGroup}>
                <label>Estado</label>
                <span className={styles[ART_STATUS_MAP[artDetalle.estado]] || ''}>
                  {artDetalle.estado.replace('_', ' ')}
                </span>
              </div>
            </div>
            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label>Fecha accidente</label>
                <span>{artDetalle.fecha_accidente}</span>
              </div>
              <div className={styles.formGroup}>
                <label>Lugar</label>
                <span>{artDetalle.lugar_accidente || '-'}</span>
              </div>
            </div>
            <div className={styles.formGroup}>
              <label>Descripcion</label>
              <span>{artDetalle.descripcion_accidente || '-'}</span>
            </div>
            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label>Tipo lesion</label>
                <span>{artDetalle.tipo_lesion || '-'}</span>
              </div>
              <div className={styles.formGroup}>
                <label>Parte del cuerpo</label>
                <span>{artDetalle.parte_cuerpo || '-'}</span>
              </div>
            </div>
            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label>ART (aseguradora)</label>
                <span>{artDetalle.art_nombre || '-'}</span>
              </div>
              <div className={styles.formGroup}>
                <label>Expediente</label>
                <span>{artDetalle.numero_expediente_art || '-'}</span>
              </div>
            </div>
            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label>Dias baja</label>
                <span>{artDetalle.dias_baja ?? '-'}</span>
              </div>
              <div className={styles.formGroup}>
                <label>% Incapacidad</label>
                <span>{artDetalle.porcentaje_incapacidad ?? '-'}</span>
              </div>
            </div>
            {artDetalle.documentos && artDetalle.documentos.length > 0 && (
              <div className={styles.formGroup}>
                <label>Documentos ({artDetalle.documentos.length})</label>
                {artDetalle.documentos.map((d) => (
                  <div key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                    <FileText size={14} />
                    <span>{d.nombre_archivo}</span>
                    <button
                      className={styles.btnDownload}
                      onClick={async () => {
                        try {
                          const response = await rrhhAPI.descargarArtDocumento(artDetalle.id, d.id);
                          const url = window.URL.createObjectURL(new Blob([response.data]));
                          const link = document.createElement('a');
                          link.href = url;
                          link.setAttribute('download', d.nombre_archivo);
                          document.body.appendChild(link);
                          link.click();
                          link.remove();
                          window.URL.revokeObjectURL(url);
                        } catch {
                          // noop
                        }
                      }}
                    >
                      <Download size={12} /> Descargar
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="modal-footer-tesla">
            <button className={styles.btnCancel} onClick={() => setArtDetalle(null)}>Cerrar</button>
          </div>
        </div>
      </div>
    );
  };

  // ── RENDER: ART Form Modal ──
  const renderArtFormModal = () => {
    if (!artModalOpen) return null;
    return (
      <div className="modal-overlay-tesla" onClick={() => setArtModalOpen(false)}>
        <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header-tesla">
            <h3 className="modal-title-tesla">{artForm.id ? 'Editar Caso ART' : 'Nuevo Caso ART'}</h3>
            <button className="btn-close-tesla" onClick={() => setArtModalOpen(false)} aria-label="Cerrar"><X size={14} /></button>
          </div>
          <form onSubmit={handleArtSubmit}>
            <div className="modal-body-tesla">
              {artFormError && <div className={styles.formError}>{artFormError}</div>}

              {!artForm.id && (
                <div className={styles.formGroup}>
                  <label>Empleado *</label>
                  <select
                    className={styles.select}
                    value={artForm.empleado_id || ''}
                    onChange={(e) => setArtForm({ ...artForm, empleado_id: parseInt(e.target.value) || '' })}
                    required
                  >
                    <option value="">Seleccionar empleado...</option>
                    {empleados.map((emp) => (
                      <option key={emp.id} value={emp.id}>
                        {emp.legajo} - {emp.apellido}, {emp.nombre}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Fecha accidente *</label>
                  <input
                    className={styles.input}
                    type="date"
                    value={artForm.fecha_accidente || ''}
                    onChange={(e) => setArtForm({ ...artForm, fecha_accidente: e.target.value })}
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Nro. Siniestro</label>
                  <input
                    className={styles.input}
                    type="text"
                    value={artForm.numero_siniestro || ''}
                    onChange={(e) => setArtForm({ ...artForm, numero_siniestro: e.target.value })}
                  />
                </div>
              </div>

              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Lugar del accidente</label>
                  <input
                    className={styles.input}
                    type="text"
                    value={artForm.lugar_accidente || ''}
                    onChange={(e) => setArtForm({ ...artForm, lugar_accidente: e.target.value })}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Estado</label>
                  <select
                    className={styles.select}
                    value={artForm.estado || 'abierto'}
                    onChange={(e) => setArtForm({ ...artForm, estado: e.target.value })}
                  >
                    <option value="abierto">Abierto</option>
                    <option value="en_tratamiento">En tratamiento</option>
                    <option value="alta_medica">Alta medica</option>
                    <option value="cerrado">Cerrado</option>
                  </select>
                </div>
              </div>

              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Tipo de lesion</label>
                  <input
                    className={styles.input}
                    type="text"
                    value={artForm.tipo_lesion || ''}
                    onChange={(e) => setArtForm({ ...artForm, tipo_lesion: e.target.value })}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Parte del cuerpo</label>
                  <input
                    className={styles.input}
                    type="text"
                    value={artForm.parte_cuerpo || ''}
                    onChange={(e) => setArtForm({ ...artForm, parte_cuerpo: e.target.value })}
                  />
                </div>
              </div>

              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>ART (aseguradora)</label>
                  <input
                    className={styles.input}
                    type="text"
                    value={artForm.art_nombre || ''}
                    onChange={(e) => setArtForm({ ...artForm, art_nombre: e.target.value })}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Nro. Expediente ART</label>
                  <input
                    className={styles.input}
                    type="text"
                    value={artForm.numero_expediente_art || ''}
                    onChange={(e) => setArtForm({ ...artForm, numero_expediente_art: e.target.value })}
                  />
                </div>
              </div>

              <div className={styles.formGroup}>
                <label>Descripcion del accidente</label>
                <textarea
                  className={styles.textarea}
                  value={artForm.descripcion_accidente || ''}
                  onChange={(e) => setArtForm({ ...artForm, descripcion_accidente: e.target.value })}
                />
              </div>

              <div className={styles.formGroup}>
                <label>Observaciones</label>
                <textarea
                  className={styles.textarea}
                  value={artForm.observaciones || ''}
                  onChange={(e) => setArtForm({ ...artForm, observaciones: e.target.value })}
                />
              </div>

              {artForm.id && (
                <div className={styles.formRow}>
                  <div className={styles.formGroup}>
                    <label>Dias baja</label>
                    <input
                      className={styles.input}
                      type="number"
                      value={artForm.dias_baja ?? ''}
                      onChange={(e) => setArtForm({ ...artForm, dias_baja: parseInt(e.target.value) || null })}
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label>% Incapacidad</label>
                    <input
                      className={styles.input}
                      type="number"
                      step="0.01"
                      value={artForm.porcentaje_incapacidad ?? ''}
                      onChange={(e) => setArtForm({ ...artForm, porcentaje_incapacidad: parseFloat(e.target.value) || null })}
                    />
                  </div>
                </div>
              )}
            </div>
            <div className="modal-footer-tesla">
              <button type="button" className={styles.btnCancel} onClick={() => setArtModalOpen(false)}>
                Cancelar
              </button>
              <button type="submit" className={styles.btnSave} disabled={artSaving}>
                {artSaving ? 'Guardando...' : 'Guardar'}
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <CalendarDays size={24} />
          <h1>Presentismo y ART</h1>
        </div>
      </div>

      {/* Tabs */}
      <div className={styles.tabs}>
        <button
          className={activeTab === 'presentismo' ? styles.tabActive : styles.tab}
          onClick={() => setActiveTab('presentismo')}
        >
          <ClipboardList size={16} /> Presentismo
        </button>
        <button
          className={activeTab === 'art' ? styles.tabActive : styles.tab}
          onClick={() => setActiveTab('art')}
        >
          <AlertTriangle size={16} /> Casos ART
        </button>
      </div>

      {/* Tab content */}
      {activeTab === 'presentismo' && (
        <>
          <div className={styles.filters}>
            <input
              className={styles.input}
              type="date"
              value={fechaDesde}
              onChange={(e) => setFechaDesde(e.target.value)}
            />
            <span style={{ color: 'var(--cf-text-tertiary)' }}>a</span>
            <input
              className={styles.input}
              type="date"
              value={fechaHasta}
              onChange={(e) => setFechaHasta(e.target.value)}
            />
            <button className={styles.btnRefresh} onClick={cargarGrilla} title="Recargar">
              <RotateCcw size={14} />
            </button>
            <button
              className={styles.btnCreate}
              onClick={async () => {
                try {
                  const { data } = await rrhhAPI.exportarPresentismoDiario({
                    fecha_desde: fechaDesde,
                    fecha_hasta: fechaHasta,
                  });
                  const url = window.URL.createObjectURL(new Blob([data]));
                  const link = document.createElement('a');
                  link.href = url;
                  link.setAttribute('download', `presentismo_${fechaDesde}_${fechaHasta}.xlsx`);
                  document.body.appendChild(link);
                  link.click();
                  link.remove();
                  window.URL.revokeObjectURL(url);
                } catch {
                  setMarkError('Error al exportar. Intenta de nuevo.');
                  setTimeout(() => setMarkError(null), 4000);
                }
              }}
              title="Exportar a Excel (apaisado)"
            >
              <Download size={14} /> Exportar Excel
            </button>
            {puedeGestionar && (
              <button
                className={styles.btnCreate}
                onClick={() => {
                  setRangoForm({ empleado_id: '', estado: 'vacaciones', fecha_desde: '', fecha_hasta: '', observaciones: '' });
                  setRangoError(null);
                  setRangoSuccess(null);
                  setRangoModalOpen(true);
                }}
                title="Cargar vacaciones, suspension, ART o licencia por rango de fechas"
              >
                <CalendarRange size={14} /> Cargar por rango
              </button>
            )}
          </div>
          {markError && <div className={styles.formError} style={{ marginBottom: 'var(--spacing-sm)' }}>{markError}</div>}
          {renderPresentismoGrid()}
        </>
      )}

      {activeTab === 'art' && renderArtList()}

      {/* Quick-mark dropdown */}
      {dropdown && (
        <div
          ref={dropdownRef}
          className={styles.dropdown}
          style={{ position: 'fixed', left: dropdown.x, top: dropdown.y }}
        >
          {ESTADOS_PRESENTISMO.map((e) => (
            <button
              key={e.value}
              className={styles.dropdownItem}
              onClick={() => handleEstadoSelect(e.value)}
            >
              <span className={styles[ESTADO_STYLE_MAP[e.value]]} style={{ minWidth: 32 }}>
                {e.label}
              </span>
              {e.fullLabel}
            </button>
          ))}
        </div>
      )}

      {/* Modals */}
      {renderArtFormModal()}
      {renderArtDetalleModal()}

      {/* Range marking modal */}
      {rangoModalOpen && (
        <div className="modal-overlay-tesla" onClick={() => setRangoModalOpen(false)}>
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Cargar por rango de fechas</h2>
              <button className="btn-close-tesla" onClick={() => setRangoModalOpen(false)} aria-label="Cerrar modal">
                <X size={14} />
              </button>
            </div>
            <div className="modal-body-tesla">
              <p
                style={{
                  color: 'var(--cf-text-secondary)',
                  fontSize: 'var(--font-sm)',
                  marginBottom: 'var(--spacing-md)',
                }}
              >
                Marcar un estado para un empleado en un rango de fechas. Util para cargar vacaciones, suspensiones, ART
                o licencia sin hacerlo dia por dia.
              </p>
              <div className={styles.formGroup}>
                <label>Empleado</label>
                <select
                  className={styles.select}
                  value={rangoForm.empleado_id}
                  onChange={(e) => setRangoForm({ ...rangoForm, empleado_id: e.target.value })}
                  required
                >
                  <option value="">Seleccionar empleado...</option>
                  {empleados.map((emp) => (
                    <option key={emp.id} value={emp.id}>
                      {emp.legajo} - {emp.apellido}, {emp.nombre}
                    </option>
                  ))}
                </select>
              </div>
              <div className={styles.formGroup}>
                <label>Estado</label>
                <select
                  className={styles.select}
                  value={rangoForm.estado}
                  onChange={(e) => setRangoForm({ ...rangoForm, estado: e.target.value })}
                >
                  <option value="vacaciones">Vacaciones</option>
                  <option value="licencia">Licencia</option>
                  <option value="art">ART</option>
                  <option value="ausente">Ausente</option>
                  <option value="home_office">Home Office</option>
                  <option value="franco">Franco</option>
                </select>
              </div>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Fecha desde</label>
                  <input
                    className={styles.input}
                    type="date"
                    value={rangoForm.fecha_desde}
                    onChange={(e) => setRangoForm({ ...rangoForm, fecha_desde: e.target.value })}
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Fecha hasta</label>
                  <input
                    className={styles.input}
                    type="date"
                    value={rangoForm.fecha_hasta}
                    onChange={(e) => setRangoForm({ ...rangoForm, fecha_hasta: e.target.value })}
                    required
                  />
                </div>
              </div>
              <div className={styles.formGroup}>
                <label>Observaciones (opcional)</label>
                <textarea
                  className={styles.textarea}
                  value={rangoForm.observaciones}
                  onChange={(e) => setRangoForm({ ...rangoForm, observaciones: e.target.value })}
                  placeholder="Ej: Vacaciones aprobadas por jefe de area"
                />
              </div>
              {rangoError && <div className={styles.formError}>{rangoError}</div>}
              {rangoSuccess && (
                <div
                  style={{
                    color: 'var(--cf-accent-green)',
                    fontSize: 'var(--font-sm)',
                    marginTop: 'var(--spacing-sm)',
                  }}
                >
                  {rangoSuccess}
                </div>
              )}
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setRangoModalOpen(false)}>
                Cerrar
              </button>
              <button className={styles.btnSave} onClick={handleRangoSubmit} disabled={rangoSaving}>
                {rangoSaving ? 'Guardando...' : 'Aplicar rango'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Motivo de ausencia modal */}
      {ausenteModal && (
        <div className="modal-overlay-tesla">
          <div className="modal-tesla">
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Marcar ausencia</h2>
              <button className="btn-close-tesla" onClick={() => setAusenteModal(null)} aria-label="Cerrar">
                <X size={14} />
              </button>
            </div>
            <div className="modal-body-tesla">
              <div className={styles.formGroup}>
                <label>Motivo de ausencia</label>
                <select
                  className={styles.select}
                  value={ausenteForm.motivo_ausencia_id}
                  onChange={(e) => setAusenteForm({ ...ausenteForm, motivo_ausencia_id: e.target.value })}
                >
                  <option value="">Sin motivo especificado</option>
                  {motivosAusencia.map((m) => (
                    <option key={m.id} value={m.id}>{m.nombre}</option>
                  ))}
                </select>
              </div>
              <div className={styles.formGroup}>
                <label>Observaciones (opcional)</label>
                <textarea
                  className={styles.textarea}
                  value={ausenteForm.observaciones}
                  onChange={(e) => setAusenteForm({ ...ausenteForm, observaciones: e.target.value })}
                  placeholder="Ej: Avisó por WhatsApp a las 7am"
                />
              </div>
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setAusenteModal(null)}>
                Cancelar
              </button>
              <button className={styles.btnSave} onClick={handleAusenteSubmit} disabled={ausenteSaving}>
                {ausenteSaving ? 'Guardando...' : 'Marcar ausente'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
