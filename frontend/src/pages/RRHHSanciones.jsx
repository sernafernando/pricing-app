import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI } from '../services/api';
import { Shield, Plus, RotateCcw, Ban, Eye, FileDown, HelpCircle, X, Settings, Pencil, Trash2 } from 'lucide-react';
import DocumentGeneratorModal from '../components/DocumentGeneratorModal';
import styles from './RRHHSanciones.module.css';

const INITIAL_FORM = {
  empleado_id: '',
  tipo_sancion_id: '',
  fecha: new Date().toISOString().slice(0, 10),
  motivo: '',
  descripcion: '',
  texto_sancion: '',
  fecha_desde: '',
  fecha_hasta: '',
};

const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
};

/**
 * Extrae placeholders {xxx} de un texto.
 * Retorna array de nombres únicos. Ej: "{nombre} bla {legajo}" → ["nombre", "legajo"]
 */
const extractPlaceholders = (text) => {
  if (!text) return [];
  const matches = text.match(/\{(\w+)\}/g);
  if (!matches) return [];
  return [...new Set(matches.map((m) => m.slice(1, -1)))];
};

/**
 * Reemplaza {placeholder} en el texto con los valores del mapa.
 * Los que no tienen valor quedan como {placeholder}.
 */
const interpolateText = (template, values) => {
  if (!template) return '';
  return template.replace(/\{(\w+)\}/g, (match, key) => {
    const val = values[key];
    return val !== undefined && val !== '' ? val : match;
  });
};

