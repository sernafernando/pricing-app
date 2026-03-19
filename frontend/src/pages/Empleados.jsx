import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI } from '../services/api';
import {
  Plus,
  Search,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  Users,
  Edit3,
  Trash2,
  User,
  Clock,
  UserMinus,
  UserPlus,
  FileText,
  Upload,
  Download,
  AlertCircle,
  Settings,
  Check,
  X,
  MapPin,
  Navigation,
  ExternalLink,
  FileDown,
} from 'lucide-react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix Leaflet default marker icon
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});
import DocumentGeneratorModal from '../components/DocumentGeneratorModal';
import styles from './Empleados.module.css';

const ESTADOS = [
  { value: '', label: 'Todos' },
  { value: 'activo', label: 'Activo' },
  { value: 'licencia', label: 'Licencia' },
  { value: 'baja', label: 'Baja' },
];

const ESTADO_COLORS = {
  activo: 'statusActive',
  licencia: 'statusLicencia',
  baja: 'statusBaja',
};

export default function Empleados() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rrhh.gestionar');
  const puedeConfig = tienePermiso('rrhh.config');
  const puedeImprimir = tienePermiso('documentos.imprimir');

  // --- Page tab ---
  const [pageTab, setPageTab] = useState('empleados');

  // --- State ---
  const [empleados, setEmpleados] = useState([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [estado, setEstado] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [area, setArea] = useState('');
  const [puesto, setPuesto] = useState('');
  const [sortBy, setSortBy] = useState('');
  const [sortOrder, setSortOrder] = useState('asc');
  const [filtroOpciones, setFiltroOpciones] = useState({ areas: [], puestos: [] });

  // Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [editando, setEditando] = useState(null);
  const [formData, setFormData] = useState({});
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  // Delete confirmation state
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [actionError, setActionError] = useState(null);

  // Turnos asignados (en modal de edición)
  const [turnosEmpleado, setTurnosEmpleado] = useState([]);
  const [loadingTurnos, setLoadingTurnos] = useState(false);
  const [horariosDisponibles, setHorariosDisponibles] = useState([]);
  const [nuevoTurnoId, setNuevoTurnoId] = useState('');
  const [nuevaTurnoPrioridad, setNuevaTurnoPrioridad] = useState('1');
  const [asignandoTurno, setAsignandoTurno] = useState(false);
  const [turnoError, setTurnoError] = useState(null);

  // Documentos del empleado (en modal de edición)
  const [documentos, setDocumentos] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [tiposDocumento, setTiposDocumento] = useState([]);
  const [docError, setDocError] = useState(null);
  const [uploadingDoc, setUploadingDoc] = useState(false);
  const [docForm, setDocForm] = useState({
    tipo_documento_id: '', descripcion: '', fecha_vencimiento: '', numero_documento: '',
  });

  // Modal tab (solo en edición)
  const [modalTab, setModalTab] = useState('datos');

  // --- Generar documento ---
  const [docGenOpen, setDocGenOpen] = useState(false);
  const [docGenEmpleado, setDocGenEmpleado] = useState(null);

  // --- Geocodificación ---
  const [geocoding, setGeocoding] = useState(false);
  const [geoError, setGeoError] = useState(null);

  // --- Motivos de baja ---
  const [motivosBaja, setMotivosBaja] = useState([]);

  // --- Tipos de documento CRUD (page tab) ---
  const [tiposConfig, setTiposConfig] = useState([]);
  const [loadingTipos, setLoadingTipos] = useState(false);
  const [tipoForm, setTipoForm] = useState({ nombre: '', descripcion: '', requiere_vencimiento: false });
  const [editandoTipo, setEditandoTipo] = useState(null);
  const [savingTipo, setSavingTipo] = useState(false);
  const [tipoError, setTipoError] = useState(null);

  // --- Motivos de baja CRUD (page tab) ---
  const [motivosConfig, setMotivosConfig] = useState([]);
  const [loadingMotivos, setLoadingMotivos] = useState(false);
  const [motivoForm, setMotivoForm] = useState({ nombre: '', descripcion: '', requiere_documentacion: false });
  const [editandoMotivo, setEditandoMotivo] = useState(null);
  const [savingMotivo, setSavingMotivo] = useState(false);
  const [motivoError, setMotivoError] = useState(null);

  const PAGE_SIZE = 50;

  // --- Debounce search ---
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(timer);
  }, [search]);

  // --- Fetch filter options (areas, puestos) ---
  useEffect(() => {
    const fetchFiltros = async () => {
      try {
        const { data } = await rrhhAPI.obtenerFiltrosEmpleados();
        setFiltroOpciones(data);
      } catch {
        setFiltroOpciones({ areas: [], puestos: [] });
      }
    };
    fetchFiltros();
  }, []);

  // --- Fetch empleados ---
  const cargarEmpleados = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: PAGE_SIZE };
      if (debouncedSearch) params.search = debouncedSearch;
      if (estado) params.estado = estado;
      if (area) params.area = area;
      if (puesto) params.puesto = puesto;
      if (sortBy) {
        params.sort_by = sortBy;
        params.sort_order = sortOrder;
      }
      const { data } = await rrhhAPI.listarEmpleados(params);
      setEmpleados(data.items);
      setTotal(data.total);
    } catch {
      setEmpleados([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch, estado, area, puesto, sortBy, sortOrder]);

  useEffect(() => {
    cargarEmpleados();
  }, [cargarEmpleados]);

  // Reset page when debounced search changes
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  // --- Handlers ---
  const handleNuevo = () => {
    setEditando(null);
    setFormData({
      nombre: '',
      apellido: '',
      dni: '',
      cuil: '',
      legajo: '',
      fecha_nacimiento: '',
      fecha_ingreso: new Date().toISOString().split('T')[0],
      fecha_egreso: '',
      puesto: '',
      area: '',
      estado: 'activo',
      calle: '',
      numero: '',
      piso_depto: '',
      entre_calles: '',
      localidad: '',
      provincia: '',
      codigo_postal: '',
      domicilio: '',
      latitud: null,
      longitud: null,
      telefono: '',
      email_personal: '',
      observaciones: '',
    });
    setFormError(null);
    setModalOpen(true);
  };

  const handleEditar = (emp) => {
    setEditando(emp);
    setFormData({
      nombre: emp.nombre || '',
      apellido: emp.apellido || '',
      dni: emp.dni || '',
      cuil: emp.cuil || '',
      legajo: emp.legajo || '',
      fecha_nacimiento: emp.fecha_nacimiento || '',
      fecha_ingreso: emp.fecha_ingreso || '',
      fecha_egreso: emp.fecha_egreso || '',
      puesto: emp.puesto || '',
      area: emp.area || '',
      estado: emp.estado || 'activo',
      motivo_baja_id: emp.motivo_baja_id || null,
      detalle_baja: emp.detalle_baja || '',
      calle: emp.calle || '',
      numero: emp.numero || '',
      piso_depto: emp.piso_depto || '',
      entre_calles: emp.entre_calles || '',
      localidad: emp.localidad || '',
      provincia: emp.provincia || '',
      codigo_postal: emp.codigo_postal || '',
      domicilio: emp.domicilio || '',
      latitud: emp.latitud || null,
      longitud: emp.longitud || null,
      telefono: emp.telefono || '',
      email_personal: emp.email_personal || '',
      observaciones: emp.observaciones || '',
    });
    setFormError(null);
    setModalOpen(true);
  };

  const handleGuardar = async () => {
    setSaving(true);
    setFormError(null);
    try {
      // Limpiar formData antes de enviar al backend
      const cleanData = {};
      for (const [key, value] of Object.entries(formData)) {
        // Convertir strings vacíos a null (Pydantic no parsea '' como date/int/float)
        cleanData[key] = value === '' ? null : value;
      }

      if (editando) {
        await rrhhAPI.actualizarEmpleado(editando.id, cleanData);
      } else {
        await rrhhAPI.crearEmpleado(cleanData);
      }
      setModalOpen(false);
      cargarEmpleados();
    } catch (err) {
      const msg = err.response?.data?.detail || 'Error al guardar';
      setFormError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleEliminar = (emp) => {
    if (!puedeGestionar) return;
    setActionError(null);
    setConfirmDelete(emp);
  };

  const handleConfirmDelete = async () => {
    if (!confirmDelete) return;
    setActionError(null);
    try {
      await rrhhAPI.eliminarEmpleado(confirmDelete.id);
      setConfirmDelete(null);
      cargarEmpleados();
    } catch (err) {
      setActionError(err.response?.data?.detail || 'Error al desactivar empleado');
    }
  };

  const handleField = (field, value) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  // ── Turnos del empleado (carga al abrir modal de edición) ──
  const cargarTurnosEmpleado = useCallback(async (empleadoId) => {
    setLoadingTurnos(true);
    setTurnoError(null);
    try {
      const [turnosRes, horariosRes] = await Promise.all([
        rrhhAPI.listarHorariosEmpleado(empleadoId),
        rrhhAPI.listarHorarios({ solo_activos: true }),
      ]);
      setTurnosEmpleado(Array.isArray(turnosRes.data) ? turnosRes.data : []);
      setHorariosDisponibles(Array.isArray(horariosRes.data) ? horariosRes.data : []);
    } catch {
      setTurnosEmpleado([]);
      setHorariosDisponibles([]);
    } finally {
      setLoadingTurnos(false);
    }
  }, []);

  useEffect(() => {
    if (modalOpen && editando) {
      cargarTurnosEmpleado(editando.id);
    } else {
      setTurnosEmpleado([]);
      setHorariosDisponibles([]);
      setNuevoTurnoId('');
      setNuevaTurnoPrioridad('1');
      setTurnoError(null);
    }
  }, [modalOpen, editando, cargarTurnosEmpleado]);

  const handleAsignarTurno = async () => {
    if (!nuevoTurnoId || !editando) return;
    setAsignandoTurno(true);
    setTurnoError(null);
    try {
      await rrhhAPI.asignarHorarioEmpleado(editando.id, {
        horario_config_id: parseInt(nuevoTurnoId, 10),
        prioridad: parseInt(nuevaTurnoPrioridad, 10),
      });
      setNuevoTurnoId('');
      setNuevaTurnoPrioridad('1');
      cargarTurnosEmpleado(editando.id);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Error al asignar turno';
      setTurnoError(msg);
    } finally {
      setAsignandoTurno(false);
    }
  };

  const handleDesasignarTurno = async (asignacionId) => {
    if (!editando) return;
    setTurnoError(null);
    try {
      await rrhhAPI.desasignarHorarioEmpleado(asignacionId);
      cargarTurnosEmpleado(editando.id);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Error al desasignar turno';
      setTurnoError(msg);
    }
  };

  const formatTime = (timeStr) => {
    if (!timeStr) return '-';
    return timeStr.slice(0, 5);
  };

  // ── Documentos del empleado ──
  const cargarDocumentos = useCallback(async (empleadoId) => {
    setLoadingDocs(true);
    setDocError(null);
    try {
      const [docsRes, tiposRes] = await Promise.all([
        rrhhAPI.listarDocumentos(empleadoId),
        rrhhAPI.listarTiposDocumento({ activo: true }),
      ]);
      setDocumentos(Array.isArray(docsRes.data) ? docsRes.data : []);
      setTiposDocumento(Array.isArray(tiposRes.data) ? tiposRes.data : []);
    } catch {
      setDocumentos([]);
      setTiposDocumento([]);
    } finally {
      setLoadingDocs(false);
    }
  }, []);

  useEffect(() => {
    if (modalOpen && editando && modalTab === 'documentos') {
      cargarDocumentos(editando.id);
    }
  }, [modalOpen, editando, modalTab, cargarDocumentos]);

  // Load motivos de baja when baja tab opens
  useEffect(() => {
    if (modalOpen && editando && modalTab === 'baja') {
      const fetchMotivos = async () => {
        try {
          const { data } = await rrhhAPI.listarMotivosBaja({ activo: true });
          setMotivosBaja(Array.isArray(data) ? data : []);
        } catch {
          setMotivosBaja([]);
        }
      };
      fetchMotivos();
    }
  }, [modalOpen, editando, modalTab]);

  // Reset modal tab when opening
  useEffect(() => {
    if (modalOpen) {
      setModalTab('datos');
      setDocumentos([]);
      setDocError(null);
      setDocForm({ tipo_documento_id: '', descripcion: '', fecha_vencimiento: '', numero_documento: '' });
    }
  }, [modalOpen]);

  const handleSubirDocumento = async (file) => {
    if (!editando || !docForm.tipo_documento_id) return;
    setUploadingDoc(true);
    setDocError(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const params = { tipo_documento_id: parseInt(docForm.tipo_documento_id, 10) };
      if (docForm.descripcion) params.descripcion = docForm.descripcion;
      if (docForm.fecha_vencimiento) params.fecha_vencimiento = docForm.fecha_vencimiento;
      if (docForm.numero_documento) params.numero_documento = docForm.numero_documento;
      await rrhhAPI.subirDocumento(editando.id, fd, params);
      setDocForm({ tipo_documento_id: '', descripcion: '', fecha_vencimiento: '', numero_documento: '' });
      cargarDocumentos(editando.id);
    } catch (err) {
      setDocError(err.response?.data?.detail || 'Error al subir documento');
    } finally {
      setUploadingDoc(false);
    }
  };

  const handleDescargarDocumento = async (docId, nombreArchivo) => {
    try {
      const { data } = await rrhhAPI.descargarDocumento(docId);
      const url = window.URL.createObjectURL(data);
      const link = document.createElement('a');
      link.href = url;
      link.download = nombreArchivo;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch {
      setDocError('Error al descargar documento');
    }
  };

  const handleEliminarDocumento = async (docId) => {
    if (!editando) return;
    setDocError(null);
    try {
      await rrhhAPI.eliminarDocumento(docId);
      cargarDocumentos(editando.id);
    } catch (err) {
      setDocError(err.response?.data?.detail || 'Error al eliminar documento');
    }
  };

  const formatFileSize = (bytes) => {
    if (!bytes) return '-';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatDateShort = (dateStr) => {
    if (!dateStr) return '-';
    const d = new Date(dateStr + 'T12:00:00');
    return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  };

  const handleGeocodificar = async () => {
    if (!editando) return;
    setGeocoding(true);
    setGeoError(null);
    try {
      // Primero guardar la dirección actual
      await rrhhAPI.actualizarEmpleado(editando.id, {
        calle: formData.calle || null,
        numero: formData.numero || null,
        piso_depto: formData.piso_depto || null,
        entre_calles: formData.entre_calles || null,
        localidad: formData.localidad || null,
        provincia: formData.provincia || null,
        codigo_postal: formData.codigo_postal || null,
        domicilio: formData.domicilio || null,
      });
      // Luego geocodificar
      const { data } = await rrhhAPI.geocodificarEmpleado(editando.id);
      handleField('latitud', data.latitud);
      handleField('longitud', data.longitud);
    } catch (err) {
      setGeoError(err.response?.data?.detail || 'Error al geocodificar');
    } finally {
      setGeocoding(false);
    }
  };

  const isVencido = (fechaVenc) => {
    if (!fechaVenc) return false;
    return new Date(fechaVenc + 'T23:59:59') < new Date();
  };

  // ── Tipos de documento CRUD ──
  const cargarTiposConfig = useCallback(async () => {
    setLoadingTipos(true);
    try {
      const { data } = await rrhhAPI.listarTiposDocumento({});
      setTiposConfig(Array.isArray(data) ? data : []);
    } catch {
      setTiposConfig([]);
    } finally {
      setLoadingTipos(false);
    }
  }, []);

  useEffect(() => {
    if (pageTab === 'tipos') cargarTiposConfig();
  }, [pageTab, cargarTiposConfig]);

  const handleTipoSubmit = async () => {
    if (!tipoForm.nombre.trim()) return;
    setSavingTipo(true);
    setTipoError(null);
    try {
      if (editandoTipo) {
        await rrhhAPI.actualizarTipoDocumento(editandoTipo.id, tipoForm);
      } else {
        await rrhhAPI.crearTipoDocumento(tipoForm);
      }
      setTipoForm({ nombre: '', descripcion: '', requiere_vencimiento: false });
      setEditandoTipo(null);
      cargarTiposConfig();
    } catch (err) {
      setTipoError(err.response?.data?.detail || 'Error al guardar tipo');
    } finally {
      setSavingTipo(false);
    }
  };

  const handleEditTipo = (tipo) => {
    setEditandoTipo(tipo);
    setTipoForm({
      nombre: tipo.nombre,
      descripcion: tipo.descripcion || '',
      requiere_vencimiento: tipo.requiere_vencimiento,
    });
    setTipoError(null);
  };

  const handleCancelEditTipo = () => {
    setEditandoTipo(null);
    setTipoForm({ nombre: '', descripcion: '', requiere_vencimiento: false });
    setTipoError(null);
  };

  const handleToggleTipoActivo = async (tipo) => {
    try {
      await rrhhAPI.actualizarTipoDocumento(tipo.id, { activo: !tipo.activo });
      cargarTiposConfig();
    } catch {
      setTipoError('Error al cambiar estado');
    }
  };

  // ── Motivos de baja CRUD ──
  const cargarMotivosConfig = useCallback(async () => {
    setLoadingMotivos(true);
    try {
      const { data } = await rrhhAPI.listarMotivosBaja({});
      setMotivosConfig(Array.isArray(data) ? data : []);
    } catch {
      setMotivosConfig([]);
    } finally {
      setLoadingMotivos(false);
    }
  }, []);

  useEffect(() => {
    if (pageTab === 'motivos') cargarMotivosConfig();
  }, [pageTab, cargarMotivosConfig]);

  const handleMotivoSubmit = async () => {
    if (!motivoForm.nombre.trim()) return;
    setSavingMotivo(true);
    setMotivoError(null);
    try {
      if (editandoMotivo) {
        await rrhhAPI.actualizarMotivoBaja(editandoMotivo.id, motivoForm);
      } else {
        await rrhhAPI.crearMotivoBaja(motivoForm);
      }
      setMotivoForm({ nombre: '', descripcion: '', requiere_documentacion: false });
      setEditandoMotivo(null);
      cargarMotivosConfig();
    } catch (err) {
      setMotivoError(err.response?.data?.detail || 'Error al guardar motivo');
    } finally {
      setSavingMotivo(false);
    }
  };

  const handleEditMotivo = (m) => {
    setEditandoMotivo(m);
    setMotivoForm({
      nombre: m.nombre,
      descripcion: m.descripcion || '',
      requiere_documentacion: m.requiere_documentacion,
    });
    setMotivoError(null);
  };

  const handleCancelEditMotivo = () => {
    setEditandoMotivo(null);
    setMotivoForm({ nombre: '', descripcion: '', requiere_documentacion: false });
    setMotivoError(null);
  };

  const handleToggleMotivoActivo = async (m) => {
    try {
      await rrhhAPI.actualizarMotivoBaja(m.id, { activo: !m.activo });
      cargarMotivosConfig();
    } catch {
      setMotivoError('Error al cambiar estado');
    }
  };

  const SortHeader = ({ field, children }) => {
    const isActive = sortBy === field;
    return (
      <th
        className={styles.sortableHeader}
        onClick={() => {
          if (sortBy === field) {
            setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'));
          } else {
            setSortBy(field);
            setSortOrder('asc');
          }
          setPage(1);
        }}
      >
        {children}
        {isActive && (
          <span className={styles.sortIndicator}>
            {sortOrder === 'asc' ? '\u25B2' : '\u25BC'}
          </span>
        )}
      </th>
    );
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Users size={24} />
          <h1>Empleados</h1>
          <span className={styles.badge}>{total}</span>
        </div>
        <div className={styles.headerActions}>
          {puedeGestionar && pageTab === 'empleados' && (
            <button className={styles.btnCreate} onClick={handleNuevo}>
              <Plus size={16} />
              Nuevo Empleado
            </button>
          )}
        </div>
      </div>

      {/* Page tabs */}
      {puedeConfig && (
        <div className={styles.pageTabs}>
          <button
            className={`${styles.pageTab} ${pageTab === 'empleados' ? styles.pageTabActive : ''}`}
            onClick={() => setPageTab('empleados')}
          >
            <Users size={14} /> Empleados
          </button>
          <button
            className={`${styles.pageTab} ${pageTab === 'tipos' ? styles.pageTabActive : ''}`}
            onClick={() => setPageTab('tipos')}
          >
            <Settings size={14} /> Tipos de Documento
          </button>
          <button
            className={`${styles.pageTab} ${pageTab === 'motivos' ? styles.pageTabActive : ''}`}
            onClick={() => setPageTab('motivos')}
          >
            <Settings size={14} /> Motivos de Baja
          </button>
        </div>
      )}

      {/* ─── PAGE TAB: Tipos de Documento ─── */}
      {pageTab === 'tipos' && puedeConfig && (
        <div className={styles.tiposSection}>
          {tipoError && <div className={styles.formError}>{tipoError}</div>}

          {/* Create/Edit form */}
          <div className={styles.tipoFormRow}>
            <input
              className={styles.input}
              type="text"
              placeholder="Nombre del tipo (ej: DNI Frente)"
              value={tipoForm.nombre}
              onChange={(e) => setTipoForm({ ...tipoForm, nombre: e.target.value })}
              maxLength={100}
            />
            <input
              className={styles.input}
              type="text"
              placeholder="Descripción (opcional)"
              value={tipoForm.descripcion}
              onChange={(e) => setTipoForm({ ...tipoForm, descripcion: e.target.value })}
              maxLength={500}
            />
            <label className={styles.tipoCheckLabel}>
              <input
                type="checkbox"
                checked={tipoForm.requiere_vencimiento}
                onChange={(e) => setTipoForm({ ...tipoForm, requiere_vencimiento: e.target.checked })}
              />
              Vence
            </label>
            <button
              className={styles.btnSave}
              onClick={handleTipoSubmit}
              disabled={savingTipo || !tipoForm.nombre.trim()}
            >
              {savingTipo ? '...' : editandoTipo ? 'Actualizar' : 'Crear'}
            </button>
            {editandoTipo && (
              <button className={styles.btnCancel} onClick={handleCancelEditTipo}>
                <X size={14} />
              </button>
            )}
          </div>

          {/* List */}
          {loadingTipos ? (
            <div className={styles.loadingCell}>Cargando tipos...</div>
          ) : tiposConfig.length === 0 ? (
            <div className={styles.emptyCell}>No hay tipos de documento configurados</div>
          ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Nombre</th>
                    <th>Descripción</th>
                    <th>Vencimiento</th>
                    <th>Estado</th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {tiposConfig.map((t) => (
                    <tr key={t.id}>
                      <td><strong>{t.nombre}</strong></td>
                      <td>{t.descripcion || '-'}</td>
                      <td>{t.requiere_vencimiento ? 'Sí' : 'No'}</td>
                      <td>
                        <span className={`${styles.statusBadge} ${t.activo ? styles.statusActive : styles.statusBaja}`}>
                          {t.activo ? 'Activo' : 'Inactivo'}
                        </span>
                      </td>
                      <td className={styles.actions}>
                        <button
                          className={styles.btnEdit}
                          onClick={() => handleEditTipo(t)}
                          title="Editar"
                        >
                          <Edit3 size={14} />
                        </button>
                        <button
                          className={t.activo ? styles.btnDanger : styles.btnEdit}
                          onClick={() => handleToggleTipoActivo(t)}
                          title={t.activo ? 'Desactivar' : 'Activar'}
                        >
                          {t.activo ? <X size={14} /> : <Check size={14} />}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ─── PAGE TAB: Motivos de Baja ─── */}
      {pageTab === 'motivos' && puedeConfig && (
        <div className={styles.tiposSection}>
          {motivoError && <div className={styles.formError}>{motivoError}</div>}

          <div className={styles.tipoFormRow}>
            <input
              className={styles.input}
              type="text"
              placeholder="Nombre del motivo (ej: Renuncia)"
              value={motivoForm.nombre}
              onChange={(e) => setMotivoForm({ ...motivoForm, nombre: e.target.value })}
              maxLength={100}
            />
            <input
              className={styles.input}
              type="text"
              placeholder="Descripción (opcional)"
              value={motivoForm.descripcion}
              onChange={(e) => setMotivoForm({ ...motivoForm, descripcion: e.target.value })}
              maxLength={500}
            />
            <label className={styles.tipoCheckLabel}>
              <input
                type="checkbox"
                checked={motivoForm.requiere_documentacion}
                onChange={(e) => setMotivoForm({ ...motivoForm, requiere_documentacion: e.target.checked })}
              />
              Req. doc
            </label>
            <button
              className={styles.btnSave}
              onClick={handleMotivoSubmit}
              disabled={savingMotivo || !motivoForm.nombre.trim()}
            >
              {savingMotivo ? '...' : editandoMotivo ? 'Actualizar' : 'Crear'}
            </button>
            {editandoMotivo && (
              <button className={styles.btnCancel} onClick={handleCancelEditMotivo}>
                <X size={14} />
              </button>
            )}
          </div>

          {loadingMotivos ? (
            <div className={styles.loadingCell}>Cargando motivos...</div>
          ) : motivosConfig.length === 0 ? (
            <div className={styles.emptyCell}>No hay motivos de baja configurados</div>
          ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Nombre</th>
                    <th>Descripción</th>
                    <th>Req. Doc</th>
                    <th>Estado</th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {motivosConfig.map((m) => (
                    <tr key={m.id}>
                      <td><strong>{m.nombre}</strong></td>
                      <td>{m.descripcion || '-'}</td>
                      <td>{m.requiere_documentacion ? 'Sí' : 'No'}</td>
                      <td>
                        <span className={`${styles.statusBadge} ${m.activo ? styles.statusActive : styles.statusBaja}`}>
                          {m.activo ? 'Activo' : 'Inactivo'}
                        </span>
                      </td>
                      <td className={styles.actions}>
                        <button
                          className={styles.btnEdit}
                          onClick={() => handleEditMotivo(m)}
                          title="Editar"
                        >
                          <Edit3 size={14} />
                        </button>
                        <button
                          className={m.activo ? styles.btnDanger : styles.btnEdit}
                          onClick={() => handleToggleMotivoActivo(m)}
                          title={m.activo ? 'Desactivar' : 'Activar'}
                        >
                          {m.activo ? <X size={14} /> : <Check size={14} />}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ─── PAGE TAB: Empleados ─── */}
      {pageTab === 'empleados' && (
      <>
      {/* Filters */}
      <div className={styles.filters}>
        <div className={styles.searchBox}>
          <Search size={16} />
          <input
            type="text"
            placeholder="Buscar por nombre, DNI, legajo..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={styles.searchInput}
          />
        </div>
        <select
          value={estado}
          onChange={(e) => { setEstado(e.target.value); setPage(1); }}
          className={styles.filterSelect}
        >
          {ESTADOS.map((e) => (
            <option key={e.value} value={e.value}>{e.label}</option>
          ))}
        </select>
        <select
          value={area}
          onChange={(e) => { setArea(e.target.value); setPage(1); }}
          className={styles.filterSelect}
        >
          <option value="">Todas las areas</option>
          {filtroOpciones.areas.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        <select
          value={puesto}
          onChange={(e) => { setPuesto(e.target.value); setPage(1); }}
          className={styles.filterSelect}
        >
          <option value="">Todos los puestos</option>
          {filtroOpciones.puestos.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <button
          className={styles.btnRefresh}
          onClick={() => { setSearch(''); setEstado(''); setArea(''); setPuesto(''); setSortBy(''); setSortOrder('asc'); setPage(1); }}
          title="Limpiar filtros"
        >
          <RotateCcw size={16} />
        </button>
      </div>

      {/* Table */}
      <div className={styles.tableWrapper}>
        <table className={styles.table}>
          <thead>
            <tr>
              <SortHeader field="legajo">Legajo</SortHeader>
              <SortHeader field="nombre">Nombre</SortHeader>
              <th>DNI</th>
              <SortHeader field="puesto">Puesto</SortHeader>
              <SortHeader field="area">Area</SortHeader>
              <th>Estado</th>
              <SortHeader field="fecha_ingreso">Ingreso</SortHeader>
              {puedeGestionar && <th>Acciones</th>}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={puedeGestionar ? 8 : 7} className={styles.loadingCell}>
                  Cargando...
                </td>
              </tr>
            ) : empleados.length === 0 ? (
              <tr>
                <td colSpan={puedeGestionar ? 8 : 7} className={styles.emptyCell}>
                  No se encontraron empleados
                </td>
              </tr>
            ) : (
              empleados.map((emp) => (
                <tr key={emp.id} className={styles.row}>
                  <td className={styles.legajo}>{emp.legajo}</td>
                  <td>
                    <div className={styles.nameCell}>
                      <User size={14} />
                      {emp.apellido}, {emp.nombre}
                    </div>
                  </td>
                  <td>{emp.dni}</td>
                  <td>{emp.puesto || '-'}</td>
                  <td>{emp.area || '-'}</td>
                  <td>
                    <span className={`${styles.statusBadge} ${styles[ESTADO_COLORS[emp.estado]] || ''}`}>
                      {emp.estado}
                    </span>
                  </td>
                  <td>{emp.fecha_ingreso}</td>
                  {(puedeGestionar || puedeImprimir) && (
                    <td className={styles.actions}>
                      {puedeImprimir && (
                        <button
                          onClick={() => { setDocGenEmpleado(emp); setDocGenOpen(true); }}
                          className={styles.btnEdit}
                          title="Generar documento PDF"
                        >
                          <FileDown size={14} />
                        </button>
                      )}
                      {puedeGestionar && (
                        <button
                          onClick={() => handleEditar(emp)}
                          className={styles.btnEdit}
                          title="Editar"
                        >
                          <Edit3 size={14} />
                        </button>
                      )}
                      {puedeGestionar && (
                        <button
                          onClick={() => handleEliminar(emp)}
                          className={styles.btnDanger}
                          title="Desactivar"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className={styles.pagination}>
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className={styles.btnPage}
          >
            <ChevronLeft size={16} />
          </button>
          <span className={styles.pageInfo}>
            {page} / {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            className={styles.btnPage}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}

      </>
      )}

      {/* Confirm Delete Modal */}
      {confirmDelete && (
        <div className="modal-overlay-tesla" onClick={() => setConfirmDelete(null)}>
          <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Confirmar desactivación</h2>
              <button className="btn-close-tesla" onClick={() => setConfirmDelete(null)} aria-label="Cerrar">✕</button>
            </div>
            <div className="modal-body-tesla">
              <p style={{ color: 'var(--cf-text-secondary)', fontSize: 'var(--font-sm)' }}>
                ¿Desactivar a <strong>{confirmDelete.apellido}, {confirmDelete.nombre}</strong> (Legajo: {confirmDelete.legajo})?
                Esta acción cambiará su estado a baja.
              </p>
              {actionError && <div className={styles.formError}>{actionError}</div>}
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setConfirmDelete(null)}>Cancelar</button>
              <button className={styles.btnDanger} onClick={handleConfirmDelete}>Confirmar</button>
            </div>
          </div>
        </div>
      )}

      {/* Modal */}
      {/* Modals (always rendered, not inside pageTab conditional) */}
      {modalOpen && (
        <div className="modal-overlay-tesla" onClick={() => setModalOpen(false)}>
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">{editando ? 'Editar Empleado' : 'Nuevo Empleado'}</h2>
              <button className="btn-close-tesla" onClick={() => setModalOpen(false)}>✕</button>
            </div>

            {/* Tabs (solo en edición) */}
            {editando && (
              <div className={styles.modalTabs}>
                <button
                  className={`${styles.modalTab} ${modalTab === 'datos' ? styles.modalTabActive : ''}`}
                  onClick={() => setModalTab('datos')}
                >
                  <User size={14} /> Datos
                </button>
                <button
                  className={`${styles.modalTab} ${modalTab === 'direccion' ? styles.modalTabActive : ''}`}
                  onClick={() => setModalTab('direccion')}
                >
                  <MapPin size={14} /> Dirección
                </button>
                <button
                  className={`${styles.modalTab} ${modalTab === 'turnos' ? styles.modalTabActive : ''}`}
                  onClick={() => setModalTab('turnos')}
                >
                  <Clock size={14} /> Turnos
                </button>
                <button
                  className={`${styles.modalTab} ${modalTab === 'documentos' ? styles.modalTabActive : ''}`}
                  onClick={() => setModalTab('documentos')}
                >
                  <FileText size={14} /> Documentos
                  {documentos.length > 0 && (
                    <span className={styles.tabBadge}>{documentos.length}</span>
                  )}
                </button>
                <button
                  className={`${styles.modalTab} ${modalTab === 'baja' ? styles.modalTabActive : ''} ${editando?.estado === 'baja' ? styles.modalTabBaja : ''}`}
                  onClick={() => setModalTab('baja')}
                >
                  <AlertCircle size={14} /> Baja
                </button>
              </div>
            )}

            <div className="modal-body-tesla">

              {/* ─── TAB: Datos ─── */}
              {(modalTab === 'datos' || !editando) && (
                <>
                  {formError && <div className={styles.formError}>{formError}</div>}
                  <div className={styles.formGrid}>
                    <div className={styles.formGroup}>
                      <label>Nombre *</label>
                      <input
                        className={styles.input}
                        value={formData.nombre}
                        onChange={(e) => handleField('nombre', e.target.value)}
                      />
                    </div>
                    <div className={styles.formGroup}>
                      <label>Apellido *</label>
                      <input
                        className={styles.input}
                        value={formData.apellido}
                        onChange={(e) => handleField('apellido', e.target.value)}
                      />
                    </div>
                    <div className={styles.formGroup}>
                      <label>DNI *</label>
                      <input
                        className={styles.input}
                        value={formData.dni}
                        onChange={(e) => handleField('dni', e.target.value)}
                      />
                    </div>
                    <div className={styles.formGroup}>
                      <label>CUIL</label>
                      <input
                        className={styles.input}
                        value={formData.cuil}
                        onChange={(e) => handleField('cuil', e.target.value)}
                      />
                    </div>
                    <div className={styles.formGroup}>
                      <label>Legajo *</label>
                      <input
                        className={styles.input}
                        value={formData.legajo}
                        onChange={(e) => handleField('legajo', e.target.value)}
                      />
                    </div>
                    <div className={styles.formGroup}>
                      <label>Fecha Nacimiento</label>
                      <input
                        type="date"
                        className={styles.input}
                        value={formData.fecha_nacimiento}
                        onChange={(e) => handleField('fecha_nacimiento', e.target.value)}
                      />
                    </div>
                    <div className={styles.formGroup}>
                      <label>Fecha Ingreso *</label>
                      <input
                        type="date"
                        className={styles.input}
                        value={formData.fecha_ingreso}
                        onChange={(e) => handleField('fecha_ingreso', e.target.value)}
                      />
                    </div>
                    <div className={styles.formGroup}>
                      <label>Puesto</label>
                      <input
                        className={styles.input}
                        value={formData.puesto}
                        onChange={(e) => handleField('puesto', e.target.value)}
                      />
                    </div>
                    <div className={styles.formGroup}>
                      <label>Area</label>
                      <input
                        className={styles.input}
                        value={formData.area}
                        onChange={(e) => handleField('area', e.target.value)}
                      />
                    </div>
                    <div className={styles.formGroup}>
                      <label>Estado</label>
                      <select
                        className={styles.select}
                        value={formData.estado}
                        onChange={(e) => handleField('estado', e.target.value)}
                      >
                        <option value="activo">Activo</option>
                        <option value="licencia">Licencia</option>
                        <option value="baja">Baja</option>
                      </select>
                    </div>
                    <div className={styles.formGroup}>
                      <label>Teléfono</label>
                      <input
                        className={styles.input}
                        value={formData.telefono}
                        onChange={(e) => handleField('telefono', e.target.value)}
                      />
                    </div>
                    <div className={styles.formGroup}>
                      <label>Email Personal</label>
                      <input
                        type="email"
                        className={styles.input}
                        value={formData.email_personal}
                        onChange={(e) => handleField('email_personal', e.target.value)}
                      />
                    </div>
                    <div className={`${styles.formGroup} ${styles.formGroupFull}`}>
                      <label>Observaciones</label>
                      <textarea
                        className={styles.textarea}
                        value={formData.observaciones}
                        onChange={(e) => handleField('observaciones', e.target.value)}
                        rows={3}
                      />
                    </div>
                  </div>
                </>
              )}

              {/* ─── TAB: Dirección ─── */}
              {editando && modalTab === 'direccion' && (
                <div className={styles.direccionSection}>
                  {geoError && <div className={styles.formError}>{geoError}</div>}

                  <div className={styles.direccionGrid}>
                    <div className={styles.formGroup} style={{ flex: 3 }}>
                      <label>Calle</label>
                      <input
                        className={styles.input}
                        value={formData.calle}
                        onChange={(e) => handleField('calle', e.target.value)}
                        placeholder="Av. Corrientes"
                      />
                    </div>
                    <div className={styles.formGroup} style={{ flex: 1 }}>
                      <label>Número</label>
                      <input
                        className={styles.input}
                        value={formData.numero}
                        onChange={(e) => handleField('numero', e.target.value)}
                        placeholder="1234"
                      />
                    </div>
                    <div className={styles.formGroup} style={{ flex: 1 }}>
                      <label>Piso/Depto</label>
                      <input
                        className={styles.input}
                        value={formData.piso_depto}
                        onChange={(e) => handleField('piso_depto', e.target.value)}
                        placeholder="3° B"
                      />
                    </div>
                  </div>

                  <div className={styles.direccionGrid}>
                    <div className={styles.formGroup} style={{ flex: 2 }}>
                      <label>Entre calles</label>
                      <input
                        className={styles.input}
                        value={formData.entre_calles}
                        onChange={(e) => handleField('entre_calles', e.target.value)}
                        placeholder="Entre Av. Callao y Riobamba"
                      />
                    </div>
                    <div className={styles.formGroup} style={{ flex: 2 }}>
                      <label>Localidad</label>
                      <input
                        className={styles.input}
                        value={formData.localidad}
                        onChange={(e) => handleField('localidad', e.target.value)}
                        placeholder="CABA / Quilmes / etc."
                      />
                    </div>
                  </div>

                  <div className={styles.direccionGrid}>
                    <div className={styles.formGroup} style={{ flex: 2 }}>
                      <label>Provincia</label>
                      <input
                        className={styles.input}
                        value={formData.provincia}
                        onChange={(e) => handleField('provincia', e.target.value)}
                        placeholder="Buenos Aires"
                      />
                    </div>
                    <div className={styles.formGroup} style={{ flex: 1 }}>
                      <label>Código Postal</label>
                      <input
                        className={styles.input}
                        value={formData.codigo_postal}
                        onChange={(e) => handleField('codigo_postal', e.target.value)}
                        placeholder="C1043"
                      />
                    </div>
                  </div>

                  <div className={styles.geoActions}>
                    {puedeGestionar && (
                      <button
                        className={styles.btnGeocodificar}
                        onClick={handleGeocodificar}
                        disabled={geocoding || (!formData.calle && !formData.domicilio)}
                      >
                        <Navigation size={14} />
                        {geocoding ? 'Geocodificando...' : 'Geocodificar'}
                      </button>
                    )}

                    {formData.latitud && formData.longitud && (
                      <a
                        href={`https://www.google.com/maps?q=${formData.latitud},${formData.longitud}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.btnGoogleMaps}
                      >
                        <ExternalLink size={12} /> Abrir en Google Maps
                      </a>
                    )}
                  </div>

                  {puedeGestionar && (
                    <div className={styles.coordsRow}>
                      <div className={styles.formGroup}>
                        <label>Latitud</label>
                        <input
                          className={styles.input}
                          type="text"
                          value={formData.latitud || ''}
                          onChange={(e) => handleField('latitud', e.target.value || null)}
                          placeholder="-34.603722"
                        />
                      </div>
                      <div className={styles.formGroup}>
                        <label>Longitud</label>
                        <input
                          className={styles.input}
                          type="text"
                          value={formData.longitud || ''}
                          onChange={(e) => handleField('longitud', e.target.value || null)}
                          placeholder="-58.381592"
                        />
                      </div>
                      <p className={styles.coordsHint}>
                        <MapPin size={12} /> Podés pegar coordenadas de Google Maps si el geocodificador no las encuentra
                      </p>
                    </div>
                  )}

                  {/* Mapa */}
                  {formData.latitud && formData.longitud && (
                    <div className={styles.mapContainer}>
                      <MapContainer
                        center={[Number(formData.latitud), Number(formData.longitud)]}
                        zoom={15}
                        style={{ height: '250px', width: '100%', borderRadius: 'var(--radius-md)' }}
                        key={`${formData.latitud}-${formData.longitud}`}
                      >
                        <TileLayer
                          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
                          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                        />
                        <Marker position={[Number(formData.latitud), Number(formData.longitud)]}>
                          <Popup>
                            {editando.apellido}, {editando.nombre}<br />
                            {formData.calle} {formData.numero}
                          </Popup>
                        </Marker>
                      </MapContainer>
                    </div>
                  )}
                </div>
              )}

              {/* ─── TAB: Turnos ─── */}
              {editando && modalTab === 'turnos' && (
                <div className={styles.turnosSection}>
                  {turnoError && <div className={styles.formError}>{turnoError}</div>}

                  {loadingTurnos ? (
                    <div className={styles.turnosLoading}>Cargando turnos...</div>
                  ) : turnosEmpleado.length === 0 ? (
                    <div className={styles.turnosEmpty}>Sin turnos asignados</div>
                  ) : (
                    <div className={styles.turnosList}>
                      {turnosEmpleado.map((t) => (
                        <div key={t.id} className={styles.turnoItem}>
                          <div className={styles.turnoItemInfo}>
                            <span className={styles.turnoItemNombre}>{t.horario_nombre}</span>
                            <span className={styles.turnoItemHora}>
                              {formatTime(t.hora_entrada)} - {formatTime(t.hora_salida)}
                            </span>
                            {t.prioridad > 1 && (
                              <span className={styles.turnoItemPrioridad}>P{t.prioridad}</span>
                            )}
                          </div>
                          {puedeGestionar && (
                            <button
                              className={styles.btnDesasignar}
                              onClick={() => handleDesasignarTurno(t.id)}
                              title="Desasignar turno"
                            >
                              <UserMinus size={12} />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {puedeGestionar && (
                    <div className={styles.turnosAsignarRow}>
                      <select
                        className={styles.select}
                        value={nuevoTurnoId}
                        onChange={(e) => setNuevoTurnoId(e.target.value)}
                      >
                        <option value="">Asignar turno...</option>
                        {horariosDisponibles
                          .filter((h) => !turnosEmpleado.some((t) => t.horario_config_id === h.id))
                          .map((h) => (
                            <option key={h.id} value={h.id}>
                              {h.nombre} ({formatTime(h.hora_entrada)}-{formatTime(h.hora_salida)})
                            </option>
                          ))}
                      </select>
                      <select
                        className={styles.select}
                        value={nuevaTurnoPrioridad}
                        onChange={(e) => setNuevaTurnoPrioridad(e.target.value)}
                        style={{ width: '70px' }}
                        title="Prioridad"
                      >
                        <option value="1">P1</option>
                        <option value="2">P2</option>
                        <option value="3">P3</option>
                      </select>
                      <button
                        className={styles.btnAsignar}
                        onClick={handleAsignarTurno}
                        disabled={!nuevoTurnoId || asignandoTurno}
                      >
                        <UserPlus size={14} />
                        {asignandoTurno ? '...' : 'Asignar'}
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* ─── TAB: Documentos ─── */}
              {editando && modalTab === 'documentos' && (
                <div className={styles.docsSection}>
                  {docError && <div className={styles.formError}>{docError}</div>}

                  {/* Upload form */}
                  {puedeGestionar && (
                    <div className={styles.docUploadForm}>
                      <div className={styles.docUploadRow}>
                        <select
                          className={styles.select}
                          value={docForm.tipo_documento_id}
                          onChange={(e) => setDocForm({ ...docForm, tipo_documento_id: e.target.value })}
                        >
                          <option value="">Tipo de documento...</option>
                          {tiposDocumento.map((t) => (
                            <option key={t.id} value={t.id}>{t.nombre}</option>
                          ))}
                        </select>
                        <input
                          className={styles.input}
                          type="text"
                          placeholder="Descripción (opcional)"
                          value={docForm.descripcion}
                          onChange={(e) => setDocForm({ ...docForm, descripcion: e.target.value })}
                        />
                      </div>
                      <div className={styles.docUploadRow}>
                        <input
                          className={styles.input}
                          type="text"
                          placeholder="Nro. documento (opcional)"
                          value={docForm.numero_documento}
                          onChange={(e) => setDocForm({ ...docForm, numero_documento: e.target.value })}
                        />
                        <input
                          className={styles.input}
                          type="date"
                          title="Fecha vencimiento (opcional)"
                          value={docForm.fecha_vencimiento}
                          onChange={(e) => setDocForm({ ...docForm, fecha_vencimiento: e.target.value })}
                        />
                        <label className={styles.btnUpload}>
                          <Upload size={14} />
                          {uploadingDoc ? 'Subiendo...' : 'Subir archivo'}
                          <input
                            type="file"
                            accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx"
                            style={{ display: 'none' }}
                            disabled={!docForm.tipo_documento_id || uploadingDoc}
                            onChange={(e) => {
                              if (e.target.files?.[0]) handleSubirDocumento(e.target.files[0]);
                              e.target.value = '';
                            }}
                          />
                        </label>
                      </div>
                    </div>
                  )}

                  {/* Documents list */}
                  {loadingDocs ? (
                    <div className={styles.turnosLoading}>Cargando documentos...</div>
                  ) : documentos.length === 0 ? (
                    <div className={styles.turnosEmpty}>Sin documentos en el legajo</div>
                  ) : (
                    <div className={styles.docsList}>
                      {documentos.map((doc) => (
                        <div key={doc.id} className={styles.docItem}>
                          <div className={styles.docItemInfo}>
                            <FileText size={14} className={styles.docIcon} />
                            <div className={styles.docItemDetail}>
                              <span className={styles.docItemName}>{doc.nombre_archivo}</span>
                              <span className={styles.docItemMeta}>
                                {doc.tipo_documento_nombre}
                                {doc.numero_documento && ` — ${doc.numero_documento}`}
                                {' — '}{formatFileSize(doc.tamano_bytes)}
                                {doc.subido_por_nombre && ` — ${doc.subido_por_nombre}`}
                                {doc.created_at && ` — ${formatDateShort(doc.created_at.slice(0, 10))}`}
                              </span>
                              {doc.descripcion && (
                                <span className={styles.docItemDesc}>{doc.descripcion}</span>
                              )}
                              {doc.fecha_vencimiento && (
                                <span className={isVencido(doc.fecha_vencimiento) ? styles.docVencido : styles.docVencimiento}>
                                  {isVencido(doc.fecha_vencimiento) && <AlertCircle size={10} />}
                                  Vence: {formatDateShort(doc.fecha_vencimiento)}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className={styles.docItemActions}>
                            <button
                              className={styles.btnDownload}
                              onClick={() => handleDescargarDocumento(doc.id, doc.nombre_archivo)}
                              title="Descargar"
                            >
                              <Download size={12} />
                            </button>
                            {puedeGestionar && (
                              <button
                                className={styles.btnDesasignar}
                                onClick={() => handleEliminarDocumento(doc.id)}
                                title="Eliminar"
                              >
                                <Trash2 size={12} />
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* ─── TAB: Baja ─── */}
              {editando && modalTab === 'baja' && (
                <div className={styles.bajaSection}>
                  {formError && <div className={styles.formError}>{formError}</div>}

                  <div className={styles.bajaGrid}>
                    <div className={styles.formGroup}>
                      <label>Estado</label>
                      <select
                        className={styles.select}
                        value={formData.estado}
                        onChange={(e) => handleField('estado', e.target.value)}
                        disabled={!puedeGestionar}
                      >
                        <option value="activo">Activo</option>
                        <option value="licencia">Licencia</option>
                        <option value="baja">Baja</option>
                      </select>
                    </div>

                    <div className={styles.formGroup}>
                      <label>Fecha de Egreso</label>
                      <input
                        type="date"
                        className={styles.input}
                        value={formData.fecha_egreso || ''}
                        onChange={(e) => handleField('fecha_egreso', e.target.value || null)}
                        disabled={!puedeGestionar}
                      />
                    </div>

                    <div className={styles.formGroup}>
                      <label>Motivo de Baja</label>
                      <select
                        className={styles.select}
                        value={formData.motivo_baja_id || ''}
                        onChange={(e) => handleField('motivo_baja_id', e.target.value ? parseInt(e.target.value, 10) : null)}
                        disabled={!puedeGestionar}
                      >
                        <option value="">Sin motivo</option>
                        {motivosBaja.map((m) => (
                          <option key={m.id} value={m.id}>{m.nombre}</option>
                        ))}
                      </select>
                    </div>

                    <div className={`${styles.formGroup} ${styles.formGroupFull}`}>
                      <label>Detalle / Observaciones de la Baja</label>
                      <textarea
                        className={styles.textarea}
                        value={formData.detalle_baja || ''}
                        onChange={(e) => handleField('detalle_baja', e.target.value)}
                        rows={4}
                        disabled={!puedeGestionar}
                        placeholder="Detalles adicionales sobre la baja, acuerdos, etc."
                      />
                    </div>
                  </div>

                  {formData.estado === 'baja' && (
                    <p className={styles.bajaNote}>
                      <AlertCircle size={14} />
                      Recordá adjuntar la documentación de la baja en el tab Documentos
                      (telegrama, acta, acuerdo, etc.)
                    </p>
                  )}
                </div>
              )}

            </div>

            <div className="modal-footer-tesla">
              <button
                className={styles.btnCancel}
                onClick={() => setModalOpen(false)}
              >
                {editando && (modalTab === 'turnos' || modalTab === 'documentos') ? 'Cerrar' : 'Cancelar'}
              </button>
              {(modalTab === 'datos' || modalTab === 'direccion' || modalTab === 'baja' || !editando) && (
                <button
                  className={styles.btnSave}
                  onClick={handleGuardar}
                  disabled={saving}
                >
                  {saving ? 'Guardando...' : 'Guardar'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Modal generar documento PDF */}
      <DocumentGeneratorModal
        isOpen={docGenOpen}
        onClose={() => { setDocGenOpen(false); setDocGenEmpleado(null); }}
        contexto="rrhh"
        entityData={docGenEmpleado}
      />
    </div>
  );
}