export default function RRHHSanciones() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rrhh.gestionar');

  // ── List state ──
  const [sanciones, setSanciones] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;

  // ── Filter state ──
  const [filtroEmpleado, setFiltroEmpleado] = useState('');
  const [filtroTipo, setFiltroTipo] = useState('');
  const [filtroDesde, setFiltroDesde] = useState('');
  const [filtroHasta, setFiltroHasta] = useState('');
  const [mostrarAnuladas, setMostrarAnuladas] = useState(false);

  // ── Tipos sancion (for select) ──
  const [tiposSancion, setTiposSancion] = useState([]);

  // ── Create modal ──
  const [crearModalOpen, setCrearModalOpen] = useState(false);
  const [crearForm, setCrearForm] = useState(INITIAL_FORM);
  const [crearSaving, setCrearSaving] = useState(false);
  const [crearError, setCrearError] = useState(null);

  // ── Anular modal ──
  const [anularTarget, setAnularTarget] = useState(null);
  const [anularMotivo, setAnularMotivo] = useState('');
  const [anularSaving, setAnularSaving] = useState(false);
  const [anularError, setAnularError] = useState(null);

  // ── Detail view ──
  const [detalleOpen, setDetalleOpen] = useState(null);

  // ── Empleados for selector ──
  const [empleados, setEmpleados] = useState([]);
  const [empleadoSearch, setEmpleadoSearch] = useState('');

  // ── Placeholders ──
  const [knownPlaceholders, setKnownPlaceholders] = useState({});
  const [placeholderValues, setPlaceholderValues] = useState({});
  const [currentPlaceholders, setCurrentPlaceholders] = useState([]);
  const [showPlaceholderHelp, setShowPlaceholderHelp] = useState(false);

  // ── Config modal (tipos + textos predefinidos) ──
  const puedeConfig = tienePermiso('rrhh.config');
  const [configModalOpen, setConfigModalOpen] = useState(false);
  const [configTab, setConfigTab] = useState('tipos'); // 'tipos' | 'textos'
  const [editingTipo, setEditingTipo] = useState(null); // null = crear, obj = editar
  const [tipoForm, setTipoForm] = useState({ nombre: '', descripcion: '', requiere_descuento: false, orden: 0 });
  const [tipoSaving, setTipoSaving] = useState(false);
  const [tipoError, setTipoError] = useState(null);

  // ── Textos predefinidos state ──
  const [textosPredefinidos, setTextosPredefinidos] = useState([]);
  const [textosPredLoading, setTextosPredLoading] = useState(false);
  const [editingTexto, setEditingTexto] = useState(null);
  const [textoForm, setTextoForm] = useState({ nombre: '', texto: '', orden: 0 });
  const [textoSaving, setTextoSaving] = useState(false);
  const [textoError, setTextoError] = useState(null);
  const [deleteConfirmTexto, setDeleteConfirmTexto] = useState(null);

  // ── Create sancion modal: texto predefinido select ──
  const [selectedTextoPredefinidoId, setSelectedTextoPredefinidoId] = useState('');

  // ── PDF modal ──
  const [pdfTarget, setPdfTarget] = useState(null);

  // ── Load tipos sancion + placeholders on mount ──
  useEffect(() => {
    const fetchTipos = async () => {
      try {
        const { data } = await rrhhAPI.listarTiposSancion({ incluir_inactivos: true });
        setTiposSancion(Array.isArray(data) ? data : data.items || []);
      } catch {
        setTiposSancion([]);
      }
    };
    const fetchPlaceholders = async () => {
      try {
        const { data } = await rrhhAPI.obtenerPlaceholdersSancion();
        setKnownPlaceholders(data || {});
      } catch {
        setKnownPlaceholders({});
      }
    };
    fetchTipos();
    fetchPlaceholders();
  }, []);

  // ── Load textos predefinidos on mount ──
  const reloadTextosPredefinidos = useCallback(async () => {
    setTextosPredLoading(true);
    try {
      const { data } = await rrhhAPI.listarTextosPredefinidosSancion({ activo: false });
      setTextosPredefinidos(Array.isArray(data) ? data : data.items || []);
    } catch {
      setTextosPredefinidos([]);
    } finally {
      setTextosPredLoading(false);
    }
  }, []);

  useEffect(() => {
    reloadTextosPredefinidos();
  }, [reloadTextosPredefinidos]);

  // ── Load empleados on mount ──
  useEffect(() => {
    const fetchEmpleados = async () => {
      try {
        const { data } = await rrhhAPI.listarEmpleados({ page_size: 9999, estado: 'activo' });
        setEmpleados(Array.isArray(data) ? data : data.items || []);
      } catch {
        setEmpleados([]);
      }
    };
    fetchEmpleados();
  }, []);

  // ── Fetch sanciones ──
  const cargarSanciones = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: PAGE_SIZE };
      if (filtroEmpleado) params.empleado_id = Number(filtroEmpleado);
      if (filtroTipo) params.tipo_sancion_id = Number(filtroTipo);
      if (filtroDesde) params.fecha_desde = filtroDesde;
      if (filtroHasta) params.fecha_hasta = filtroHasta;
      if (!mostrarAnuladas) params.incluir_anuladas = false;

      const { data } = await rrhhAPI.listarSanciones(params);
      setSanciones(data.items || []);
      setTotal(data.total || 0);
    } catch {
      setSanciones([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, filtroEmpleado, filtroTipo, filtroDesde, filtroHasta, mostrarAnuladas]);

  useEffect(() => {
    cargarSanciones();
  }, [cargarSanciones]);

  // ── Create sancion ──
  const handleCrear = async () => {
    if (!crearForm.empleado_id || !crearForm.tipo_sancion_id) {
      setCrearError('Empleado y tipo de sanción son obligatorios');
      return;
    }
    if (!crearForm.motivo.trim()) {
      setCrearError('El motivo es obligatorio');
      return;
    }
    setCrearSaving(true);
    setCrearError(null);
    try {
      const payload = {
        empleado_id: Number(crearForm.empleado_id),
        tipo_sancion_id: Number(crearForm.tipo_sancion_id),
        fecha: crearForm.fecha,
        motivo: crearForm.motivo.trim(),
      };
      if (crearForm.descripcion.trim()) {
        payload.descripcion = crearForm.descripcion.trim();
      }
      const textoFinal = currentPlaceholders.length > 0
        ? interpolateText(crearForm.texto_sancion, placeholderValues)
        : crearForm.texto_sancion;
      if (textoFinal.trim()) {
        payload.texto_sancion = textoFinal.trim();
      }
      if (crearForm.fecha_desde) payload.fecha_desde = crearForm.fecha_desde;
      if (crearForm.fecha_hasta) payload.fecha_hasta = crearForm.fecha_hasta;
      if (selectedTextoPredefinidoId) payload.texto_predefinido_id = Number(selectedTextoPredefinidoId);

      await rrhhAPI.crearSancion(payload);
      setCrearModalOpen(false);
      setCrearForm(INITIAL_FORM);
      setCurrentPlaceholders([]);
      setPlaceholderValues({});
      setSelectedTextoPredefinidoId('');
      cargarSanciones();
    } catch (err) {
      setCrearError(err.response?.data?.detail || 'Error al crear la sancion');
    } finally {
      setCrearSaving(false);
    }
  };

  // ── Anular sancion ──
  const handleAnular = async () => {
    if (!anularMotivo.trim()) {
      setAnularError('El motivo de anulacion es obligatorio');
      return;
    }
    setAnularSaving(true);
    setAnularError(null);
    try {
      await rrhhAPI.anularSancion(anularTarget.id, { motivo: anularMotivo.trim() });
      setAnularTarget(null);
      setAnularMotivo('');
      cargarSanciones();
    } catch (err) {
      setAnularError(err.response?.data?.detail || 'Error al anular la sancion');
    } finally {
      setAnularSaving(false);
    }
  };

  // ── Open create modal ──
  const openCrear = () => {
    setCrearForm({ ...INITIAL_FORM, fecha: new Date().toISOString().slice(0, 10) });
    setCrearError(null);
    setSelectedTextoPredefinidoId('');
    setCurrentPlaceholders([]);
    setPlaceholderValues({});
    setCrearModalOpen(true);
  };

  // ── Open anular modal ──
  const openAnular = (sancion) => {
    setAnularTarget(sancion);
    setAnularMotivo('');
    setAnularError(null);
  };

  // ── Helpers ──
  const getTipoNombre = (tipoId) => {
    const tipo = tiposSancion.find((t) => t.id === tipoId);
    return tipo ? tipo.nombre : `#${tipoId}`;
  };

  /**
   * Construye los valores auto-fill a partir del empleado seleccionado y el form.
   * Solo llena los placeholders que están en KNOWN_PLACEHOLDERS del backend.
   */
  const buildAutoFillValues = useCallback((empleadoId, formData) => {
    const emp = empleados.find((e) => e.id === Number(empleadoId));
    const tipo = tiposSancion.find((t) => t.id === Number(formData.tipo_sancion_id));
    const auto = {};
    if (emp) {
      auto.nombre_empleado = `${emp.apellido}, ${emp.nombre}`.toUpperCase();
      auto.legajo = emp.legajo || '';
      auto.dni = emp.dni || '';
      auto.cuil = emp.cuil || '';
      auto.area = emp.area || '';
      auto.puesto = emp.puesto || '';
      auto.fecha_ingreso = emp.fecha_ingreso ? formatDate(emp.fecha_ingreso) : '';
    }
    if (tipo) {
      auto.tipo_sancion = tipo.nombre || '';
    }
    // dias_suspension se calcula de fecha_desde/fecha_hasta
    if (formData.fecha_desde && formData.fecha_hasta) {
      const desde = new Date(formData.fecha_desde + 'T12:00:00');
      const hasta = new Date(formData.fecha_hasta + 'T12:00:00');
      const diff = Math.round((hasta - desde) / (1000 * 60 * 60 * 24)) + 1;
      if (diff > 0) auto.dias_suspension = String(diff);
    }
    if (formData.fecha) auto.fecha_sancion = formatDate(formData.fecha);
    if (formData.fecha_desde) auto.fecha_desde = formatDate(formData.fecha_desde);
    if (formData.fecha_hasta) auto.fecha_hasta = formatDate(formData.fecha_hasta);
    return auto;
  }, [empleados, tiposSancion]);

  /**
   * Cuando cambian los datos del form que afectan auto-fill, recalcular.
   */
  const refreshPlaceholderValues = useCallback((formData, extraPlaceholders) => {
    const auto = buildAutoFillValues(formData.empleado_id, formData);
    const phs = extraPlaceholders || currentPlaceholders;
    setPlaceholderValues((prev) => {
      const next = {};
      for (const ph of phs) {
        // Auto-fill si es conocido, sino mantener valor manual previo
        if (auto[ph] !== undefined) {
          next[ph] = auto[ph];
        } else {
          next[ph] = prev[ph] || '';
        }
      }
      return next;
    });
  }, [buildAutoFillValues, currentPlaceholders]);

  // ── Config tipos: helpers ──
  const tiposActivos = tiposSancion.filter((t) => t.activo);

  const reloadTipos = async () => {
    try {
      const { data } = await rrhhAPI.listarTiposSancion({ incluir_inactivos: true });
      setTiposSancion(Array.isArray(data) ? data : data.items || []);
    } catch {
      /* noop */
    }
  };

  const openEditTipo = (tipo) => {
    setEditingTipo(tipo);
    setTipoForm({
      nombre: tipo.nombre,
      descripcion: tipo.descripcion || '',
      requiere_descuento: tipo.requiere_descuento,
      texto_predeterminado: tipo.texto_predeterminado || '',
      orden: tipo.orden,
    });
    setTipoError(null);
  };

  const openNewTipo = () => {
    setEditingTipo(null);
    setTipoForm({ nombre: '', descripcion: '', requiere_descuento: false, orden: tiposSancion.length + 1 });
    setTipoError(null);
  };

  const handleSaveTipo = async () => {
    if (!tipoForm.nombre.trim()) {
      setTipoError('El nombre es obligatorio');
      return;
    }
    setTipoSaving(true);
    setTipoError(null);
    try {
      if (editingTipo) {
        await rrhhAPI.actualizarTipoSancion(editingTipo.id, tipoForm);
      } else {
        await rrhhAPI.crearTipoSancion(tipoForm);
      }
      await reloadTipos();
      setEditingTipo(null);
      setTipoForm({ nombre: '', descripcion: '', requiere_descuento: false, orden: 0 });
    } catch (err) {
      setTipoError(err.response?.data?.detail || 'Error al guardar tipo');
    } finally {
      setTipoSaving(false);
    }
  };

  // ── Textos predefinidos: CRUD helpers ──
  const textosActivos = textosPredefinidos.filter((t) => t.activo);

  const openEditTexto = (texto) => {
    setEditingTexto(texto);
    setTextoForm({ nombre: texto.nombre, texto: texto.texto, orden: texto.orden });
    setTextoError(null);
  };

  const openNewTexto = () => {
    setEditingTexto(null);
    setTextoForm({ nombre: '', texto: '', orden: textosPredefinidos.length + 1 });
    setTextoError(null);
  };

  const handleSaveTexto = async () => {
    if (!textoForm.nombre.trim()) {
      setTextoError('El nombre es obligatorio');
      return;
    }
    if (!textoForm.texto.trim()) {
      setTextoError('El texto es obligatorio');
      return;
    }
    setTextoSaving(true);
    setTextoError(null);
    try {
      if (editingTexto) {
        await rrhhAPI.actualizarTextoPredefinidoSancion(editingTexto.id, textoForm);
      } else {
        await rrhhAPI.crearTextoPredefinidoSancion(textoForm);
      }
      await reloadTextosPredefinidos();
      setEditingTexto(null);
      setTextoForm({ nombre: '', texto: '', orden: 0 });
    } catch (err) {
      setTextoError(err.response?.data?.detail || 'Error al guardar texto');
    } finally {
      setTextoSaving(false);
    }
  };

  const handleDeleteTexto = async () => {
    if (!deleteConfirmTexto) return;
    try {
      await rrhhAPI.eliminarTextoPredefinidoSancion(deleteConfirmTexto.id);
      await reloadTextosPredefinidos();
    } catch {
      /* noop */
    } finally {
      setDeleteConfirmTexto(null);
    }
  };

  // ── Texto predefinido selection in create modal ──
  const handleSelectTextoPredefinido = (textoId) => {
    setSelectedTextoPredefinidoId(textoId);
    if (!textoId) {
      setCrearForm((prev) => ({ ...prev, texto_sancion: '' }));
      setCurrentPlaceholders([]);
      setPlaceholderValues({});
      return;
    }
    const texto = textosPredefinidos.find((t) => t.id === Number(textoId));
    if (!texto) return;
    const template = texto.texto;
    const phs = extractPlaceholders(template);
    const newForm = { ...crearForm, texto_sancion: template };
    setCrearForm(newForm);
    setCurrentPlaceholders(phs);
    refreshPlaceholderValues(newForm, phs);
  };

  const handleToggleTipoActivo = async (tipo) => {
    try {
      await rrhhAPI.actualizarTipoSancion(tipo.id, { activo: !tipo.activo });
      await reloadTipos();
    } catch {
      /* noop */
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Shield size={24} />
          <h1>Sanciones</h1>
          {total > 0 && <span className={styles.badge}>{total}</span>}
        </div>
        <div className={styles.headerActions}>
          {puedeConfig && (
            <button className={styles.btnConfig} onClick={() => setConfigModalOpen(true)}>
              <Settings size={16} /> Tipos
            </button>
          )}
          {puedeGestionar && (
            <button className={styles.btnCreate} onClick={openCrear}>
              <Plus size={16} /> Nueva sancion
            </button>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className={styles.filters}>
        <input
          type="number"
          className={styles.input}
          placeholder="Legajo o ID empleado"
          value={filtroEmpleado}
          onChange={(e) => { setFiltroEmpleado(e.target.value); setPage(1); }}
          min="1"
        />
        <select
          className={styles.select}
          value={filtroTipo}
          onChange={(e) => { setFiltroTipo(e.target.value); setPage(1); }}
        >
          <option value="">Todos los tipos</option>
          {tiposSancion.map((t) => (
            <option key={t.id} value={t.id}>{t.nombre}</option>
          ))}
        </select>
        <input
          type="date"
          className={styles.input}
          value={filtroDesde}
          onChange={(e) => { setFiltroDesde(e.target.value); setPage(1); }}
          title="Fecha desde"
        />
        <input
          type="date"
          className={styles.input}
          value={filtroHasta}
          onChange={(e) => { setFiltroHasta(e.target.value); setPage(1); }}
          title="Fecha hasta"
        />
        <label className={styles.checkboxLabel}>
          <input
            type="checkbox"
            checked={mostrarAnuladas}
            onChange={(e) => { setMostrarAnuladas(e.target.checked); setPage(1); }}
          />
          Mostrar anuladas
        </label>
        <button className={styles.btnRefresh} onClick={() => { setPage(1); cargarSanciones(); }} title="Recargar">
          <RotateCcw size={14} />
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <div className={styles.loading}>Cargando sanciones...</div>
      ) : sanciones.length === 0 ? (
        <div className={styles.empty}>No se encontraron sanciones</div>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Empleado</th>
              <th>Tipo sancion</th>
              <th>Motivo</th>
              <th>Suspension</th>
              <th>Estado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {sanciones.map((s) => (
              <tr key={s.id}>
                <td>{formatDate(s.fecha)}</td>
                <td>{s.empleado_nombre || `#${s.empleado_id}`}</td>
                <td>{getTipoNombre(s.tipo_sancion_id)}</td>
                <td>{s.motivo}</td>
                <td>
                  {s.fecha_desde
                    ? `${formatDate(s.fecha_desde)} - ${formatDate(s.fecha_hasta)}`
                    : '-'}
                </td>
                <td>
                  {s.anulada ? (
                    <span className={styles.statusAnulada}>Anulada</span>
                  ) : (
                    <span className={styles.statusActiva}>Activa</span>
                  )}
                </td>
                <td>
                  <div className={styles.actions}>
                    <button
                      className={styles.btnView}
                      onClick={() => setDetalleOpen(s)}
                      title="Ver detalle"
                    >
                      <Eye size={14} />
                    </button>
                    <button
                      className={styles.btnView}
                      onClick={() => setPdfTarget(s)}
                      title="Generar PDF"
                    >
                      <FileDown size={14} />
                    </button>
                    {puedeGestionar && !s.anulada && (
                      <button
                        className={styles.btnAnular}
                        onClick={() => openAnular(s)}
                        title="Anular sancion"
                      >
                        <Ban size={14} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className={styles.filters} style={{ marginTop: 'var(--spacing-md)', justifyContent: 'center' }}>
          <button
            className={styles.btnCancel}
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Anterior
          </button>
          <span style={{ fontSize: 'var(--font-sm)', color: 'var(--cf-text-secondary)' }}>
            Pagina {page} de {totalPages}
          </span>
          <button
            className={styles.btnCancel}
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Siguiente
          </button>
        </div>
      )}

      {/* Create modal */}
      {crearModalOpen && (
        <div className="modal-overlay-tesla" onClick={() => setCrearModalOpen(false)}>
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Nueva sancion</h2>
              <button className="btn-close-tesla" onClick={() => setCrearModalOpen(false)} aria-label="Cerrar modal">✕</button>
            </div>
            <div className="modal-body-tesla">
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Empleado (Legajo)</label>
                  <input
                    type="text"
                    className={styles.input}
                    placeholder="Buscar por legajo o nombre..."
                    value={empleadoSearch}
                    onChange={(e) => setEmpleadoSearch(e.target.value)}
                  />
                  <select
                    className={styles.select}
                    value={crearForm.empleado_id}
                    onChange={(e) => {
                      const newForm = { ...crearForm, empleado_id: e.target.value };
                      setCrearForm(newForm);
                      refreshPlaceholderValues(newForm);
                    }}
                    required
                    size={5}
                    style={{ marginTop: 'var(--spacing-xs)' }}
                  >
                    <option value="">Seleccionar empleado...</option>
                    {empleados
                      .filter((emp) => {
                        if (!empleadoSearch) return true;
                        const q = empleadoSearch.toLowerCase();
                        return (
                          (emp.legajo || '').toLowerCase().includes(q) ||
                          (emp.nombre || '').toLowerCase().includes(q) ||
                          (emp.apellido || '').toLowerCase().includes(q) ||
                          (`${emp.apellido} ${emp.nombre}`).toLowerCase().includes(q)
                        );
                      })
                      .map((emp) => (
                        <option key={emp.id} value={emp.id}>
                          {emp.legajo} - {emp.apellido}, {emp.nombre}
                        </option>
                      ))}
                  </select>
                </div>
                <div className={styles.formGroup}>
                  <label>Tipo de sancion</label>
                  <select
                    className={styles.select}
                    value={crearForm.tipo_sancion_id}
                    onChange={(e) => setCrearForm({ ...crearForm, tipo_sancion_id: e.target.value })}
                    required
                  >
                    <option value="">Seleccionar...</option>
                    {tiposActivos.map((t) => (
                      <option key={t.id} value={t.id}>{t.nombre}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className={styles.formGroup}>
                <label>Texto predefinido (opcional)</label>
                <select
                  className={styles.select}
                  value={selectedTextoPredefinidoId}
                  onChange={(e) => handleSelectTextoPredefinido(e.target.value)}
                >
                  <option value="">Seleccionar texto predefinido...</option>
                  {textosActivos.map((t) => (
                    <option key={t.id} value={t.id}>{t.nombre}</option>
                  ))}
                </select>
              </div>
              <div className={styles.formGroup}>
                <label>Fecha</label>
                <input
                  type="date"
                  className={styles.input}
                  value={crearForm.fecha}
                  onChange={(e) => {
                    const newForm = { ...crearForm, fecha: e.target.value };
                    setCrearForm(newForm);
                    refreshPlaceholderValues(newForm);
                  }}
                  required
                />
              </div>
              <div className={styles.formGroup}>
                <label>Motivo (obligatorio)</label>
                <textarea
                  className={styles.textarea}
                  value={crearForm.motivo}
                  onChange={(e) => setCrearForm({ ...crearForm, motivo: e.target.value })}
                  required
                />
              </div>
              <div className={styles.formGroup}>
                <label>Descripcion adicional</label>
                <textarea
                  className={styles.textarea}
                  value={crearForm.descripcion}
                  onChange={(e) => setCrearForm({ ...crearForm, descripcion: e.target.value })}
                />
              </div>
              {/* Texto de sanción: si hay placeholders → form dinámico, sino → textarea libre */}
              {currentPlaceholders.length > 0 ? (
                <>
                  <div className={styles.formGroup}>
                    <div className={styles.labelRow}>
                      <label>Campos del documento</label>
                      <button
                        type="button"
                        className={styles.btnHelp}
                        onClick={() => setShowPlaceholderHelp(true)}
                        title="Ver placeholders disponibles"
                      >
                        <HelpCircle size={14} />
                      </button>
                    </div>
                    <div className={styles.placeholderGrid}>
                      {currentPlaceholders.map((ph) => {
                        const isKnown = ph in knownPlaceholders;
                        return (
                          <div key={ph} className={styles.placeholderField}>
                            <label>
                              {ph.replace(/_/g, ' ')}
                              {isKnown && <span className={styles.autoTag}>auto</span>}
                            </label>
                            <input
                              type="text"
                              className={styles.input}
                              value={placeholderValues[ph] || ''}
                              onChange={(e) => {
                                setPlaceholderValues((prev) => ({ ...prev, [ph]: e.target.value }));
                              }}
                              placeholder={knownPlaceholders[ph] || `Valor para {${ph}}`}
                            />
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  <div className={styles.formGroup}>
                    <label>Vista previa del texto</label>
                    <div className={styles.textPreview}>
                      {interpolateText(crearForm.texto_sancion, placeholderValues)}
                    </div>
                  </div>
                </>
              ) : (
                <div className={styles.formGroup}>
                  <label>Texto de la sancion (cuerpo del documento)</label>
                  <textarea
                    className={styles.textarea}
                    value={crearForm.texto_sancion}
                    onChange={(e) => setCrearForm({ ...crearForm, texto_sancion: e.target.value })}
                    rows={6}
                    placeholder="Texto completo que aparecera en el documento de sancion..."
                  />
                </div>
              )}
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Suspension desde</label>
                  <input
                    type="date"
                    className={styles.input}
                    value={crearForm.fecha_desde}
                    onChange={(e) => {
                      const newForm = { ...crearForm, fecha_desde: e.target.value };
                      setCrearForm(newForm);
                      refreshPlaceholderValues(newForm);
                    }}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Suspension hasta</label>
                  <input
                    type="date"
                    className={styles.input}
                    value={crearForm.fecha_hasta}
                    onChange={(e) => {
                      const newForm = { ...crearForm, fecha_hasta: e.target.value };
                      setCrearForm(newForm);
                      refreshPlaceholderValues(newForm);
                    }}
                  />
                </div>
              </div>
              {crearError && <div className={styles.formError}>{crearError}</div>}
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setCrearModalOpen(false)}>
                Cancelar
              </button>
              <button className={styles.btnSave} onClick={handleCrear} disabled={crearSaving}>
                {crearSaving ? 'Guardando...' : 'Crear sancion'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Anular modal */}
      {anularTarget && (
        <div className="modal-overlay-tesla" onClick={() => setAnularTarget(null)}>
          <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Anular sancion</h2>
              <button className="btn-close-tesla" onClick={() => setAnularTarget(null)} aria-label="Cerrar modal">✕</button>
            </div>
            <div className="modal-body-tesla">
              <p style={{ color: 'var(--cf-text-secondary)', fontSize: 'var(--font-sm)', marginBottom: 'var(--spacing-md)' }}>
                Se anulara la sancion del empleado {anularTarget.empleado_nombre || `#${anularTarget.empleado_id}`}.
                Esta accion no se puede deshacer.
              </p>
              <div className={styles.formGroup}>
                <label>Motivo de anulacion (obligatorio)</label>
                <textarea
                  className={styles.textarea}
                  value={anularMotivo}
                  onChange={(e) => setAnularMotivo(e.target.value)}
                  required
                />
              </div>
              {anularError && <div style={{ color: 'var(--cf-accent-red)', fontSize: 'var(--font-xs)' }}>{anularError}</div>}
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setAnularTarget(null)}>
                Cancelar
              </button>
              <button className={styles.btnAnular} onClick={handleAnular} disabled={anularSaving}>
                {anularSaving ? 'Anulando...' : 'Confirmar anulacion'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Detail modal */}
      {detalleOpen && (
        <div className="modal-overlay-tesla" onClick={() => setDetalleOpen(null)}>
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Detalle de sancion</h2>
              <button className="btn-close-tesla" onClick={() => setDetalleOpen(null)} aria-label="Cerrar modal">✕</button>
            </div>
            <div className="modal-body-tesla">
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Empleado</label>
                  <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                    {detalleOpen.empleado_nombre || `#${detalleOpen.empleado_id}`}
                  </div>
                </div>
                <div className={styles.formGroup}>
                  <label>Tipo</label>
                  <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                    {getTipoNombre(detalleOpen.tipo_sancion_id)}
                  </div>
                </div>
              </div>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Fecha</label>
                  <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                    {formatDate(detalleOpen.fecha)}
                  </div>
                </div>
                <div className={styles.formGroup}>
                  <label>Estado</label>
                  <div>
                    {detalleOpen.anulada ? (
                      <span className={styles.statusAnulada}>Anulada</span>
                    ) : (
                      <span className={styles.statusActiva}>Activa</span>
                    )}
                  </div>
                </div>
              </div>
              <div className={styles.formGroup}>
                <label>Motivo</label>
                <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                  {detalleOpen.motivo}
                </div>
              </div>
              {detalleOpen.descripcion && (
                <div className={styles.formGroup}>
                  <label>Descripcion</label>
                  <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                    {detalleOpen.descripcion}
                  </div>
                </div>
              )}
              {detalleOpen.texto_sancion && (
                <div className={styles.formGroup}>
                  <label>Texto de la sancion</label>
                  <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)', whiteSpace: 'pre-wrap' }}>
                    {detalleOpen.texto_sancion}
                  </div>
                </div>
              )}
              {detalleOpen.fecha_desde && (
                <div className={styles.formRow}>
                  <div className={styles.formGroup}>
                    <label>Suspension desde</label>
                    <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                      {formatDate(detalleOpen.fecha_desde)}
                    </div>
                  </div>
                  <div className={styles.formGroup}>
                    <label>Suspension hasta</label>
                    <div style={{ color: 'var(--cf-text-primary)', fontSize: 'var(--font-sm)' }}>
                      {formatDate(detalleOpen.fecha_hasta)}
                    </div>
                  </div>
                </div>
              )}
              {detalleOpen.anulada && detalleOpen.anulada_motivo && (
                <div className={styles.formGroup}>
                  <label>Motivo de anulacion</label>
                  <div style={{ color: 'var(--cf-accent-red)', fontSize: 'var(--font-sm)' }}>
                    {detalleOpen.anulada_motivo}
                  </div>
                </div>
              )}
            </div>
            <div className="modal-footer-tesla">
              <button
                className={styles.btnSave}
                onClick={() => { setDetalleOpen(null); setPdfTarget(detalleOpen); }}
              >
                <FileDown size={14} /> Generar PDF
              </button>
              <button className={styles.btnCancel} onClick={() => setDetalleOpen(null)}>
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Config modal (tipos + textos predefinidos) */}
      {configModalOpen && (
        <div className="modal-overlay-tesla">
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Configurar sanciones</h2>
              <button className="btn-close-tesla" onClick={() => { setConfigModalOpen(false); setEditingTipo(null); setEditingTexto(null); }} aria-label="Cerrar modal">
                <X size={14} />
              </button>
            </div>
            <div className="modal-body-tesla">
              {/* Tabs */}
              <div className={styles.configTabs}>
                <button
                  className={configTab === 'tipos' ? styles.configTabActive : styles.configTab}
                  onClick={() => setConfigTab('tipos')}
                >
                  Tipos de sancion
                </button>
                <button
                  className={configTab === 'textos' ? styles.configTabActive : styles.configTab}
                  onClick={() => setConfigTab('textos')}
                >
                  Textos predefinidos
                </button>
              </div>

              {/* Tab: Tipos de sancion */}
              {configTab === 'tipos' && (
                <div className={styles.tabContent}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Orden</th>
                        <th>Nombre</th>
                        <th>Descuento</th>
                        <th>Estado</th>
                        <th>Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tiposSancion.map((t) => (
                        <tr key={t.id} style={t.activo ? {} : { opacity: 0.5 }}>
                          <td>{t.orden}</td>
                          <td>{t.nombre}</td>
                          <td>{t.requiere_descuento ? 'Si' : 'No'}</td>
                          <td>
                            <span className={t.activo ? styles.statusActiva : styles.statusAnulada}>
                              {t.activo ? 'Activo' : 'Inactivo'}
                            </span>
                          </td>
                          <td>
                            <div className={styles.actions}>
                              <button className={styles.btnView} onClick={() => openEditTipo(t)} title="Editar">
                                <Pencil size={14} />
                              </button>
                              <button
                                className={t.activo ? styles.btnAnular : styles.btnView}
                                onClick={() => handleToggleTipoActivo(t)}
                                title={t.activo ? 'Desactivar' : 'Activar'}
                              >
                                {t.activo ? <Ban size={14} /> : <RotateCcw size={14} />}
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className={styles.configForm}>
                    <h3 className={styles.configFormTitle}>
                      {editingTipo ? `Editar: ${editingTipo.nombre}` : 'Nuevo tipo de sancion'}
                    </h3>
                    <div className={styles.formRow}>
                      <div className={styles.formGroup}>
                        <label>Nombre</label>
                        <input type="text" className={styles.input} value={tipoForm.nombre} onChange={(e) => setTipoForm({ ...tipoForm, nombre: e.target.value })} placeholder="Ej: Apercibimiento" />
                      </div>
                      <div className={styles.formGroup}>
                        <label>Orden</label>
                        <input type="number" className={styles.input} value={tipoForm.orden} onChange={(e) => setTipoForm({ ...tipoForm, orden: Number(e.target.value) })} min={0} />
                      </div>
                    </div>
                    <div className={styles.formGroup}>
                      <label>Descripcion</label>
                      <input type="text" className={styles.input} value={tipoForm.descripcion} onChange={(e) => setTipoForm({ ...tipoForm, descripcion: e.target.value })} placeholder="Descripcion breve" />
                    </div>
                    <label className={styles.checkboxLabel}>
                      <input type="checkbox" checked={tipoForm.requiere_descuento} onChange={(e) => setTipoForm({ ...tipoForm, requiere_descuento: e.target.checked })} />
                      Requiere descuento salarial
                    </label>
                    {tipoError && <div className={styles.formError}>{tipoError}</div>}
                    <div className={styles.configFormActions}>
                      {editingTipo && <button className={styles.btnCancel} onClick={openNewTipo}>Cancelar edicion</button>}
                      <button className={styles.btnSave} onClick={handleSaveTipo} disabled={tipoSaving}>
                        {tipoSaving ? 'Guardando...' : editingTipo ? 'Guardar cambios' : 'Crear tipo'}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Tab: Textos predefinidos */}
              {configTab === 'textos' && (
                <div className={styles.tabContent}>
                  {textosPredLoading ? (
                    <div className={styles.loading}>Cargando textos...</div>
                  ) : (
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Orden</th>
                          <th>Nombre</th>
                          <th>Placeholders</th>
                          <th>Estado</th>
                          <th>Acciones</th>
                        </tr>
                      </thead>
                      <tbody>
                        {textosPredefinidos.map((t) => (
                          <tr key={t.id} style={t.activo ? {} : { opacity: 0.5 }}>
                            <td>{t.orden}</td>
                            <td>{t.nombre}</td>
                            <td>
                              <div className={styles.phBadges}>
                                {extractPlaceholders(t.texto).map((ph) => (
                                  <code key={ph} className={ph in knownPlaceholders ? styles.phKnown : styles.phCustom}>
                                    {ph}
                                  </code>
                                ))}
                                {extractPlaceholders(t.texto).length === 0 && <span style={{ color: 'var(--cf-text-tertiary)', fontSize: 'var(--font-xs)' }}>sin placeholders</span>}
                              </div>
                            </td>
                            <td>
                              <span className={t.activo ? styles.statusActiva : styles.statusAnulada}>
                                {t.activo ? 'Activo' : 'Inactivo'}
                              </span>
                            </td>
                            <td>
                              <div className={styles.actions}>
                                <button className={styles.btnView} onClick={() => openEditTexto(t)} title="Editar">
                                  <Pencil size={14} />
                                </button>
                                <button
                                  className={t.activo ? styles.btnAnular : styles.btnView}
                                  onClick={() => t.activo ? setDeleteConfirmTexto(t) : handleSelectTextoPredefinido('')}
                                  title={t.activo ? 'Desactivar' : 'Ya inactivo'}
                                  disabled={!t.activo}
                                >
                                  <Trash2 size={14} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  <div className={styles.configForm}>
                    <h3 className={styles.configFormTitle}>
                      {editingTexto ? `Editar: ${editingTexto.nombre}` : 'Nuevo texto predefinido'}
                    </h3>
                    <div className={styles.formRow}>
                      <div className={styles.formGroup}>
                        <label>Nombre / Motivo</label>
                        <input type="text" className={styles.input} value={textoForm.nombre} onChange={(e) => setTextoForm({ ...textoForm, nombre: e.target.value })} placeholder="Ej: Llegada tarde" />
                      </div>
                      <div className={styles.formGroup}>
                        <label>Orden</label>
                        <input type="number" className={styles.input} value={textoForm.orden} onChange={(e) => setTextoForm({ ...textoForm, orden: Number(e.target.value) })} min={0} />
                      </div>
                    </div>
                    <div className={styles.formGroup}>
                      <div className={styles.labelRow}>
                        <label>Texto con placeholders</label>
                        <button type="button" className={styles.btnHelp} onClick={() => setShowPlaceholderHelp(true)} title="Ver placeholders disponibles">
                          <HelpCircle size={14} />
                        </button>
                      </div>
                      <textarea
                        className={styles.textarea}
                        value={textoForm.texto}
                        onChange={(e) => setTextoForm({ ...textoForm, texto: e.target.value })}
                        rows={6}
                        placeholder="Ej: Se notifica a {nombre_empleado} legajo {legajo} que..."
                      />
                      {textoForm.texto && (
                        <div className={styles.placeholderPreview}>
                          <span className={styles.previewLabel}>Placeholders detectados:</span>
                          {extractPlaceholders(textoForm.texto).map((ph) => (
                            <code key={ph} className={ph in knownPlaceholders ? styles.phKnown : styles.phCustom}>
                              {`{${ph}}`}
                            </code>
                          ))}
                          {extractPlaceholders(textoForm.texto).length === 0 && (
                            <span style={{ color: 'var(--cf-text-tertiary)', fontSize: 'var(--font-xs)' }}>
                              Ninguno. Usa {'{nombre}'} para agregar.
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                    {textoError && <div className={styles.formError}>{textoError}</div>}
                    <div className={styles.configFormActions}>
                      {editingTexto && <button className={styles.btnCancel} onClick={openNewTexto}>Cancelar edicion</button>}
                      <button className={styles.btnSave} onClick={handleSaveTexto} disabled={textoSaving}>
                        {textoSaving ? 'Guardando...' : editingTexto ? 'Guardar cambios' : 'Crear texto'}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => { setConfigModalOpen(false); setEditingTipo(null); setEditingTexto(null); }}>
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirm texto modal */}
      {deleteConfirmTexto && (
        <div className="modal-overlay-tesla">
          <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Desactivar texto predefinido</h2>
              <button className="btn-close-tesla" onClick={() => setDeleteConfirmTexto(null)} aria-label="Cerrar modal"><X size={14} /></button>
            </div>
            <div className="modal-body-tesla">
              <p style={{ color: 'var(--cf-text-secondary)', fontSize: 'var(--font-sm)' }}>
                Se desactivara el texto <strong>{deleteConfirmTexto.nombre}</strong>. Las sanciones existentes que lo usen no se veran afectadas.
              </p>
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setDeleteConfirmTexto(null)}>Cancelar</button>
              <button className={styles.btnAnular} onClick={handleDeleteTexto}>Desactivar</button>
            </div>
          </div>
        </div>
      )}

      {/* Placeholder help modal */}
      {showPlaceholderHelp && (
        <div className="modal-overlay-tesla">
          <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Placeholders disponibles</h2>
              <button className="btn-close-tesla" onClick={() => setShowPlaceholderHelp(false)} aria-label="Cerrar modal">
                <X size={14} />
              </button>
            </div>
            <div className="modal-body-tesla">
              <p style={{ color: 'var(--cf-text-secondary)', fontSize: 'var(--font-sm)', marginBottom: 'var(--spacing-md)' }}>
                Usa estos nombres entre llaves en el texto predeterminado del tipo de sancion. Los marcados como <strong>auto</strong> se completan automaticamente.
              </p>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Placeholder</th>
                    <th>Descripcion</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(knownPlaceholders).map(([key, desc]) => (
                    <tr key={key}>
                      <td><code>{`{${key}}`}</code></td>
                      <td>{desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p style={{ color: 'var(--cf-text-tertiary)', fontSize: 'var(--font-xs)', marginTop: 'var(--spacing-md)' }}>
                Tambien podes usar placeholders custom (ej: {'{motivo_detallado}'}). Se mostraran como campo de texto libre.
              </p>
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setShowPlaceholderHelp(false)}>
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* PDF Generator Modal */}
      {pdfTarget && (
        <DocumentGeneratorModal
          isOpen={!!pdfTarget}
          onClose={() => setPdfTarget(null)}
          contexto="sanciones"
          entityData={{
            ...pdfTarget,
            empleado_legajo: pdfTarget.empleado_legajo,
            empleado_sector: pdfTarget.empleado_sector,
            empleado_dni: pdfTarget.empleado_dni,
            tipo_sancion_nombre: getTipoNombre(pdfTarget.tipo_sancion_id),
            dias_suspension: (() => {
              if (pdfTarget.fecha_desde && pdfTarget.fecha_hasta) {
                const desde = new Date(pdfTarget.fecha_desde + 'T12:00:00');
                const hasta = new Date(pdfTarget.fecha_hasta + 'T12:00:00');
                const diff = Math.round((hasta - desde) / (1000 * 60 * 60 * 24)) + 1;
                return diff > 0 ? String(diff) : '';
              }
              return '';
            })(),
          }}
        />
      )}
    </div>
  );
}
