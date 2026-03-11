import { useState, useEffect, useCallback, useRef } from 'react';
import { useDebounce } from '../hooks/useDebounce';
import {
  Upload, RefreshCw, MapPin, CheckCircle, AlertCircle, Settings,
  ScanBarcode, Plus, Trash2, ToggleLeft, ToggleRight, X, Download,
  Truck, Search, Printer, Pencil, Bike, Building, Calendar,
  Table, Map, CloudRain, Flag,
} from 'lucide-react';
import MapaEnviosFlex from './MapaEnviosFlex';
import CalendarioEnvios from './CalendarioEnvios';
import api from '../services/api';
import { toLocalDateString } from '../utils/dateUtils';
import { printZpl } from '../services/zebraPrint';
import { usePermisos } from '../contexts/PermisosContext';
import { useToast } from '../hooks/useToast';
import Toast from './Toast';
import styles from './TabEnviosFlex.module.css';

const CORDONES = ['CABA', 'Cordón 1', 'Cordón 2', 'Cordón 3'];

const EXPORT_COLUMNS = {
  shipping_id: 'Shipping ID',
  fecha_envio: 'Fecha Envío',
  destinatario: 'Destinatario',
  direccion: 'Dirección',
  cp: 'CP',
  localidad: 'Localidad',
  cordon: 'Cordón',
  logistica: 'Logística',
  costo_envio: 'Costo Envío',
  estado_ml: 'Estado ML',
  estado_erp: 'Estado ERP',
  pistoleado: 'Pistoleado',
  caja: 'Caja',
  turbo: 'Turbo',
  lluvia: 'Lluvia',
  flag_envio: 'Flag',
  flag_envio_motivo: 'Motivo Flag',
};

const FLAG_LABELS = {
  mal_pasado: 'Mal pasado',
  envio_cancelado: 'Cancelado',
  duplicado: 'Duplicado',
  otro: 'Otro',
};

const ML_STATUS_LABELS = {
  ready_to_ship: 'Listo para enviar',
  shipped: 'Enviado',
  delivered: 'Entregado',
  cancelled: 'Cancelado',
  not_delivered: 'No entregado',
};

const todayStr = () => toLocalDateString();

// ── Helper: badge classes ───────────────────────────────────────

const getCordonBadgeClass = (cordon) => {
  if (!cordon) return styles.cordonSinAsignar;
  switch (cordon) {
    case 'CABA': return styles.cordonCaba;
    case 'Cordón 1': return styles.cordonUno;
    case 'Cordón 2': return styles.cordonDos;
    case 'Cordón 3': return styles.cordonTres;
    default: return styles.cordonSinAsignar;
  }
};

const getMlStatusClass = (status) => {
  switch (status) {
    case 'ready_to_ship': return styles.mlReadyToShip;
    case 'shipped': return styles.mlShipped;
    case 'delivered': return styles.mlDelivered;
    case 'cancelled': return styles.mlCancelled;
    case 'not_delivered': return styles.mlNotDelivered;
    default: return styles.mlDefault;
  }
};

// ────────────────────────────────────────────────────────────────

export default function TabEnviosFlex({ operador = null }) {
  const { tienePermiso } = usePermisos();

  // Permisos envíos flex
  const puedeSubir = tienePermiso('envios_flex.subir_etiquetas');
  const puedeAsignarLogistica = tienePermiso('envios_flex.asignar_logistica');
  const puedeCambiarFecha = tienePermiso('envios_flex.cambiar_fecha');
  const puedeEliminar = tienePermiso('envios_flex.eliminar');
  const puedeExportar = tienePermiso('envios_flex.exportar');
  const puedeGestionarLogisticas = tienePermiso('envios_flex.gestionar_logisticas');
  const puedeVerCostos = tienePermiso('envios_flex.config');
  const puedeAsignarTurbo = tienePermiso('envios_flex.asignar_turbo');
  const puedeAsignarLluvia = tienePermiso('envios_flex.asignar_lluvia');
  const puedeFlag = tienePermiso('envios_flex.config');

  // Data
  const [etiquetas, setEtiquetas] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [logisticas, setLogisticas] = useState([]);
  const [transportes, setTransportes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Smart polling ref (count + lastUpdated del último check)
  const pollingRef = useRef({ count: null, lastUpdated: null });

  // Filtros
  const [fechaDesde, setFechaDesde] = useState(todayStr());
  const [fechaHasta, setFechaHasta] = useState(todayStr());
  const [filtroRapidoActivo, setFiltroRapidoActivo] = useState('hoy');
  const [mostrarDropdownFecha, setMostrarDropdownFecha] = useState(false);
  const [fechaTemporal, setFechaTemporal] = useState({ desde: todayStr(), hasta: todayStr() });
  const [filtroCordon, setFiltroCordon] = useState('');
  const [filtroLogistica, setFiltroLogistica] = useState('');
  const [filtroMlStatus, setFiltroMlStatus] = useState('');
  const [filtroSsosId, setFiltroSsosId] = useState('');
  const [sinLogistica, setSinLogistica] = useState(false);
  const [sinCordon, setSinCordon] = useState(false);
  const [filtroPistoleado, setFiltroPistoleado] = useState('');
  const [soloOutlet, setSoloOutlet] = useState(false);
  const [soloTurbo, setSoloTurbo] = useState(false);
  const [soloFlag, setSoloFlag] = useState(false);
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 400);

  // Extrae shipping_id si el input es JSON de etiqueta (pistola/QR)
  const handleSearchChange = (value) => {
    const trimmed = value.trim();
    if (trimmed.startsWith('{')) {
      try {
        const parsed = JSON.parse(trimmed);
        const shippingId = parsed.id || parsed.shipping_id;
        if (shippingId) {
          setSearch(String(shippingId));
          return;
        }
      } catch {
        // No es JSON válido (todavía se está escribiendo), dejar pasar
      }
    }
    setSearch(value);
  };

  // Filtros rápidos de fecha (copiados del Dashboard)
  const aplicarFiltroRapido = (filtro) => {
    const hoy = new Date();
    const fmt = (d) => toLocalDateString(d);
    let desde;
    let hasta = hoy;

    switch (filtro) {
      case 'hoy':
        desde = new Date(hoy);
        break;
      case 'ayer': {
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 1);
        hasta = new Date(desde);
        break;
      }
      case '3d':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 2);
        break;
      case '7d':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 6);
        break;
      default:
        return;
    }

    setFiltroRapidoActivo(filtro);
    setMostrarDropdownFecha(false);
    setFechaDesde(fmt(desde));
    setFechaHasta(fmt(hasta));
  };

  const aplicarFechaPersonalizada = () => {
    setFiltroRapidoActivo('custom');
    setMostrarDropdownFecha(false);
    setFechaDesde(fechaTemporal.desde);
    setFechaHasta(fechaTemporal.hasta);
  };

  // Scanner
  const [scanInput, setScanInput] = useState('');
  const [scanFeedback, setScanFeedback] = useState(null); // { type, message }
  const scanRef = useRef(null);

  // Upload
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const fileInputRef = useRef(null);

  // Modal logísticas
  const [showLogisticasModal, setShowLogisticasModal] = useState(false);
  const [newLogNombre, setNewLogNombre] = useState('');
  const [newLogColor, setNewLogColor] = useState('#3b82f6');
  const [editingLog, setEditingLog] = useState(null); // { id, nombre, color }

  // Modal transportes
  const [showTransportesModal, setShowTransportesModal] = useState(false);
  const [newTranspNombre, setNewTranspNombre] = useState('');
  const [newTranspCuit, setNewTranspCuit] = useState('');
  const [editingTransp, setEditingTransp] = useState(null); // { id, nombre, cuit, direccion, cp, localidad, telefono, horario, color }
  const [newTranspDireccion, setNewTranspDireccion] = useState('');
  const [newTranspCp, setNewTranspCp] = useState('');
  const [newTranspLocalidad, setNewTranspLocalidad] = useState('');
  const [newTranspTelefono, setNewTranspTelefono] = useState('');
  const [newTranspHorario, setNewTranspHorario] = useState('');
  const [newTranspColor, setNewTranspColor] = useState('#8b5cf6');

  // Inline editing
  const [actualizando, setActualizando] = useState(new Set());

  // Costo override inline editing
  const [editandoCosto, setEditandoCosto] = useState(null); // shipping_id que se está editando
  const [costoInputValue, setCostoInputValue] = useState('');
  const costoInputRef = useRef(null);

  // Scroll horizontal sincronizado (scrollbar duplicada arriba)
  const tableContainerRef = useRef(null);
  const topScrollRef = useRef(null);
  const tableRef = useRef(null);
  const [tableWidth, setTableWidth] = useState(0);

  // Vista: tabla, mapa o calendario
  const [vistaActiva, setVistaActiva] = useState('tabla'); // 'tabla' | 'mapa' | 'calendario'

  // Selección múltiple
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [lastSelected, setLastSelected] = useState(null);
  const [bulkLogisticaId, setBulkLogisticaId] = useState('');
  const [bulkTransporteId, setBulkTransporteId] = useState('');
  const [bulkActualizando, setBulkActualizando] = useState(false);

  // Error inline (reemplaza alert())
  const { toast, showToast: showErrorToast, hideToast } = useToast(5000);

  // Export — array ordenado: el orden de tildado = orden de columnas en el XLSX
  const [showExportModal, setShowExportModal] = useState(false);
  const [exportColumns, setExportColumns] = useState([...Object.keys(EXPORT_COLUMNS)]);
  const [exporting, setExporting] = useState(false);

  // Export manuales — modal con tabla editable
  const [showExportManualesModal, setShowExportManualesModal] = useState(false);
  const [exportManualesData, setExportManualesData] = useState([]);
  const [exportingManuales, setExportingManuales] = useState(false);

  // Modal envío manual
  const [showManualEnvioModal, setShowManualEnvioModal] = useState(false);
  const [manualEnvio, setManualEnvio] = useState({
    receiver_name: '',
    street_name: '',
    street_number: '',
    zip_code: '',
    city_name: '',
    phone: '',
    status: 'ready_to_ship',
    cust_id: '',
    bra_id: '',
    soh_id: '',
    logistica_id: '',
    transporte_id: '',
    comment: '',
    fecha_envio: todayStr(),
  });
  const [editandoManualId, setEditandoManualId] = useState(null);
  const [manualEnvioLoading, setManualEnvioLoading] = useState(false);
  const [manualEnvioCordon, setManualEnvioCordon] = useState(null);
  const [sucursales, setSucursales] = useState([]);
  const [pedidoLoading, setPedidoLoading] = useState(false);
  const [pedidoError, setPedidoError] = useState(null);
  const [custLoading, setCustLoading] = useState(false);
  const [custError, setCustError] = useState(null);

  // Modal impresión etiqueta manual
  const [showPrintManualModal, setShowPrintManualModal] = useState(false);
  const [printManualEnvio, setPrintManualEnvio] = useState(null); // etiqueta seleccionada
  const [printNumBultos, setPrintNumBultos] = useState(1);
  const [printTipoDomicilio, setPrintTipoDomicilio] = useState('Particular');
  const [printTipoEnvio, setPrintTipoEnvio] = useState('');
  const [printManualLoading, setPrintManualLoading] = useState(false);

  // Flag modal
  const [showFlagModal, setShowFlagModal] = useState(false);
  const [flagType, setFlagType] = useState('mal_pasado');
  const [flagMotivo, setFlagMotivo] = useState('');
  const [flagLoading, setFlagLoading] = useState(false);

  // Filtrar flaggeadas client-side (los datos ya vienen con flag_envio)
  const etiquetasFiltradas = soloFlag
    ? etiquetas.filter(e => e.flag_envio)
    : etiquetas;

  // Confirm modal (reemplaza confirm())
  const [confirmDialog, setConfirmDialog] = useState(null); // { title, message, onConfirm, challengeWord?, showComment? }
  const [confirmInput, setConfirmInput] = useState('');
  const [confirmComment, setConfirmComment] = useState('');

  // ── Error feedback (reemplaza alert()) ──────────────────────

  const mostrarError = (err) => {
    const msg = err?.response?.data?.detail || err?.message || String(err);
    showErrorToast(msg, 'error');
  };

  // ── Confirm dialog helpers ─────────────────────────────────

  const pedirConfirmacion = (title, message, { challengeWord = null, showComment = false } = {}) =>
    new Promise((resolve) => {
      setConfirmInput('');
      setConfirmComment('');
      setConfirmDialog({
        title,
        message,
        challengeWord,
        showComment,
        onConfirm: () => {
          const comment = confirmComment.trim() || null;
          setConfirmDialog(null);
          setConfirmInput('');
          setConfirmComment('');
          resolve({ confirmed: true, comment });
        },
        onCancel: () => {
          setConfirmDialog(null);
          setConfirmInput('');
          setConfirmComment('');
          resolve({ confirmed: false, comment: null });
        },
      });
    });

  // ── Data loading ─────────────────────────────────────────────

  const cargarLogisticas = useCallback(async () => {
    try {
      const { data } = await api.get('/logisticas?incluir_inactivas=true');
      setLogisticas(data);
    } catch (err) {
      console.error('Error cargando logísticas:', err);
    }
  }, []);

  const cargarTransportes = useCallback(async () => {
    try {
      const { data } = await api.get('/transportes?incluir_inactivas=true');
      setTransportes(data);
    } catch (err) {
      console.error('Error cargando transportes:', err);
    }
  }, []);

  // Helper: construye params de filtros activos (reutilizado en stats refresh)
  const buildFilterParams = useCallback(() => {
    const p = new URLSearchParams();
    if (fechaDesde) p.append('fecha_desde', fechaDesde);
    if (fechaHasta) p.append('fecha_hasta', fechaHasta);
    if (filtroCordon) p.append('cordon', filtroCordon);
    if (filtroLogistica) p.append('logistica_id', filtroLogistica);
    if (sinLogistica) p.append('sin_logistica', 'true');
    if (sinCordon) p.append('sin_cordon', 'true');
    if (soloOutlet) p.append('solo_outlet', 'true');
    if (soloTurbo) p.append('solo_turbo', 'true');
    if (filtroMlStatus) p.append('mlstatus', filtroMlStatus);
    if (filtroSsosId) p.append('ssos_id', filtroSsosId);
    if (filtroPistoleado) p.append('pistoleado', filtroPistoleado);
    if (debouncedSearch) p.append('search', debouncedSearch);
    return p;
  }, [fechaDesde, fechaHasta, filtroCordon, filtroLogistica, sinLogistica, sinCordon, soloOutlet, soloTurbo, filtroMlStatus, filtroSsosId, filtroPistoleado, debouncedSearch]);

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = buildFilterParams();

      // Cargar listado y estadísticas en paralelo, pero independientes:
      // si las estadísticas fallan (ej: timeout 524) el listado sigue funcionando.
      const etiqPromise = api.get(`/etiquetas-envio?${params}`);
      const statsPromise = api.get(`/etiquetas-envio/estadisticas?${params}`);

      const etiqResponse = await etiqPromise;
      setEtiquetas(etiqResponse.data);

      // Estadísticas best-effort: si fallan, mostramos la tabla igual
      try {
        const statsResponse = await statsPromise;
        setEstadisticas(statsResponse.data);
      } catch {
        // Silencioso — las estadísticas se pueden recuperar con el polling
      }

      // Resetear polling ref para que el próximo poll no triggerea reload
      // (se recalcula en el siguiente tick de polling)
      pollingRef.current = { count: null, lastUpdated: null };
    } catch (err) {
      setError('Error cargando etiquetas');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [buildFilterParams]);

  useEffect(() => {
    cargarLogisticas();
    cargarTransportes();
  }, [cargarLogisticas, cargarTransportes]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  // ── Smart Polling: detectar cambios y recargar silenciosamente ──

  useEffect(() => {
    const POLL_INTERVAL = 10_000; // 10 segundos

    const checkForUpdates = async () => {
      // No pollear si hay modal abierta, bulk action, o tab no visible
      if (
        document.hidden ||
        showManualEnvioModal ||
        showLogisticasModal ||
        showTransportesModal ||
        showExportModal ||
        showExportManualesModal ||
        showPrintManualModal ||
        showFlagModal ||
        bulkActualizando
      ) {
        return;
      }

      try {
        // Construir solo los filtros livianos (los que el backend acepta sin JOINs)
        const p = new URLSearchParams();
        if (fechaDesde) p.append('fecha_desde', fechaDesde);
        if (fechaHasta) p.append('fecha_hasta', fechaHasta);
        if (filtroLogistica) p.append('logistica_id', filtroLogistica);
        if (sinLogistica) p.append('sin_logistica', 'true');
        if (soloOutlet) p.append('solo_outlet', 'true');
        if (soloTurbo) p.append('solo_turbo', 'true');
        if (filtroPistoleado) p.append('pistoleado', filtroPistoleado);

        const { data } = await api.get(`/etiquetas-envio/check-updates?${p}`);
        const prev = pollingRef.current;

        // Primera vez: guardar referencia y, si hay error previo, forzar reload
        if (prev.count === null) {
          pollingRef.current = { count: data.count, lastUpdated: data.last_updated };
          // Si hay error previo (ej: carga inicial falló por timeout),
          // forzar un reload silencioso para recuperar la UI
          if (!error) return;
        }

        // Detectar cambio: count distinto O timestamp distinto
        if (data.count !== prev.count || data.last_updated !== prev.lastUpdated) {
          pollingRef.current = { count: data.count, lastUpdated: data.last_updated };
          // Recargar silenciosamente (sin setLoading)
          try {
            const params = buildFilterParams();
            const etiqResponse = await api.get(`/etiquetas-envio?${params}`);
            setEtiquetas(etiqResponse.data);
            setError(null); // Limpiar error previo si el listado ahora responde

            // Estadísticas best-effort
            try {
              const statsResponse = await api.get(`/etiquetas-envio/estadisticas?${params}`);
              setEstadisticas(statsResponse.data);
            } catch {
              // Silencioso — las estadísticas se recuperan en el próximo poll
            }
          } catch {
            // Silencioso — no mostrar error por polling
          }
        }
      } catch {
        // Silencioso — el polling no debería molestar al usuario con errores
      }
    };

    const intervalId = setInterval(checkForUpdates, POLL_INTERVAL);

    // Resetear referencia cuando cambian los filtros
    pollingRef.current = { count: null, lastUpdated: null };

    return () => clearInterval(intervalId);
  }, [
    fechaDesde, fechaHasta, filtroLogistica, sinLogistica, soloOutlet,
    soloTurbo, filtroPistoleado, showManualEnvioModal, showLogisticasModal,
    showTransportesModal, showExportModal, showExportManualesModal,
    showPrintManualModal, showFlagModal,
    bulkActualizando, buildFilterParams, error,
  ]);

  // ── Scroll horizontal sincronizado ──────────────────────────

  useEffect(() => {
    const container = tableContainerRef.current;
    const topScroll = topScrollRef.current;
    const table = tableRef.current;
    if (!container || !topScroll || !table) return;

    // Medir ancho real de la tabla
    const updateWidth = () => {
      setTableWidth(table.scrollWidth);
    };
    updateWidth();

    const observer = new ResizeObserver(updateWidth);
    observer.observe(table);

    // Sincronizar scroll entre ambas barras
    let syncing = false;
    const syncFromTop = () => {
      if (syncing) return;
      syncing = true;
      container.scrollLeft = topScroll.scrollLeft;
      syncing = false;
    };
    const syncFromBottom = () => {
      if (syncing) return;
      syncing = true;
      topScroll.scrollLeft = container.scrollLeft;
      syncing = false;
    };

    topScroll.addEventListener('scroll', syncFromTop);
    container.addEventListener('scroll', syncFromBottom);

    // Flechas del teclado para scroll horizontal
    const handleKeyDown = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;
      const step = 200;
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        container.scrollLeft += step;
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        container.scrollLeft -= step;
      }
    };
    container.addEventListener('keydown', handleKeyDown);

    return () => {
      observer.disconnect();
      topScroll.removeEventListener('scroll', syncFromTop);
      container.removeEventListener('scroll', syncFromBottom);
      container.removeEventListener('keydown', handleKeyDown);
    };
  }, [etiquetas, loading]);

  // ── Scanner ──────────────────────────────────────────────────

  const handleScan = async () => {
    const raw = scanInput.trim();
    if (!raw) return;

    setScanInput('');
    setScanFeedback(null);

    try {
      const { data } = await api.post('/etiquetas-envio/manual', {
        json_data: raw,
      });

      if (data.duplicada) {
        setScanFeedback({ type: 'duplicate', message: data.mensaje });
      } else {
        setScanFeedback({ type: 'success', message: data.mensaje });
        // Refresh data
        cargarDatos();
      }
    } catch (err) {
      setScanFeedback({
        type: 'error',
        message: err.response?.data?.detail || 'Error procesando QR',
      });
    }

    // Auto-clear after 3s
    setTimeout(() => setScanFeedback(null), 3000);

    // Refocus
    scanRef.current?.focus();
  };

  const handleScanKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleScan();
    }
  };

  // ── File Upload ──────────────────────────────────────────────

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadResult(null);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const { data } = await api.post('/etiquetas-envio/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      setUploadResult(data);
      cargarDatos();
    } catch (err) {
      setUploadResult({
        errores: 1,
        detalle_errores: [err.response?.data?.detail || err.message],
      });
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  // ── Inline edits ─────────────────────────────────────────────

  const cambiarLogistica = async (shippingId, logisticaId) => {
    setActualizando(prev => new Set([...prev, shippingId]));
    try {
      const val = logisticaId === '' ? null : parseInt(logisticaId, 10);
      await api.put(`/etiquetas-envio/${shippingId}/logistica`, {
        logistica_id: val,
      });

      // Update locally
      const log = logisticas.find(l => l.id === val);
      setEtiquetas(prev =>
        prev.map(e =>
          e.shipping_id === shippingId
            ? {
                ...e,
                logistica_id: val,
                logistica_nombre: log?.nombre || null,
                logistica_color: log?.color || null,
              }
            : e
        )
      );
    } catch (err) {
      mostrarError(err);
    } finally {
      setActualizando(prev => {
        const next = new Set(prev);
        next.delete(shippingId);
        return next;
      });
    }
  };

  const cambiarFecha = async (shippingId, nuevaFecha) => {
    setActualizando(prev => new Set([...prev, shippingId]));
    try {
      await api.put(`/etiquetas-envio/${shippingId}/fecha`, {
        fecha_envio: nuevaFecha,
      });

      setEtiquetas(prev =>
        prev.map(e =>
          e.shipping_id === shippingId
            ? { ...e, fecha_envio: nuevaFecha }
            : e
        )
      );
    } catch (err) {
      mostrarError(err);
    } finally {
      setActualizando(prev => {
        const next = new Set(prev);
        next.delete(shippingId);
        return next;
      });
    }
  };

  const cambiarEstadoManual = async (shippingId, nuevoEstado) => {
    const opId = operador?.operadorActivo?.id;
    if (!opId) {
      mostrarError({ message: 'No hay operador activo' });
      return;
    }
    setActualizando(prev => new Set([...prev, shippingId]));
    try {
      await api.put(
        `/etiquetas-envio/${shippingId}/estado-ml?status=${nuevoEstado}&operador_id=${opId}`,
      );
      setEtiquetas(prev =>
        prev.map(e =>
          e.shipping_id === shippingId
            ? { ...e, mlstatus: nuevoEstado }
            : e
        )
      );
    } catch (err) {
      mostrarError(err);
    } finally {
      setActualizando(prev => {
        const next = new Set(prev);
        next.delete(shippingId);
        return next;
      });
    }
  };

  // ── Costo override ─────────────────────────────────────────

  const iniciarEdicionCosto = (shippingId, costoActual) => {
    setEditandoCosto(shippingId);
    setCostoInputValue(costoActual != null ? String(costoActual) : '');
    // Focus en el siguiente render
    setTimeout(() => costoInputRef.current?.focus(), 0);
  };

  const cancelarEdicionCosto = () => {
    setEditandoCosto(null);
    setCostoInputValue('');
  };

  const guardarCostoOverride = async (shippingId) => {
    const valor = costoInputValue.trim();
    // Si está vacío → quitar override (null)
    const costo = valor === '' ? null : parseFloat(valor);

    if (costo !== null && (isNaN(costo) || costo < 0)) {
      mostrarError({ message: 'Ingresá un costo válido (número >= 0, o vacío para quitar)' });
      return;
    }

    setActualizando(prev => new Set([...prev, shippingId]));
    setEditandoCosto(null);

    try {
      await api.put(`/etiquetas-envio/${shippingId}/costo`, {
        costo,
        operador_id: operador?.operadorActivo?.id,
      });

      // Actualizar localmente
      setEtiquetas(prev =>
        prev.map(e =>
          e.shipping_id === shippingId
            ? { ...e, costo_override: costo, costo_envio: costo ?? e.costo_envio }
            : e
        )
      );

      // Refrescar estadísticas para que el total refleje el cambio
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${buildFilterParams()}`);
      setEstadisticas(statsData);
    } catch (err) {
      mostrarError(err);
    } finally {
      setActualizando(prev => {
        const next = new Set(prev);
        next.delete(shippingId);
        return next;
      });
    }
  };

  const handleCostoKeyDown = (e, shippingId) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      guardarCostoOverride(shippingId);
    } else if (e.key === 'Escape') {
      cancelarEdicionCosto();
    }
  };

  // ── Impresión de etiquetas ZPL ─────────────────────────────

  const [imprimiendo, setImprimiendo] = useState(null); // shipping_id en progreso

  const imprimirEtiqueta = async (shippingId) => {
    setImprimiendo(shippingId);
    try {
      const { data } = await api.get(`/etiquetas-envio/${shippingId}/etiqueta`);

      if (!data.ok) {
        mostrarError(data.error || 'No se pudo obtener la etiqueta');
        return;
      }

      const resultado = await printZpl(data.zpl, shippingId);

      if (resultado.method === 'zebra') {
        // Impreso directamente en la Zebra
        setScanFeedback({ type: 'success', text: `Etiqueta ${shippingId} enviada a la impresora` });
        setTimeout(() => setScanFeedback(null), 4000);
      } else {
        // Descargado como .zpl
        setScanFeedback({ type: 'duplicate', text: `Etiqueta ${shippingId} descargada (Zebra no disponible)` });
        setTimeout(() => setScanFeedback(null), 4000);
      }
    } catch (err) {
      mostrarError(err);
    } finally {
      setImprimiendo(null);
    }
  };

  // ── Logísticas CRUD ──────────────────────────────────────────

  const crearLogistica = async (e) => {
    e.preventDefault();
    if (!newLogNombre.trim()) return;

    try {
      await api.post('/logisticas', {
        nombre: newLogNombre.trim(),
        color: newLogColor,
      });
      setNewLogNombre('');
      setNewLogColor('#3b82f6');
      cargarLogisticas();
    } catch (err) {
      mostrarError(err);
    }
  };

  const toggleLogistica = async (logistica) => {
    try {
      await api.put(`/logisticas/${logistica.id}`, {
        activa: !logistica.activa,
      });
      cargarLogisticas();
    } catch (err) {
      mostrarError(err);
    }
  };

  const eliminarLogistica = async (logistica) => {
    const { confirmed } = await pedirConfirmacion(
      'Desactivar logística',
      `¿Desactivar logística "${logistica.nombre}"?`,
    );
    if (!confirmed) return;
    try {
      await api.delete(`/logisticas/${logistica.id}`);
      cargarLogisticas();
    } catch (err) {
      mostrarError(err);
    }
  };

  const guardarEdicionLogistica = async () => {
    if (!editingLog || !editingLog.nombre.trim()) return;
    try {
      await api.put(`/logisticas/${editingLog.id}`, {
        nombre: editingLog.nombre.trim(),
        color: editingLog.color || '',
      });
      setEditingLog(null);
      cargarLogisticas();
    } catch (err) {
      mostrarError(err);
    }
  };

  // ── Transportes CRUD ────────────────────────────────────────

  const crearTransporte = async (e) => {
    e.preventDefault();
    if (!newTranspNombre.trim()) return;

    try {
      await api.post('/transportes', {
        nombre: newTranspNombre.trim(),
        cuit: newTranspCuit.trim() || null,
        direccion: newTranspDireccion.trim() || null,
        cp: newTranspCp.trim() || null,
        localidad: newTranspLocalidad.trim() || null,
        telefono: newTranspTelefono.trim() || null,
        horario: newTranspHorario.trim() || null,
        color: newTranspColor,
      });
      setNewTranspNombre('');
      setNewTranspCuit('');
      setNewTranspDireccion('');
      setNewTranspCp('');
      setNewTranspLocalidad('');
      setNewTranspTelefono('');
      setNewTranspHorario('');
      setNewTranspColor('#8b5cf6');
      cargarTransportes();
    } catch (err) {
      mostrarError(err);
    }
  };

  const toggleTransporte = async (transporte) => {
    try {
      await api.put(`/transportes/${transporte.id}`, {
        activa: !transporte.activa,
      });
      cargarTransportes();
    } catch (err) {
      mostrarError(err);
    }
  };

  const eliminarTransporte = async (transporte) => {
    const { confirmed } = await pedirConfirmacion(
      'Desactivar transporte',
      `¿Desactivar transporte "${transporte.nombre}"?`,
    );
    if (!confirmed) return;
    try {
      await api.delete(`/transportes/${transporte.id}`);
      cargarTransportes();
    } catch (err) {
      mostrarError(err);
    }
  };

  const guardarEdicionTransporte = async () => {
    if (!editingTransp || !editingTransp.nombre.trim()) return;
    try {
      await api.put(`/transportes/${editingTransp.id}`, {
        nombre: editingTransp.nombre.trim(),
        cuit: editingTransp.cuit?.trim() || null,
        direccion: editingTransp.direccion?.trim() || null,
        cp: editingTransp.cp?.trim() || null,
        localidad: editingTransp.localidad?.trim() || null,
        telefono: editingTransp.telefono?.trim() || null,
        horario: editingTransp.horario?.trim() || null,
        color: editingTransp.color || '',
      });
      setEditingTransp(null);
      cargarTransportes();
    } catch (err) {
      mostrarError(err);
    }
  };

  const cambiarTransporte = async (shippingId, transporteId) => {
    setActualizando(prev => new Set([...prev, shippingId]));
    try {
      const val = transporteId === '' ? null : parseInt(transporteId, 10);
      // Usamos el endpoint de edición manual para actualizar transporte_id
      // Solo funciona para envíos manuales
      const etiqueta = etiquetas.find(et => et.shipping_id === shippingId);
      if (etiqueta?.es_manual) {
        await api.put(`/etiquetas-envio/manual-envio/${shippingId}`, {
          fecha_envio: etiqueta.fecha_envio,
          receiver_name: etiqueta.mlreceiver_name || 'Sin nombre',
          street_name: etiqueta.mlstreet_name || 'S/N',
          street_number: etiqueta.mlstreet_number || 'S/N',
          zip_code: etiqueta.mlzip_code || '0000',
          city_name: etiqueta.mlcity_name || '',
          status: etiqueta.mlstatus || 'ready_to_ship',
          cust_id: etiqueta.manual_cust_id || null,
          bra_id: etiqueta.manual_bra_id || null,
          soh_id: etiqueta.manual_soh_id || null,
          logistica_id: etiqueta.logistica_id || null,
          transporte_id: val,
          comment: etiqueta.manual_comment || null,
          operador_id: operador?.operadorActivo?.id,
        });
      }

      // Update locally
      const tr = transportes.find(t => t.id === val);
      setEtiquetas(prev =>
        prev.map(et =>
          et.shipping_id === shippingId
            ? {
                ...et,
                transporte_id: val,
                transporte_nombre: tr?.nombre || null,
                transporte_color: tr?.color || null,
                transporte_direccion: tr?.direccion || null,
                transporte_cp: tr?.cp || null,
                transporte_localidad: tr?.localidad || null,
                transporte_telefono: tr?.telefono || null,
                transporte_horario: tr?.horario || null,
              }
            : et
        )
      );
    } catch (err) {
      mostrarError(err);
    } finally {
      setActualizando(prev => {
        const next = new Set(prev);
        next.delete(shippingId);
        return next;
      });
    }
  };

  // ── Selección múltiple ─────────────────────────────────────

  const toggleSeleccion = (shippingId, shiftKey) => {
    const nueva = new Set(selectedIds);

    if (shiftKey && lastSelected !== null) {
      // Shift+click: seleccionar rango
      const ids = etiquetasFiltradas.map(e => e.shipping_id);
      const idxActual = ids.indexOf(shippingId);
      const idxUltimo = ids.indexOf(lastSelected);
      const inicio = Math.min(idxActual, idxUltimo);
      const fin = Math.max(idxActual, idxUltimo);

      for (let i = inicio; i <= fin; i++) {
        nueva.add(ids[i]);
      }
    } else {
      if (nueva.has(shippingId)) {
        nueva.delete(shippingId);
      } else {
        nueva.add(shippingId);
      }
    }

    setSelectedIds(nueva);
    setLastSelected(shippingId);
  };

  const seleccionarTodos = () => {
    if (selectedIds.size === etiquetasFiltradas.length && etiquetasFiltradas.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(etiquetasFiltradas.map(e => e.shipping_id)));
    }
  };

  const limpiarSeleccion = () => {
    setSelectedIds(new Set());
    setLastSelected(null);
    setBulkLogisticaId('');
    setBulkTransporteId('');
  };

  const asignarLogisticaMasivo = async () => {
    if (!bulkLogisticaId || selectedIds.size === 0) return;

    setBulkActualizando(true);
    try {
      await api.put('/etiquetas-envio/asignar-masivo', {
        shipping_ids: Array.from(selectedIds),
        logistica_id: parseInt(bulkLogisticaId, 10),
      });

      // Actualizar localmente
      const log = logisticas.find(l => l.id === parseInt(bulkLogisticaId, 10));
      setEtiquetas(prev =>
        prev.map(e =>
          selectedIds.has(e.shipping_id)
            ? {
                ...e,
                logistica_id: log?.id || null,
                logistica_nombre: log?.nombre || null,
                logistica_color: log?.color || null,
              }
            : e
        )
      );

      limpiarSeleccion();
      // Refresh stats
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${buildFilterParams()}`);
      setEstadisticas(statsData);
    } catch (err) {
      mostrarError(err);
    } finally {
      setBulkActualizando(false);
    }
  };

  const asignarTransporteMasivo = async () => {
    if (!bulkTransporteId || selectedIds.size === 0) return;

    const transporteId = bulkTransporteId === 'none' ? null : parseInt(bulkTransporteId, 10);

    setBulkActualizando(true);
    try {
      await api.put('/etiquetas-envio/transporte-masivo', {
        shipping_ids: Array.from(selectedIds),
        transporte_id: transporteId,
      });

      // Actualizar localmente
      const tr = transporteId ? transportes.find(t => t.id === transporteId) : null;
      setEtiquetas(prev =>
        prev.map(e =>
          selectedIds.has(e.shipping_id)
            ? {
                ...e,
                transporte_id: tr?.id || null,
                transporte_nombre: tr?.nombre || null,
                transporte_color: tr?.color || null,
                transporte_direccion: tr?.direccion || null,
                transporte_cp: tr?.cp || null,
                transporte_localidad: tr?.localidad || null,
                transporte_telefono: tr?.telefono || null,
                transporte_horario: tr?.horario || null,
              }
            : e
        )
      );

      limpiarSeleccion();
      // Refresh stats
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${buildFilterParams()}`);
      setEstadisticas(statsData);
    } catch (err) {
      mostrarError(err);
    } finally {
      setBulkActualizando(false);
    }
  };

  const toggleTurboMasivo = async (marcar) => {
    if (selectedIds.size === 0) return;

    setBulkActualizando(true);
    try {
      await api.put(`/etiquetas-envio/turbo-masivo?es_turbo=${marcar}`, {
        shipping_ids: Array.from(selectedIds),
      });

      // Actualizar localmente
      setEtiquetas(prev =>
        prev.map(e =>
          selectedIds.has(e.shipping_id)
            ? { ...e, es_turbo: marcar }
            : e
        )
      );

      limpiarSeleccion();
      // Refresh stats
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${buildFilterParams()}`);
      setEstadisticas(statsData);
    } catch (err) {
      mostrarError(err);
    } finally {
      setBulkActualizando(false);
    }
  };

  const toggleLluviaMasivo = async (marcar) => {
    if (selectedIds.size === 0) return;

    setBulkActualizando(true);
    try {
      await api.put(`/etiquetas-envio/lluvia-masivo?es_lluvia=${marcar}`, {
        shipping_ids: Array.from(selectedIds),
      });

      // Actualizar localmente
      setEtiquetas(prev =>
        prev.map(e =>
          selectedIds.has(e.shipping_id)
            ? { ...e, es_lluvia: marcar }
            : e
        )
      );

      limpiarSeleccion();
      // Refresh stats (cost may change)
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${buildFilterParams()}`);
      setEstadisticas(statsData);
    } catch (err) {
      mostrarError(err);
    } finally {
      setBulkActualizando(false);
    }
  };

  const geocodificarSeleccionados = async (ids = null) => {
    const shipping_ids = ids || Array.from(selectedIds);
    if (shipping_ids.length === 0) return;

    setBulkActualizando(true);
    try {
      const { data } = await api.post('/etiquetas-envio/geocodificar', { shipping_ids });
      const { geocodificados, ya_tenian, sin_resultado, errores } = data;

      const partes = [];
      if (geocodificados > 0) partes.push(`${geocodificados} geocodificado${geocodificados !== 1 ? 's' : ''}`);
      if (ya_tenian > 0) partes.push(`${ya_tenian} ya tenían coords`);
      if (sin_resultado > 0) partes.push(`${sin_resultado} sin resultado`);
      if (errores > 0) partes.push(`${errores} error${errores !== 1 ? 'es' : ''}`);

      showErrorToast(partes.join(' · '), geocodificados > 0 ? 'success' : 'warning');

      // Refrescar datos si algo se geocodificó
      if (geocodificados > 0) {
        await cargarDatos();
      }
    } catch (err) {
      mostrarError(err);
    } finally {
      setBulkActualizando(false);
    }
  };

  // ── Flag envío ────────────────────────────────────────────────

  const abrirFlagModal = () => {
    setFlagType('mal_pasado');
    setFlagMotivo('');
    setShowFlagModal(true);
  };

  const aplicarFlag = async () => {
    if (selectedIds.size === 0) return;
    setFlagLoading(true);
    try {
      await api.put('/etiquetas-envio/flag-masivo', {
        shipping_ids: Array.from(selectedIds),
        flag_envio: flagType,
        motivo: flagMotivo.trim() || null,
      });

      // Actualizar localmente
      setEtiquetas(prev =>
        prev.map(e =>
          selectedIds.has(e.shipping_id)
            ? { ...e, flag_envio: flagType, flag_envio_motivo: flagMotivo.trim() || null }
            : e
        )
      );

      setShowFlagModal(false);
      limpiarSeleccion();

      // Refresh stats
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${buildFilterParams()}`);
      setEstadisticas(statsData);
    } catch (err) {
      mostrarError(err);
    } finally {
      setFlagLoading(false);
    }
  };

  const quitarFlagSeleccionados = async () => {
    if (selectedIds.size === 0) return;
    setBulkActualizando(true);
    try {
      await api.put('/etiquetas-envio/flag-masivo', {
        shipping_ids: Array.from(selectedIds),
        flag_envio: null,
        motivo: null,
      });

      // Actualizar localmente
      setEtiquetas(prev =>
        prev.map(e =>
          selectedIds.has(e.shipping_id)
            ? { ...e, flag_envio: null, flag_envio_motivo: null }
            : e
        )
      );

      limpiarSeleccion();

      // Refresh stats
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${buildFilterParams()}`);
      setEstadisticas(statsData);
    } catch (err) {
      mostrarError(err);
    } finally {
      setBulkActualizando(false);
    }
  };

  const borrarSeleccionados = async () => {
    if (selectedIds.size === 0) return;
    const n = selectedIds.size;

    // Extraer palabra random de las direcciones de las etiquetas seleccionadas
    const seleccionadas = etiquetasFiltradas.filter(e => selectedIds.has(e.shipping_id));
    const palabras = seleccionadas
      .flatMap(e => {
        const fuentes = [e.mlstreet_name, e.mlcity_name, e.mlreceiver_name];
        return fuentes
          .filter(Boolean)
          .flatMap(s => s.split(/\s+/))
          .filter(w => w.length >= 4 && /^[a-záéíóúñü]+$/i.test(w));
      });
    const challengeWord = palabras.length > 0
      ? palabras[Math.floor(Math.random() * palabras.length)]
      : null;

    const { confirmed, comment } = await pedirConfirmacion(
      'Borrar etiquetas',
      `¿Borrar ${n} etiqueta${n !== 1 ? 's' : ''}? Esta acción no se puede deshacer.`,
      { challengeWord, showComment: true },
    );
    if (!confirmed) return;

    try {
      await api.delete('/etiquetas-envio', {
        data: { shipping_ids: Array.from(selectedIds), comment },
      });

      setEtiquetas(prev => prev.filter(e => !selectedIds.has(e.shipping_id)));
      limpiarSeleccion();
      // Refresh stats
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${buildFilterParams()}`);
      setEstadisticas(statsData);
    } catch (err) {
      mostrarError(err);
    }
  };

  // ── Export XLSX ─────────────────────────────────────────────

  const toggleExportColumn = (key) => {
    setExportColumns(prev => {
      if (prev.includes(key)) {
        return prev.filter(k => k !== key);
      }
      return [...prev, key];
    });
  };

  const handleExport = async () => {
    if (exportColumns.length === 0) return;
    setExporting(true);
    try {
      const columnasFinales = puedeVerCostos
        ? exportColumns
        : exportColumns.filter(c => c !== 'costo_envio');
      const params = new URLSearchParams();
      params.append('fecha_desde', fechaDesde || todayStr());
      params.append('fecha_hasta', fechaHasta || todayStr());
      params.append('columnas', columnasFinales.join(','));
      if (filtroCordon) params.append('cordon', filtroCordon);
      if (filtroLogistica) params.append('logistica_id', filtroLogistica);
      if (sinLogistica) params.append('sin_logistica', 'true');
      if (soloOutlet) params.append('solo_outlet', 'true');
      if (soloTurbo) params.append('solo_turbo', 'true');
      if (filtroMlStatus) params.append('mlstatus', filtroMlStatus);
      if (debouncedSearch) params.append('search', debouncedSearch);

      const response = await api.get(`/etiquetas-envio/export?${params}`, {
        responseType: 'blob',
      });

      // Descargar el archivo
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `envios_flex_${fechaDesde}_${fechaHasta}.xlsx`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);

      setShowExportModal(false);
    } catch (err) {
      mostrarError(err);
    } finally {
      setExporting(false);
    }
  };

  // ── Export manuales (tabla editable → XLSX) ────────────────

  const abrirExportManualesModal = () => {
    const manuales = etiquetasFiltradas.filter(
      (e) => selectedIds.has(e.shipping_id) && e.es_manual,
    );
    const rows = manuales.map((e) => ({
      shipping_id: e.shipping_id,
      numero_tracking: e.shipping_id,
      fecha_venta: e.fecha_envio || '',
      valor_declarado: '',
      peso_declarado: '',
      destinatario: e.mlreceiver_name || '',
      telefono: e.manual_phone || '',
      direccion: `${e.mlstreet_name || ''} ${e.mlstreet_number || ''}`.trim(),
      localidad: e.mlcity_name || '',
      codigo_postal: e.mlzip_code || '',
      observaciones: e.manual_comment || '',
      total_a_cobrar: '',
      logistica_inversa: '',
    }));
    setExportManualesData(rows);
    setShowExportManualesModal(true);
  };

  const handleExportManualesChange = (idx, field, value) => {
    setExportManualesData((prev) =>
      prev.map((row, i) => (i === idx ? { ...row, [field]: value } : row)),
    );
  };

  const handleExportManuales = async () => {
    if (exportManualesData.length === 0) return;
    setExportingManuales(true);
    try {
      const payload = exportManualesData.map((row) => ({
        numero_tracking: row.numero_tracking,
        fecha_venta: row.fecha_venta,
        valor_declarado: row.valor_declarado,
        peso_declarado: row.peso_declarado,
        destinatario: row.destinatario,
        telefono: row.telefono,
        direccion: row.direccion,
        localidad: row.localidad,
        codigo_postal: row.codigo_postal,
        observaciones: row.observaciones,
        total_a_cobrar: row.total_a_cobrar,
        logistica_inversa: row.logistica_inversa,
      }));

      const response = await api.post(
        '/etiquetas-envio/export-manuales',
        { envios: payload },
        { responseType: 'blob' },
      );

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute(
        'download',
        `envios_manuales_${todayStr()}.xlsx`,
      );
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);

      setShowExportManualesModal(false);
    } catch (err) {
      mostrarError(err);
    } finally {
      setExportingManuales(false);
    }
  };

  // ── Envío manual ───────────────────────────────────────────

  const abrirModalManualEnvio = async () => {
    setEditandoManualId(null);
    setManualEnvio({
      receiver_name: '',
      street_name: '',
      street_number: '',
      zip_code: '',
      city_name: '',
      phone: '',
      status: 'ready_to_ship',
      cust_id: '',
      bra_id: '',
      soh_id: '',
      logistica_id: '',
      transporte_id: '',
      comment: '',
      fecha_envio: todayStr(),
    });
    setManualEnvioCordon(null);
    setPedidoError(null);
    setCustError(null);
    setShowManualEnvioModal(true);

    // Cargar sucursales si no están cargadas
    if (sucursales.length === 0) {
      try {
        const { data } = await api.get('/clientes/filtros/sucursales');
        setSucursales(data);
      } catch {
        // silently fail — dropdown won't have options
      }
    }
  };

  const abrirModalEditarManual = async (envio) => {
    setEditandoManualId(envio.shipping_id);
    setManualEnvio({
      receiver_name: envio.mlreceiver_name || '',
      street_name: envio.mlstreet_name || '',
      street_number: envio.mlstreet_number || '',
      zip_code: envio.mlzip_code || '',
      city_name: envio.mlcity_name || '',
      status: envio.mlstatus || 'ready_to_ship',
      cust_id: envio.manual_cust_id || '',
      bra_id: envio.manual_bra_id || '',
      soh_id: envio.manual_soh_id || '',
      logistica_id: envio.logistica_id || '',
      transporte_id: envio.transporte_id || '',
      comment: envio.manual_comment || '',
      phone: envio.manual_phone || '',
      fecha_envio: envio.fecha_envio || todayStr(),
    });
    setManualEnvioCordon(envio.cordon || null);
    setPedidoError(null);
    setCustError(null);
    setShowManualEnvioModal(true);

    if (sucursales.length === 0) {
      try {
        const { data } = await api.get('/clientes/filtros/sucursales');
        setSucursales(data);
      } catch {
        // silently fail
      }
    }
  };

  const handleManualEnvioChange = (field, value) => {
    setManualEnvio(prev => ({ ...prev, [field]: value }));
  };

  const resolverCordonPorCP = async (zipCode) => {
    if (!zipCode || zipCode.length < 4) {
      setManualEnvioCordon(null);
      return;
    }
    try {
      const { data } = await api.get(`/codigos-postales/${zipCode}/cordon`);
      setManualEnvioCordon(data.cordon || null);
    } catch {
      setManualEnvioCordon(null);
    }
  };

  const buscarPedido = async () => {
    const sohId = manualEnvio.soh_id?.toString().trim();
    const braId = manualEnvio.bra_id?.toString().trim();
    if (!sohId || !braId) {
      setPedidoError('Seleccioná una sucursal y cargá el N° de pedido');
      return;
    }

    setPedidoLoading(true);
    setPedidoError(null);
    try {
      const { data } = await api.get(
        `/etiquetas-envio/lookup-pedido?soh_id=${sohId}&bra_id=${braId}`
      );
      // Auto-fill: cust_id + dirección del cliente
      let streetName = '';
      let streetNumber = '';
      if (data.cust_address) {
        const match = data.cust_address.match(/^(.+?)\s+(\d+\s*)$/);
        if (match) {
          streetName = match[1].trim();
          streetNumber = match[2].trim();
        } else {
          streetName = data.cust_address;
        }
      }
      const custPhone = data.cust_cellphone || data.cust_phone1 || '';
      setManualEnvio(prev => ({
        ...prev,
        cust_id: data.cust_id || prev.cust_id,
        receiver_name: data.cust_name || prev.receiver_name,
        street_name: streetName || prev.street_name,
        street_number: streetNumber || prev.street_number,
        zip_code: data.cust_zip || prev.zip_code,
        city_name: data.cust_city || prev.city_name,
        phone: custPhone || prev.phone,
      }));
      if (data.cust_zip) {
        resolverCordonPorCP(data.cust_zip);
      }
    } catch (err) {
      setPedidoError(err.response?.data?.detail || 'Pedido no encontrado');
    } finally {
      setPedidoLoading(false);
    }
  };

  const buscarCliente = async () => {
    const custId = manualEnvio.cust_id?.toString().trim();
    if (!custId) return;

    setCustLoading(true);
    setCustError(null);
    try {
      const { data } = await api.get(`/clientes/${custId}?comp_id=1`);
      let streetName = '';
      let streetNumber = '';
      if (data.cust_address) {
        const match = data.cust_address.match(/^(.+?)\s+(\d+\s*)$/);
        if (match) {
          streetName = match[1].trim();
          streetNumber = match[2].trim();
        } else {
          streetName = data.cust_address;
        }
      }
      const custPhone = data.cust_cellphone || data.cust_phone1 || '';
      setManualEnvio(prev => ({
        ...prev,
        receiver_name: data.cust_name || prev.receiver_name,
        street_name: streetName || prev.street_name,
        street_number: streetNumber || prev.street_number,
        zip_code: data.cust_zip || prev.zip_code,
        city_name: data.cust_city || prev.city_name,
        phone: custPhone || prev.phone,
      }));
      if (data.cust_zip) {
        resolverCordonPorCP(data.cust_zip);
      }
    } catch (err) {
      setCustError(err.response?.data?.detail || 'Cliente no encontrado');
    } finally {
      setCustLoading(false);
    }
  };

  const guardarEnvioManual = async () => {
    if (!manualEnvio.receiver_name.trim()) {
      mostrarError({ message: 'Ingresá el nombre del destinatario' });
      return;
    }
    if (!manualEnvio.street_name.trim()) {
      mostrarError({ message: 'Ingresá la calle' });
      return;
    }
    if (!manualEnvio.zip_code.trim()) {
      mostrarError({ message: 'Ingresá el código postal' });
      return;
    }

    setManualEnvioLoading(true);
    try {
      const payload = {
        fecha_envio: manualEnvio.fecha_envio,
        receiver_name: manualEnvio.receiver_name.trim(),
        street_name: manualEnvio.street_name.trim(),
        street_number: manualEnvio.street_number.trim(),
        zip_code: manualEnvio.zip_code.trim(),
        city_name: manualEnvio.city_name.trim(),
        status: manualEnvio.status,
        cust_id: manualEnvio.cust_id ? parseInt(manualEnvio.cust_id, 10) : null,
        bra_id: manualEnvio.bra_id ? parseInt(manualEnvio.bra_id, 10) : null,
        soh_id: manualEnvio.soh_id ? parseInt(manualEnvio.soh_id, 10) : null,
        logistica_id: manualEnvio.logistica_id ? parseInt(manualEnvio.logistica_id, 10) : null,
        transporte_id: manualEnvio.transporte_id ? parseInt(manualEnvio.transporte_id, 10) : null,
        comment: manualEnvio.comment.trim() || null,
        phone: manualEnvio.phone.trim() || null,
        operador_id: operador?.operadorActivo?.id,
      };

      if (editandoManualId) {
        await api.put(`/etiquetas-envio/manual-envio/${editandoManualId}`, payload);
      } else {
        await api.post('/etiquetas-envio/manual-envio', payload);
      }
      setShowManualEnvioModal(false);
      cargarDatos();
    } catch (err) {
      mostrarError(err);
    } finally {
      setManualEnvioLoading(false);
    }
  };

  // ── Impresión de etiqueta manual ─────────────────────────────

  const abrirModalPrintManual = (envio) => {
    setPrintManualEnvio(envio);
    setPrintNumBultos(1);
    setPrintTipoDomicilio('Particular');
    setPrintTipoEnvio('');
    setShowPrintManualModal(true);
  };

  const imprimirEtiquetaManual = async () => {
    if (!printManualEnvio) return;
    if (printNumBultos < 1) {
      mostrarError({ message: 'El número de bultos debe ser al menos 1' });
      return;
    }

    if (printNumBultos > 20) {
      const { confirmed } = await pedirConfirmacion(
        'Cantidad elevada de bultos',
        `Vas a generar ${printNumBultos} etiquetas (una por bulto). ¿Confirmar impresión?`,
      );
      if (!confirmed) return;
    }

    setPrintManualLoading(true);
    try {
      const params = {
        num_bultos: printNumBultos,
        tipo_domicilio_manual: printTipoDomicilio,
      };
      if (printTipoEnvio.trim()) {
        params.tipo_envio_manual = printTipoEnvio;
      }

      const { data } = await api.get(
        `/etiquetas-envio/${printManualEnvio.shipping_id}/etiqueta-manual`,
        { params, responseType: 'text' },
      );

      // Intentar imprimir vía Zebra Browser Print, fallback a descarga
      const resultado = await printZpl(data, printManualEnvio.shipping_id);

      if (resultado.method === 'zebra') {
        setScanFeedback({
          type: 'success',
          message: `Etiqueta ${printManualEnvio.shipping_id} enviada a la impresora (${printNumBultos} bulto${printNumBultos > 1 ? 's' : ''})`,
        });
      } else {
        setScanFeedback({
          type: 'duplicate',
          message: `Etiqueta ${printManualEnvio.shipping_id} descargada (Zebra no disponible)`,
        });
      }
      setTimeout(() => setScanFeedback(null), 4000);

      setShowPrintManualModal(false);
    } catch (err) {
      mostrarError(err);
    } finally {
      setPrintManualLoading(false);
    }
  };

  // ── Render ───────────────────────────────────────────────────

  const logisticasActivas = logisticas.filter(l => l.activa);
  const transportesActivos = transportes.filter(t => t.activa);

  return (
    <div className={styles.container}>
      {/* Estadísticas — clickeables para filtrar */}
      {estadisticas && (
        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{estadisticas.total}</div>
            <div className={styles.statLabel}>Etiquetas</div>
          </div>
          <button
            type="button"
            className={`${styles.statCard} ${styles.statCardClickable} ${sinLogistica ? styles.statCardActive : ''}`}
            onClick={() => { setSinLogistica(prev => !prev); setSinCordon(false); setFiltroCordon(''); }}
          >
            <div className={`${styles.statValue} ${styles.statSecondary}`}>
              {estadisticas.sin_logistica}
            </div>
            <div className={styles.statLabel}>Sin logística</div>
          </button>
          {Object.entries(estadisticas.por_cordon).map(([cordonName, qty]) => (
            <button
              key={cordonName}
              type="button"
              className={`${styles.statCard} ${styles.statCardClickable} ${filtroCordon === cordonName && !sinCordon ? styles.statCardActive : ''}`}
              onClick={() => { setFiltroCordon(prev => prev === cordonName ? '' : cordonName); setSinCordon(false); setSinLogistica(false); }}
            >
              <div className={styles.statValue}>{qty}</div>
              <div className={styles.statLabel}>{cordonName}</div>
            </button>
          ))}
          {estadisticas.sin_cordon > 0 && (
            <button
              type="button"
              className={`${styles.statCard} ${styles.statCardClickable} ${sinCordon ? styles.statCardActive : ''}`}
              onClick={() => { setSinCordon(prev => !prev); setFiltroCordon(''); setSinLogistica(false); }}
            >
              <div className={`${styles.statValue} ${styles.statSecondary}`}>
                {estadisticas.sin_cordon}
              </div>
              <div className={styles.statLabel}>Sin cordón</div>
            </button>
          )}
          {(estadisticas.flagged > 0 || soloFlag) && (
            <button
              type="button"
              className={`${styles.statCard} ${styles.statCardClickable} ${styles.statCardFlag} ${soloFlag ? styles.statCardActive : ''}`}
              onClick={() => { setSoloFlag(prev => !prev); }}
            >
              <div className={`${styles.statValue} ${styles.statValueFlag}`}>
                {estadisticas.flagged}
              </div>
              <div className={styles.statLabel}>Flaggeadas</div>
            </button>
          )}
          {puedeVerCostos && estadisticas.costo_total > 0 && (
            <div className={`${styles.statCard} ${styles.statCardCosto}`}>
              <div className={styles.statValue}>
                ${estadisticas.costo_total.toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
              </div>
              <div className={styles.statLabel}>Costo total</div>
            </div>
          )}
        </div>
      )}

      {/* Scanner — solo visible si tiene permiso de subir etiquetas */}
      {puedeSubir && (
        <div className={styles.scannerSection}>
          <ScanBarcode size={20} style={{ color: 'var(--text-tertiary)', flexShrink: 0 }} />
          <input
            ref={scanRef}
            type="text"
            value={scanInput}
            onChange={(e) => setScanInput(e.target.value)}
            onKeyDown={handleScanKeyDown}
            placeholder='Escanear QR con pistola (JSON de la etiqueta)...'
            className={styles.scannerInput}
            autoComplete="off"
          />
          {scanFeedback && (
            <div
              className={
                scanFeedback.type === 'success'
                  ? styles.feedbackSuccess
                  : scanFeedback.type === 'duplicate'
                  ? styles.feedbackDuplicate
                  : styles.feedbackError
              }
            >
              {scanFeedback.type === 'success' && <CheckCircle size={16} />}
              {scanFeedback.type === 'duplicate' && <AlertCircle size={16} />}
              {scanFeedback.type === 'error' && <AlertCircle size={16} />}
              {scanFeedback.message}
            </div>
          )}
        </div>
      )}

      {/* Controls */}
      <div className={styles.controls}>
        <div className={styles.filtros}>
          <div className={styles.dateQuickFilters}>
            <button
              type="button"
              onClick={() => setMostrarDropdownFecha(!mostrarDropdownFecha)}
              className={`${styles.btnDateQuick} ${styles.btnDateCalendar} ${filtroRapidoActivo === 'custom' ? styles.btnDateQuickActive : ''}`}
              title="Rango personalizado"
            >
              <Calendar size={14} />
            </button>
            <button
              type="button"
              onClick={() => aplicarFiltroRapido('hoy')}
              className={`${styles.btnDateQuick} ${filtroRapidoActivo === 'hoy' ? styles.btnDateQuickActive : ''}`}
            >
              Hoy
            </button>
            <button
              type="button"
              onClick={() => aplicarFiltroRapido('ayer')}
              className={`${styles.btnDateQuick} ${filtroRapidoActivo === 'ayer' ? styles.btnDateQuickActive : ''}`}
            >
              Ayer
            </button>
            <button
              type="button"
              onClick={() => aplicarFiltroRapido('3d')}
              className={`${styles.btnDateQuick} ${filtroRapidoActivo === '3d' ? styles.btnDateQuickActive : ''}`}
            >
              3d
            </button>
            <button
              type="button"
              onClick={() => aplicarFiltroRapido('7d')}
              className={`${styles.btnDateQuick} ${filtroRapidoActivo === '7d' ? styles.btnDateQuickActive : ''}`}
            >
              7d
            </button>

            {mostrarDropdownFecha && (
              <>
                <div
                  className={styles.dateDropdownOverlay}
                  onClick={() => setMostrarDropdownFecha(false)}
                />
                <div className={styles.dateDropdown}>
                  <div className={styles.dateDropdownField}>
                    <label>Desde</label>
                    <input
                      type="date"
                      value={fechaTemporal.desde}
                      onChange={(e) => setFechaTemporal({ ...fechaTemporal, desde: e.target.value })}
                      className={styles.dateDropdownInput}
                    />
                  </div>
                  <div className={styles.dateDropdownField}>
                    <label>Hasta</label>
                    <input
                      type="date"
                      value={fechaTemporal.hasta}
                      onChange={(e) => setFechaTemporal({ ...fechaTemporal, hasta: e.target.value })}
                      className={styles.dateDropdownInput}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={aplicarFechaPersonalizada}
                    className="btn-tesla outline-subtle-primary sm"
                  >
                    Aplicar
                  </button>
                </div>
              </>
            )}
          </div>

          <input
            type="text"
            placeholder="Buscar (texto o escanear QR)..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className={styles.searchInput}
          />

          <select
            value={filtroCordon}
            onChange={(e) => setFiltroCordon(e.target.value)}
            className={styles.selectSm}
          >
            <option value="">Cordón</option>
            {CORDONES.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          <select
            value={filtroLogistica}
            onChange={(e) => setFiltroLogistica(e.target.value)}
            className={styles.selectSm}
          >
            <option value="">Logística</option>
            {logisticasActivas.map(l => (
              <option key={l.id} value={l.id}>{l.nombre}</option>
            ))}
          </select>

          <select
            value={filtroMlStatus}
            onChange={(e) => setFiltroMlStatus(e.target.value)}
            className={styles.selectSm}
          >
            <option value="">Estado ML</option>
            {Object.entries(ML_STATUS_LABELS).map(([val, label]) => (
              <option key={val} value={val}>{label}</option>
            ))}
          </select>

          <select
            value={filtroPistoleado}
            onChange={(e) => setFiltroPistoleado(e.target.value)}
            className={styles.selectSm}
          >
            <option value="">Pistoleado</option>
            <option value="si">Sí</option>
            <option value="no">No</option>
          </select>

          {(() => {
            const erpOptions = [];
            const seen = new Set();
            for (const e of etiquetas) {
              if (e.ssos_id != null && !seen.has(e.ssos_id)) {
                seen.add(e.ssos_id);
                erpOptions.push({ id: e.ssos_id, name: e.ssos_name || `Estado ${e.ssos_id}` });
              }
            }
            erpOptions.sort((a, b) => a.name.localeCompare(b.name));
            if (erpOptions.length === 0) return null;
            return (
              <select
                value={filtroSsosId}
                onChange={(e) => setFiltroSsosId(e.target.value)}
                className={styles.selectSm}
              >
                <option value="">Estado ERP</option>
                {erpOptions.map(opt => (
                  <option key={opt.id} value={opt.id}>{opt.name}</option>
                ))}
              </select>
            );
          })()}

          <button
            onClick={() => setSinLogistica(!sinLogistica)}
            className={`btn-tesla sm ${sinLogistica ? 'outline-subtle-primary toggle-active' : 'secondary'}`}
          >
            Sin logística
          </button>

          <button
            onClick={() => setSoloOutlet(!soloOutlet)}
            className={`btn-tesla sm ${soloOutlet ? 'outline-subtle-primary toggle-active' : 'secondary'}`}
          >
            Outlet
          </button>

          <button
            onClick={() => setSoloTurbo(!soloTurbo)}
            className={`btn-tesla sm ${soloTurbo ? 'outline-subtle-primary toggle-active' : 'secondary'}`}
          >
            Turbo
          </button>
        </div>

        <div className={styles.actions}>
          <div className={styles.vistaToggle}>
            <button
              type="button"
              className={`${styles.vistaBtn} ${vistaActiva === 'tabla' ? styles.vistaBtnActive : ''}`}
              onClick={() => setVistaActiva('tabla')}
              aria-label="Vista tabla"
            >
              <Table size={15} />
              Tabla
            </button>
            <button
              type="button"
              className={`${styles.vistaBtn} ${vistaActiva === 'mapa' ? styles.vistaBtnActive : ''}`}
              onClick={() => setVistaActiva('mapa')}
              aria-label="Vista mapa"
            >
              <Map size={15} />
              Mapa
            </button>
            <button
              type="button"
              className={`${styles.vistaBtn} ${vistaActiva === 'calendario' ? styles.vistaBtnActive : ''}`}
              onClick={() => setVistaActiva('calendario')}
              aria-label="Vista calendario"
            >
              <Calendar size={15} />
              Calendario
            </button>
          </div>

          <button
            onClick={cargarDatos}
            className={styles.btnRefresh}
            disabled={loading}
            aria-label="Actualizar lista"
          >
            <RefreshCw size={16} />
            Actualizar
          </button>

          {puedeSubir && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip,.txt"
                onChange={handleUpload}
                className={styles.fileInputHidden}
                id="zpl-upload"
              />
              <label
                htmlFor="zpl-upload"
                className={`${styles.btnUpload} ${uploading ? styles.btnDisabled : ''}`}
              >
                <Upload size={16} />
                {uploading ? 'Subiendo...' : 'Subir ZPL'}
              </label>
            </>
          )}

          {puedeSubir && (
            <button
              onClick={abrirModalManualEnvio}
              className={styles.btnManualEnvio}
              aria-label="Agregar envío manual"
            >
              <Truck size={16} />
              Envío manual
            </button>
          )}

          {puedeExportar && (
            <button
              onClick={() => setShowExportModal(true)}
              className={styles.btnExport}
              disabled={etiquetasFiltradas.length === 0}
              aria-label="Exportar a Excel"
            >
              <Download size={16} />
              Exportar
            </button>
          )}

          {puedeGestionarLogisticas && (
            <button
              onClick={() => setShowLogisticasModal(true)}
              className={styles.btnLogisticas}
              aria-label="Gestionar logísticas"
            >
              <Settings size={16} />
              Logísticas
            </button>
          )}

          {puedeGestionarLogisticas && (
            <button
              onClick={() => setShowTransportesModal(true)}
              className={styles.btnLogisticas}
              aria-label="Gestionar transportes"
            >
              <Building size={16} />
              Transportes
            </button>
          )}
        </div>
      </div>

      {/* Upload result */}
      {uploadResult && (
        <div className={uploadResult.errores > 0 && !uploadResult.nuevas ? styles.uploadError : styles.uploadSuccess}>
          {uploadResult.nuevas !== undefined && (
            <div className={styles.uploadStats}>
              <CheckCircle size={16} />
              <span>
                {uploadResult.nuevas} nuevas, {uploadResult.duplicadas} duplicadas
                {uploadResult.errores > 0 && `, ${uploadResult.errores} errores`}
              </span>
            </div>
          )}
          {uploadResult.detalle_errores?.length > 0 && (
            <div className={styles.uploadErrors}>
              <AlertCircle size={16} />
              <ul>
                {uploadResult.detalle_errores.slice(0, 5).map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          )}
          <button
            className={styles.btnDismiss}
            onClick={() => setUploadResult(null)}
            aria-label="Cerrar mensaje"
          >
            Cerrar
          </button>
        </div>
      )}

      {/* Contenido principal: tabla, mapa o calendario */}
      {loading ? (
        <div className={styles.loading}>Cargando etiquetas...</div>
      ) : error ? (
        <div className={styles.error}>{error}</div>
      ) : vistaActiva === 'mapa' ? (
        <MapaEnviosFlex envios={etiquetas} onGeolocalizar={geocodificarSeleccionados} geocodificando={bulkActualizando} />
      ) : vistaActiva === 'calendario' ? (
        <CalendarioEnvios
          onDiaClick={(dateStr) => {
            setFechaDesde(dateStr);
            setFechaHasta(dateStr);
            setFiltroRapidoActivo('custom');
            setVistaActiva('tabla');
          }}
        />
      ) : (
        <>
        <div
          ref={topScrollRef}
          className={styles.topScrollbar}
        >
          <div style={{ width: tableWidth, height: 1 }} />
        </div>
        <div
          ref={tableContainerRef}
          className={styles.tableContainer}
          tabIndex={0}
          aria-label="Tabla de envíos — usá flechas izquierda/derecha para scroll horizontal"
        >
          <table ref={tableRef} className={styles.table}>
            <thead>
              <tr>
                <th className={styles.thCheckbox}>
                  <input
                    type="checkbox"
                    checked={selectedIds.size === etiquetasFiltradas.length && etiquetasFiltradas.length > 0}
                    onChange={seleccionarTodos}
                    className={styles.checkbox}
                    aria-label="Seleccionar todas las etiquetas"
                  />
                </th>
                <th>Shipping ID</th>
                <th>Destinatario</th>
                <th>Dirección</th>
                <th>CP</th>
                <th>Localidad</th>
                <th>Cordón</th>
                <th>Estado ERP</th>
                <th>Estado ML</th>
                <th>Fecha Envío</th>
                <th>Logística</th>
                <th>Transporte</th>
                {puedeVerCostos && <th className={styles.thCosto}>Costo</th>}
                <th>Pistoleado</th>
                <th>Caja</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {etiquetasFiltradas.length === 0 ? (
                <tr>
                  <td colSpan={puedeVerCostos ? 15 : 14} className={styles.empty}>
                    {soloFlag ? 'No hay etiquetas flaggeadas' : 'No hay etiquetas para la fecha seleccionada'}
                  </td>
                </tr>
              ) : (
                etiquetasFiltradas.map((e) => (
                  <tr
                    key={e.shipping_id}
                    className={`${selectedIds.has(e.shipping_id) ? styles.rowSelected : ''} ${e.flag_envio ? styles.rowFlagged : ''}`}
                  >
                    <td className={styles.tdCheckbox}>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(e.shipping_id)}
                        onChange={(ev) => toggleSeleccion(e.shipping_id, ev.nativeEvent.shiftKey)}
                        className={styles.checkbox}
                        aria-label={`Seleccionar envío ${e.shipping_id}`}
                      />
                    </td>
                    <td>
                      {!e.es_manual && e.ml_order_id ? (
                        <a
                          href={`https://www.mercadolibre.com.ar/ventas/${e.ml_order_id}/detalle`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={styles.shippingIdLink}
                        >
                          {e.shipping_id}
                        </a>
                      ) : (
                        <span className={styles.shippingId}>{e.shipping_id}</span>
                      )}
                      {e.es_outlet && (
                        <span className={styles.outletBadge}>Outlet</span>
                      )}
                      {e.es_turbo && (
                        <span className={styles.turboBadge}>Turbo</span>
                      )}
                      {e.es_lluvia && (
                        <span className={styles.lluviaBadge}>Lluvia</span>
                      )}
                      {e.creado_por_usuario_nombre && (
                        <span className={styles.creadoPorBadge} title={`Creado por ${e.creado_por_usuario_nombre} desde Pedidos`}>
                          {e.creado_por_usuario_nombre}
                        </span>
                      )}
                      {e.flag_envio && (
                        <span
                          className={`${styles.flagBadge} ${
                            e.flag_envio === 'mal_pasado' ? styles.flagBadgeMalPasado
                            : e.flag_envio === 'envio_cancelado' ? styles.flagBadgeCancelado
                            : e.flag_envio === 'duplicado' ? styles.flagBadgeDuplicado
                            : styles.flagBadgeOtro
                          }`}
                          title={e.flag_envio_motivo || FLAG_LABELS[e.flag_envio]}
                        >
                          <Flag size={10} />
                          {FLAG_LABELS[e.flag_envio] || e.flag_envio}
                        </span>
                      )}
                    </td>
                    <td className={styles.destinatario}>
                      <div>{e.mlreceiver_name || '—'}</div>
                      {e.mluser_nickname && (
                        <div className={styles.buyerNickname} title={`Usuario ML: ${e.mluser_nickname}`}>
                          @{e.mluser_nickname}
                        </div>
                      )}
                      {e.manual_comment && (
                        <div className={styles.manualComment} title={e.manual_comment}>
                          {e.manual_comment}
                        </div>
                      )}
                    </td>
                    <td className={styles.direccion} title={
                      e.transporte_id && e.transporte_direccion
                        ? `Transporte: ${e.transporte_direccion}${e.transporte_cp ? ` (${e.transporte_cp})` : ''}${e.transporte_localidad ? ` - ${e.transporte_localidad}` : ''} | Cliente: ${e.mlstreet_name || ''} ${e.mlstreet_number || ''}`
                        : (e.direccion_completa || `${e.mlstreet_name || ''} ${e.mlstreet_number || ''}`)
                    }>
                      {e.transporte_id && e.transporte_direccion ? (
                        <>
                          <div className={styles.direccionTransporte}>
                            <Building size={12} className={styles.transporteIcon} />
                            {e.transporte_direccion}
                            {(e.transporte_cp || e.transporte_localidad) && (
                              <span className={styles.transporteCpLocalidad}>
                                {' '}({[e.transporte_cp, e.transporte_localidad].filter(Boolean).join(' - ')})
                              </span>
                            )}
                          </div>
                          {e.mlstreet_name && (
                            <div className={styles.direccionCliente} title={`Dir. cliente: ${e.mlstreet_name} ${e.mlstreet_number || ''}`}>
                              {e.mlstreet_name} {e.mlstreet_number || ''}
                            </div>
                          )}
                        </>
                      ) : (
                        <>
                          <div>
                            {e.mlstreet_name
                              ? `${e.mlstreet_name} ${e.mlstreet_number || ''}`
                              : '—'}
                          </div>
                          {e.direccion_comentario && (
                            <div className={styles.direccionComentario} title={e.direccion_comentario}>
                              {e.direccion_comentario}
                            </div>
                          )}
                        </>
                      )}
                    </td>
                    <td>
                      {e.mlzip_code ? (
                        <a
                          href={
                            e.latitud && e.longitud
                              ? `https://www.google.com/maps?q=${e.latitud},${e.longitud}`
                              : `https://www.google.com/maps/search/${e.mlzip_code}+${e.mlcity_name || 'Buenos Aires'}+Argentina`
                          }
                          target="_blank"
                          rel="noopener noreferrer"
                          className={`${styles.cpLink} ${e.latitud ? styles.cpLinkExact : ''}`}
                          title={
                            e.latitud && e.longitud
                              ? `Ver ubicación exacta en Google Maps`
                              : `Buscar CP ${e.mlzip_code} en Google Maps`
                          }
                        >
                          <MapPin size={12} className={styles.cpIcon} />
                          <strong>{e.mlzip_code}</strong>
                        </a>
                      ) : (
                        <span className={styles.cellMuted}>—</span>
                      )}
                    </td>
                    <td className={styles.direccion}>{e.mlcity_name || '—'}</td>
                    <td>
                      <span className={`${styles.badge} ${getCordonBadgeClass(e.cordon)}`}>
                        {e.cordon || 'Sin asignar'}
                      </span>
                    </td>
                    <td>
                      {e.ssos_name ? (
                        <span
                          className={styles.erpBadge}
                          style={
                            e.ssos_color
                              ? { background: `${e.ssos_color}20`, color: e.ssos_color }
                              : undefined
                          }
                        >
                          {e.ssos_name}
                        </span>
                      ) : (
                        <span className={styles.cellMuted}>—</span>
                      )}
                    </td>
                    <td>
                      {e.es_manual && puedeVerCostos ? (
                        <select
                          value={e.mlstatus || ''}
                          onChange={(ev) => cambiarEstadoManual(e.shipping_id, ev.target.value)}
                          disabled={actualizando.has(e.shipping_id)}
                          className={`${styles.mlStatusSelect} ${getMlStatusClass(e.mlstatus)}`}
                        >
                          {!e.mlstatus && <option value="">— Sin estado —</option>}
                          <option value="ready_to_ship">Listo para enviar</option>
                          <option value="shipped">Enviado</option>
                          <option value="delivered">Entregado</option>
                        </select>
                      ) : e.mlstatus ? (
                        <span className={`${styles.badge} ${getMlStatusClass(e.mlstatus)}`}>
                          {ML_STATUS_LABELS[e.mlstatus] || e.mlstatus}
                        </span>
                      ) : (
                        <span className={styles.cellMuted}>—</span>
                      )}
                    </td>
                    <td>
                      <input
                        type="date"
                        value={e.fecha_envio}
                        onChange={(ev) => cambiarFecha(e.shipping_id, ev.target.value)}
                        disabled={!puedeCambiarFecha || actualizando.has(e.shipping_id)}
                        className={styles.fechaInput}
                      />
                    </td>
                    <td>
                      <select
                        value={e.logistica_id || ''}
                        onChange={(ev) => cambiarLogistica(e.shipping_id, ev.target.value)}
                        disabled={!puedeAsignarLogistica || actualizando.has(e.shipping_id)}
                        className={styles.logisticaSelect}
                      >
                        <option value="">— Sin asignar —</option>
                        {logisticasActivas.map(l => (
                          <option key={l.id} value={l.id}>{l.nombre}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      {e.es_manual ? (
                        <select
                          value={e.transporte_id || ''}
                          onChange={(ev) => cambiarTransporte(e.shipping_id, ev.target.value)}
                          disabled={!puedeAsignarLogistica || actualizando.has(e.shipping_id)}
                          className={styles.logisticaSelect}
                        >
                          <option value="">— Sin transporte —</option>
                          {transportesActivos.map(t => (
                            <option key={t.id} value={t.id}>{t.nombre}</option>
                          ))}
                        </select>
                      ) : (
                        e.transporte_nombre ? (
                          <span
                            className={styles.erpBadge}
                            style={
                              e.transporte_color
                                ? { background: `${e.transporte_color}20`, color: e.transporte_color }
                                : undefined
                            }
                          >
                            {e.transporte_nombre}
                          </span>
                        ) : (
                          <span className={styles.cellMuted}>—</span>
                        )
                      )}
                    </td>
                    {puedeVerCostos && (
                      <td
                        className={`${e.costo_envio != null ? styles.cellCosto : styles.cellMuted} ${e.costo_override != null ? styles.cellCostoOverride : ''} ${puedeVerCostos ? styles.cellCostoEditable : ''}`}
                        onClick={() => {
                          if (puedeVerCostos && editandoCosto !== e.shipping_id && !actualizando.has(e.shipping_id)) {
                            iniciarEdicionCosto(e.shipping_id, e.costo_override ?? e.costo_envio);
                          }
                        }}
                        title={e.costo_override != null ? 'Costo manual (click para editar)' : puedeVerCostos ? 'Click para editar costo' : undefined}
                      >
                        {editandoCosto === e.shipping_id ? (
                          <input
                            ref={costoInputRef}
                            type="number"
                            step="0.01"
                            min="0"
                            value={costoInputValue}
                            onChange={(ev) => setCostoInputValue(ev.target.value)}
                            onKeyDown={(ev) => handleCostoKeyDown(ev, e.shipping_id)}
                            onBlur={() => guardarCostoOverride(e.shipping_id)}
                            className={styles.costoInput}
                            placeholder="Vacío = auto"
                          />
                        ) : actualizando.has(e.shipping_id) ? (
                          <span className={styles.cellMuted}>...</span>
                        ) : e.costo_envio != null ? (
                          `$${e.costo_envio.toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
                        ) : (
                          '—'
                        )}
                      </td>
                    )}
                    <td className={e.pistoleado_at ? styles.cellSuccess : styles.cellMuted}>
                      {e.pistoleado_at
                        ? `${new Date(e.pistoleado_at).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })} — ${e.pistoleado_operador_nombre || ''}`
                        : '—'}
                    </td>
                    <td className={e.pistoleado_caja ? '' : styles.cellMuted}>
                      {e.pistoleado_caja || '—'}
                    </td>
                    <td>
                      {e.es_manual && puedeVerCostos && (
                        <button
                          className={styles.btnPrint}
                          onClick={() => abrirModalEditarManual(e)}
                          title="Editar envío manual"
                          aria-label={`Editar envío ${e.shipping_id}`}
                        >
                          <Pencil size={14} />
                        </button>
                      )}
                      {e.es_manual ? (
                        <button
                          className={styles.btnPrint}
                          onClick={() => abrirModalPrintManual(e)}
                          disabled={imprimiendo === e.shipping_id}
                          title="Imprimir etiqueta manual"
                          aria-label={`Imprimir etiqueta ${e.shipping_id}`}
                        >
                          <Printer size={14} />
                        </button>
                      ) : (
                        <button
                          className={styles.btnPrint}
                          onClick={() => imprimirEtiqueta(e.shipping_id)}
                          disabled={imprimiendo === e.shipping_id}
                          title="Imprimir etiqueta ZPL"
                          aria-label={`Imprimir etiqueta ${e.shipping_id}`}
                        >
                          <Printer size={14} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
           </table>
        </div>
        </>
      )}

      {/* Footer */}
      <div className={styles.footer}>
        <span>Mostrando {etiquetasFiltradas.length} etiquetas{soloFlag ? ' (flaggeadas)' : ''}</span>
      </div>

      {/* Barra de acciones flotante para selección múltiple */}
      {selectedIds.size > 0 && (
        <div className={styles.selectionBar}>
          <span className={styles.selectionCount}>
            {selectedIds.size} etiqueta{selectedIds.size !== 1 ? 's' : ''}
          </span>

          {puedeAsignarLogistica && (
            <div className={styles.selectionActions}>
              <select
                value={bulkLogisticaId}
                onChange={(ev) => setBulkLogisticaId(ev.target.value)}
                className={styles.selectionSelect}
                disabled={bulkActualizando}
              >
                <option value="">Elegir logística...</option>
                {logisticasActivas.map(l => (
                  <option key={l.id} value={l.id}>{l.nombre}</option>
                ))}
              </select>
              <button
                onClick={asignarLogisticaMasivo}
                disabled={!bulkLogisticaId || bulkActualizando}
                className={styles.selectionBtnAsignar}
              >
                {bulkActualizando ? 'Asignando...' : 'Asignar'}
              </button>
            </div>
          )}

          {puedeAsignarLogistica && (
            <div className={styles.selectionActions}>
              <select
                value={bulkTransporteId}
                onChange={(ev) => setBulkTransporteId(ev.target.value)}
                className={styles.selectionSelect}
                disabled={bulkActualizando}
              >
                <option value="">Elegir transporte...</option>
                <option value="none">— Sin transporte —</option>
                {transportesActivos.map(t => (
                  <option key={t.id} value={t.id}>{t.nombre}</option>
                ))}
              </select>
              <button
                onClick={asignarTransporteMasivo}
                disabled={!bulkTransporteId || bulkActualizando}
                className={styles.selectionBtnAsignar}
              >
                {bulkActualizando ? 'Asignando...' : 'Asignar'}
              </button>
            </div>
          )}

          {puedeAsignarTurbo && (() => {
            const todasTurbo = etiquetasFiltradas
              .filter(e => selectedIds.has(e.shipping_id))
              .every(e => e.es_turbo);
            return (
              <button
                onClick={() => toggleTurboMasivo(!todasTurbo)}
                disabled={bulkActualizando}
                className={todasTurbo ? styles.selectionBtnTurboActive : styles.selectionBtnTurbo}
                title={todasTurbo ? 'Desmarcar turbo' : 'Marcar como turbo'}
                aria-label={todasTurbo ? 'Desmarcar turbo' : 'Marcar como turbo'}
              >
                <Bike size={16} />
                {todasTurbo ? 'Quitar turbo' : 'Turbo'}
              </button>
            );
          })()}

          {puedeAsignarLluvia && (() => {
            const todasLluvia = etiquetasFiltradas
              .filter(e => selectedIds.has(e.shipping_id))
              .every(e => e.es_lluvia);
            return (
              <button
                onClick={() => toggleLluviaMasivo(!todasLluvia)}
                disabled={bulkActualizando}
                className={todasLluvia ? styles.selectionBtnLluviaActive : styles.selectionBtnLluvia}
                title={todasLluvia ? 'Desmarcar lluvia' : 'Marcar como lluvia'}
                aria-label={todasLluvia ? 'Desmarcar lluvia' : 'Marcar como lluvia'}
              >
                <CloudRain size={16} />
                {todasLluvia ? 'Quitar lluvia' : 'Lluvia'}
              </button>
            );
          })()}

          {puedeAsignarLogistica && (
            <button
              onClick={() => geocodificarSeleccionados()}
              disabled={bulkActualizando}
              className={styles.selectionBtnGeo}
              title="Geolocalizar etiquetas seleccionadas"
              aria-label="Geolocalizar etiquetas seleccionadas"
            >
              <MapPin size={16} />
              Geolocalizar
            </button>
          )}

          {puedeFlag && (
            <button
              onClick={abrirFlagModal}
              disabled={bulkActualizando}
              className={styles.selectionBtnFlag}
              title="Flaggear etiquetas seleccionadas"
              aria-label="Flaggear etiquetas seleccionadas"
            >
              <Flag size={16} />
              Flaggear
            </button>
          )}

          {puedeFlag && (() => {
            const algunaConFlag = etiquetasFiltradas
              .filter(e => selectedIds.has(e.shipping_id))
              .some(e => e.flag_envio);
            if (!algunaConFlag) return null;
            return (
              <button
                onClick={quitarFlagSeleccionados}
                disabled={bulkActualizando}
                className={styles.selectionBtnQuitarFlag}
                title="Quitar flag de las seleccionadas"
                aria-label="Quitar flag de las seleccionadas"
              >
                <Flag size={16} />
                Quitar flag
              </button>
            );
          })()}

          {/* Exportar manuales — solo si todos los seleccionados son manuales */}
          {puedeExportar && (() => {
            const seleccionadas = etiquetasFiltradas.filter(e => selectedIds.has(e.shipping_id));
            const todasManuales = seleccionadas.length > 0 && seleccionadas.every(e => e.es_manual);
            if (!todasManuales) return null;
            return (
              <button
                onClick={abrirExportManualesModal}
                disabled={bulkActualizando}
                className={styles.selectionBtnGeo}
                title="Exportar envíos manuales seleccionados"
                aria-label="Exportar envíos manuales seleccionados"
              >
                <Download size={16} />
                Exportar manuales
              </button>
            );
          })()}

          {/* Acciones rápidas cuando hay 1 solo envío seleccionado */}
          {selectedIds.size === 1 && (() => {
            const selId = Array.from(selectedIds)[0];
            const envio = etiquetasFiltradas.find(e => e.shipping_id === selId);
            if (!envio) return null;
            return (
              <>
                {envio.es_manual && puedeVerCostos && (
                  <button
                    onClick={() => abrirModalEditarManual(envio)}
                    disabled={bulkActualizando}
                    className={styles.selectionBtnGeo}
                    title="Editar envío"
                    aria-label="Editar envío"
                  >
                    <Pencil size={16} />
                    Editar
                  </button>
                )}
                <button
                  onClick={() => envio.es_manual ? abrirModalPrintManual(envio) : imprimirEtiqueta(envio.shipping_id)}
                  disabled={bulkActualizando || imprimiendo === envio.shipping_id}
                  className={styles.selectionBtnGeo}
                  title="Imprimir etiqueta"
                  aria-label="Imprimir etiqueta"
                >
                  <Printer size={16} />
                  Imprimir
                </button>
              </>
            );
          })()}

          {puedeEliminar && (
            <button
              onClick={borrarSeleccionados}
              className={styles.selectionBtnBorrar}
              title="Borrar etiquetas seleccionadas"
              aria-label="Borrar etiquetas seleccionadas"
            >
              <Trash2 size={16} />
              Borrar
            </button>
          )}

          <button
            onClick={limpiarSeleccion}
            className={styles.selectionBtnCancelar}
            aria-label="Cancelar selección"
          >
            <X size={16} />
          </button>
        </div>
      )}

      {/* Error toast inline */}
      <Toast toast={toast} onClose={hideToast} />

      {/* Confirm modal */}
      {confirmDialog && (
        <div className={styles.modalOverlay} onClick={confirmDialog.onCancel}>
          <div className={styles.confirmModal} onClick={(ev) => ev.stopPropagation()}>
            <h3 className={styles.confirmTitle}>{confirmDialog.title}</h3>
            <p className={styles.confirmMessage}>{confirmDialog.message}</p>
            {confirmDialog.showComment && (
              <div className={styles.challengeSection}>
                <p className={styles.challengeLabel}>Motivo (opcional):</p>
                <input
                  type="text"
                  value={confirmComment}
                  onChange={(ev) => setConfirmComment(ev.target.value)}
                  className={styles.challengeInput}
                  placeholder="Ej: se cargaron por error"
                  autoComplete="off"
                />
              </div>
            )}
            {confirmDialog.challengeWord && (
              <div className={styles.challengeSection}>
                <p className={styles.challengeLabel}>
                  Escribí <strong>{confirmDialog.challengeWord}</strong> para confirmar:
                </p>
                <input
                  type="text"
                  value={confirmInput}
                  onChange={(ev) => setConfirmInput(ev.target.value)}
                  className={styles.challengeInput}
                  placeholder={confirmDialog.challengeWord}
                  autoFocus
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
            )}
            <div className={styles.confirmActions}>
              <button
                className={styles.btnCancelar}
                onClick={confirmDialog.onCancel}
              >
                Cancelar
              </button>
              <button
                className={styles.btnConfirmDanger}
                onClick={confirmDialog.onConfirm}
                disabled={
                  confirmDialog.challengeWord
                    ? confirmInput.toLowerCase() !== confirmDialog.challengeWord.toLowerCase()
                    : false
                }
              >
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Logísticas */}
      {showLogisticasModal && (
        <div className={styles.modalOverlay} onClick={() => setShowLogisticasModal(false)}>
          <div className={styles.modalContent} onClick={(ev) => ev.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Logísticas</h3>
              <button
                className={styles.modalClose}
                onClick={() => setShowLogisticasModal(false)}
                aria-label="Cerrar modal"
              >
                ×
              </button>
            </div>

            <div className={styles.modalBody}>
              {/* List */}
              <div className={styles.logisticasList}>
                {logisticas.length === 0 ? (
                  <div className={styles.empty}>No hay logísticas creadas</div>
                ) : (
                  logisticas.map(l => (
                    <div
                      key={l.id}
                      className={`${styles.logisticaItem} ${!l.activa ? styles.logisticaInactiva : ''}`}
                    >
                      {editingLog?.id === l.id ? (
                        <>
                          <input
                            type="color"
                            value={editingLog.color || '#94a3b8'}
                            onChange={(ev) => setEditingLog({ ...editingLog, color: ev.target.value })}
                            className={styles.colorInput}
                          />
                          <input
                            type="text"
                            value={editingLog.nombre}
                            onChange={(ev) => setEditingLog({ ...editingLog, nombre: ev.target.value })}
                            className={styles.editInlineInput}
                            autoFocus
                            onKeyDown={(ev) => {
                              if (ev.key === 'Enter') guardarEdicionLogistica();
                              if (ev.key === 'Escape') setEditingLog(null);
                            }}
                          />
                          <button
                            className={styles.btnLogisticaAction}
                            onClick={guardarEdicionLogistica}
                            title="Guardar"
                            aria-label="Guardar cambios"
                          >
                            <CheckCircle size={16} />
                          </button>
                          <button
                            className={styles.btnLogisticaAction}
                            onClick={() => setEditingLog(null)}
                            title="Cancelar"
                            aria-label="Cancelar edición"
                          >
                            <X size={16} />
                          </button>
                        </>
                      ) : (
                        <>
                          <div
                            className={styles.logisticaColor}
                            style={{ background: l.color || '#94a3b8' }}
                          />
                          <span className={styles.logisticaNombre}>{l.nombre}</span>
                          {l.activa && (
                            <label
                              className={styles.logisticaAsignaLabel}
                              title="Al pistolear, asigna la logística en vez de verificar"
                            >
                              <input
                                type="checkbox"
                                checked={l.pistoleado_asigna || false}
                                onChange={() => {
                                  api.put(`/logisticas/${l.id}`, { pistoleado_asigna: !l.pistoleado_asigna })
                                    .then(() => cargarLogisticas())
                                    .catch(mostrarError);
                                }}
                              />
                              <ScanBarcode size={14} />
                              <span>Asigna</span>
                            </label>
                          )}
                          {l.activa && (
                            <button
                              className={styles.btnLogisticaAction}
                              onClick={() => setEditingLog({ id: l.id, nombre: l.nombre, color: l.color || '#94a3b8' })}
                              title="Editar"
                              aria-label="Editar logística"
                            >
                              <Pencil size={16} />
                            </button>
                          )}
                          <button
                            className={styles.btnLogisticaAction}
                            onClick={() => toggleLogistica(l)}
                            title={l.activa ? 'Desactivar' : 'Activar'}
                            aria-label={l.activa ? 'Desactivar logística' : 'Activar logística'}
                          >
                            {l.activa ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                          </button>
                          {l.activa && (
                            <button
                              className={styles.btnLogisticaAction}
                              onClick={() => eliminarLogistica(l)}
                              title="Desactivar"
                              aria-label="Desactivar logística"
                            >
                              <Trash2 size={16} />
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  ))
                )}
              </div>

              {/* Create form */}
              <form onSubmit={crearLogistica} className={styles.createForm}>
                <div className={styles.formField}>
                  <label htmlFor="log-nombre">Nombre</label>
                  <input
                    id="log-nombre"
                    type="text"
                    value={newLogNombre}
                    onChange={(ev) => setNewLogNombre(ev.target.value)}
                    placeholder="Ej: Andreani"
                    required
                  />
                </div>
                <div className={styles.formField}>
                  <label htmlFor="log-color">Color</label>
                  <input
                    id="log-color"
                    type="color"
                    value={newLogColor}
                    onChange={(ev) => setNewLogColor(ev.target.value)}
                    className={styles.colorInput}
                  />
                </div>
                <button type="submit" className={styles.btnCrear}>
                  <Plus size={16} />
                  Crear
                </button>
              </form>
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.btnCancelar}
                onClick={() => setShowLogisticasModal(false)}
              >
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Transportes */}
      {showTransportesModal && (
        <div className={styles.modalOverlay} onClick={() => setShowTransportesModal(false)}>
          <div className={`${styles.modalContent} ${styles.modalWide}`} onClick={(ev) => ev.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Transportes interprovinciales</h3>
              <button
                className={styles.modalClose}
                onClick={() => setShowTransportesModal(false)}
                aria-label="Cerrar modal"
              >
                ×
              </button>
            </div>

            <div className={styles.modalBody}>
              {/* List */}
              <div className={styles.logisticasList}>
                {transportes.length === 0 ? (
                  <div className={styles.empty}>No hay transportes creados</div>
                ) : (
                  transportes.map(t => (
                    <div key={t.id}>
                      <div
                        className={`${styles.logisticaItem} ${!t.activa ? styles.logisticaInactiva : ''}`}
                      >
                        <div
                          className={styles.logisticaColor}
                          style={{ background: t.color || '#94a3b8' }}
                        />
                        <div className={styles.transporteInfo}>
                          <span className={styles.logisticaNombre}>{t.nombre}</span>
                          {t.cuit && <span className={styles.transporteDetail}>CUIT: {t.cuit}</span>}
                          {t.direccion && <span className={styles.transporteDetail}>{t.direccion}</span>}
                          {(t.cp || t.localidad) && (
                            <span className={styles.transporteDetail}>
                              {[t.cp, t.localidad].filter(Boolean).join(' - ')}
                            </span>
                          )}
                          {t.telefono && <span className={styles.transporteDetail}>Tel: {t.telefono}</span>}
                          {t.horario && <span className={styles.transporteDetail}>{t.horario}</span>}
                        </div>
                        {t.activa && (
                          <button
                            className={styles.btnLogisticaAction}
                            onClick={() => setEditingTransp(
                              editingTransp?.id === t.id ? null : {
                                id: t.id, nombre: t.nombre, cuit: t.cuit || '',
                                direccion: t.direccion || '', cp: t.cp || '',
                                localidad: t.localidad || '', telefono: t.telefono || '',
                                horario: t.horario || '', color: t.color || '#8b5cf6',
                              }
                            )}
                            title="Editar"
                            aria-label="Editar transporte"
                          >
                            <Pencil size={16} />
                          </button>
                        )}
                        <button
                          className={styles.btnLogisticaAction}
                          onClick={() => toggleTransporte(t)}
                          title={t.activa ? 'Desactivar' : 'Activar'}
                          aria-label={t.activa ? 'Desactivar transporte' : 'Activar transporte'}
                        >
                          {t.activa ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                        </button>
                        {t.activa && (
                          <button
                            className={styles.btnLogisticaAction}
                            onClick={() => eliminarTransporte(t)}
                            title="Desactivar"
                            aria-label="Desactivar transporte"
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </div>
                      {editingTransp?.id === t.id && (
                        <div className={styles.editTranspForm}>
                          <div className={styles.formGrid}>
                            <div className={styles.formField}>
                              <label>Nombre</label>
                              <input
                                type="text"
                                value={editingTransp.nombre}
                                onChange={(ev) => setEditingTransp({ ...editingTransp, nombre: ev.target.value })}
                                autoFocus
                              />
                            </div>
                            <div className={styles.formField}>
                              <label>CUIT</label>
                              <input
                                type="text"
                                value={editingTransp.cuit}
                                onChange={(ev) => setEditingTransp({ ...editingTransp, cuit: ev.target.value })}
                                placeholder="30-12345678-9"
                              />
                            </div>
                            <div className={`${styles.formField} ${styles.formFieldSpan2}`}>
                              <label>Dirección</label>
                              <input
                                type="text"
                                value={editingTransp.direccion}
                                onChange={(ev) => setEditingTransp({ ...editingTransp, direccion: ev.target.value })}
                              />
                            </div>
                            <div className={styles.formField}>
                              <label>CP</label>
                              <input
                                type="text"
                                value={editingTransp.cp}
                                onChange={(ev) => setEditingTransp({ ...editingTransp, cp: ev.target.value })}
                              />
                            </div>
                            <div className={styles.formField}>
                              <label>Localidad</label>
                              <input
                                type="text"
                                value={editingTransp.localidad}
                                onChange={(ev) => setEditingTransp({ ...editingTransp, localidad: ev.target.value })}
                              />
                            </div>
                            <div className={styles.formField}>
                              <label>Teléfono</label>
                              <input
                                type="text"
                                value={editingTransp.telefono}
                                onChange={(ev) => setEditingTransp({ ...editingTransp, telefono: ev.target.value })}
                              />
                            </div>
                            <div className={styles.formField}>
                              <label>Horario</label>
                              <input
                                type="text"
                                value={editingTransp.horario}
                                onChange={(ev) => setEditingTransp({ ...editingTransp, horario: ev.target.value })}
                              />
                            </div>
                            <div className={styles.formField}>
                              <label>Color</label>
                              <input
                                type="color"
                                value={editingTransp.color}
                                onChange={(ev) => setEditingTransp({ ...editingTransp, color: ev.target.value })}
                                className={styles.colorInput}
                              />
                            </div>
                          </div>
                          <div className={styles.editTranspActions}>
                            <button className={styles.btnCrear} onClick={guardarEdicionTransporte}>
                              <CheckCircle size={16} />
                              Guardar
                            </button>
                            <button className={styles.btnCancelar} onClick={() => setEditingTransp(null)}>
                              Cancelar
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>

              {/* Create form */}
              <form onSubmit={crearTransporte} className={styles.createForm}>
                <div className={styles.formGrid}>
                  <div className={styles.formField}>
                    <label htmlFor="transp-nombre">Nombre</label>
                    <input
                      id="transp-nombre"
                      type="text"
                      value={newTranspNombre}
                      onChange={(ev) => setNewTranspNombre(ev.target.value)}
                      placeholder="Ej: Cruz del Sur"
                      required
                    />
                  </div>
                  <div className={styles.formField}>
                    <label htmlFor="transp-cuit">CUIT</label>
                    <input
                      id="transp-cuit"
                      type="text"
                      value={newTranspCuit}
                      onChange={(ev) => setNewTranspCuit(ev.target.value)}
                      placeholder="30-12345678-9"
                    />
                  </div>
                  <div className={`${styles.formField} ${styles.formFieldSpan2}`}>
                    <label htmlFor="transp-direccion">Dirección</label>
                    <input
                      id="transp-direccion"
                      type="text"
                      value={newTranspDireccion}
                      onChange={(ev) => setNewTranspDireccion(ev.target.value)}
                      placeholder="Dirección de la terminal/depósito"
                    />
                  </div>
                  <div className={styles.formField}>
                    <label htmlFor="transp-cp">CP</label>
                    <input
                      id="transp-cp"
                      type="text"
                      value={newTranspCp}
                      onChange={(ev) => setNewTranspCp(ev.target.value)}
                      placeholder="1234"
                      maxLength={10}
                    />
                  </div>
                  <div className={styles.formField}>
                    <label htmlFor="transp-localidad">Localidad</label>
                    <input
                      id="transp-localidad"
                      type="text"
                      value={newTranspLocalidad}
                      onChange={(ev) => setNewTranspLocalidad(ev.target.value)}
                      placeholder="Ciudad/localidad"
                      maxLength={200}
                    />
                  </div>
                  <div className={styles.formField}>
                    <label htmlFor="transp-telefono">Teléfono</label>
                    <input
                      id="transp-telefono"
                      type="text"
                      value={newTranspTelefono}
                      onChange={(ev) => setNewTranspTelefono(ev.target.value)}
                      placeholder="011-4444-5555"
                    />
                  </div>
                  <div className={styles.formField}>
                    <label htmlFor="transp-horario">Horario</label>
                    <input
                      id="transp-horario"
                      type="text"
                      value={newTranspHorario}
                      onChange={(ev) => setNewTranspHorario(ev.target.value)}
                      placeholder="Lun-Vie 8:00-17:00"
                    />
                  </div>
                  <div className={styles.formField}>
                    <label htmlFor="transp-color">Color</label>
                    <input
                      id="transp-color"
                      type="color"
                      value={newTranspColor}
                      onChange={(ev) => setNewTranspColor(ev.target.value)}
                      className={styles.colorInput}
                    />
                  </div>
                </div>
                <button type="submit" className={styles.btnCrear}>
                  <Plus size={16} />
                  Crear transporte
                </button>
              </form>
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.btnCancelar}
                onClick={() => setShowTransportesModal(false)}
              >
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Envío Manual */}
      {showManualEnvioModal && (
        <div className={styles.modalOverlay} onClick={() => setShowManualEnvioModal(false)}>
          <div className={`${styles.modalContent} ${styles.modalWide}`} onClick={(ev) => ev.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>{editandoManualId ? `Editar envío ${editandoManualId}` : 'Agregar envío manual'}</h3>
              <button
                className={styles.modalClose}
                onClick={() => setShowManualEnvioModal(false)}
                aria-label="Cerrar modal"
              >
                ×
              </button>
            </div>

            <div className={styles.modalBody}>
              <div className={styles.formGrid} autoComplete="off">
                {/* Fila 1: Fecha + Sucursal */}
                <div className={styles.formField}>
                  <label htmlFor="me-fecha">Fecha de envío</label>
                  <input
                    id="me-fecha"
                    type="date"
                    value={manualEnvio.fecha_envio}
                    onChange={(ev) => handleManualEnvioChange('fecha_envio', ev.target.value)}
                  />
                </div>
                <div className={styles.formField}>
                  <label htmlFor="me-sucursal">Sucursal</label>
                  <select
                    id="me-sucursal"
                    value={manualEnvio.bra_id}
                    onChange={(ev) => handleManualEnvioChange('bra_id', ev.target.value)}
                  >
                    <option value="">— Seleccionar —</option>
                    {sucursales.map(s => (
                      <option key={s.bra_id} value={s.bra_id}>{s.bra_desc}</option>
                    ))}
                  </select>
                </div>

                {/* Fila 2: N° Pedido (con búsqueda) + Logística */}
                <div className={styles.formField}>
                  <label htmlFor="me-sohid">N° Pedido (ERP)</label>
                  <div className={styles.inputWithAction}>
                    <input
                      id="me-sohid"
                      type="number"
                      value={manualEnvio.soh_id}
                      onChange={(ev) => handleManualEnvioChange('soh_id', ev.target.value)}
                      placeholder="Ej: 54321"
                      onKeyDown={(ev) => ev.key === 'Enter' && buscarPedido()}
                    />
                    <button
                      className={styles.btnInputAction}
                      onClick={buscarPedido}
                      disabled={pedidoLoading || !manualEnvio.soh_id || !manualEnvio.bra_id}
                      title="Buscar pedido y autocompletar datos del cliente"
                      aria-label="Buscar pedido"
                    >
                      {pedidoLoading ? '...' : <Search size={14} />}
                    </button>
                  </div>
                  {pedidoError && <span className={styles.fieldError}>{pedidoError}</span>}
                </div>
                <div className={styles.formField}>
                  <label htmlFor="me-logistica">Logística</label>
                  <select
                    id="me-logistica"
                    value={manualEnvio.logistica_id}
                    onChange={(ev) => handleManualEnvioChange('logistica_id', ev.target.value)}
                  >
                    <option value="">— Sin asignar —</option>
                    {logisticasActivas.map(l => (
                      <option key={l.id} value={l.id}>{l.nombre}</option>
                    ))}
                  </select>
                </div>

                {/* Fila 2b: Transporte (span 2 cols) */}
                <div className={`${styles.formField} ${styles.formFieldSpan2}`}>
                  <label htmlFor="me-transporte">Transporte interprovincial</label>
                  <select
                    id="me-transporte"
                    value={manualEnvio.transporte_id}
                    onChange={(ev) => handleManualEnvioChange('transporte_id', ev.target.value)}
                  >
                    <option value="">— Sin transporte —</option>
                    {transportesActivos.map(t => (
                      <option key={t.id} value={t.id}>
                        {t.nombre}{t.direccion ? ` — ${t.direccion}` : ''}
                      </option>
                    ))}
                  </select>
                  {manualEnvio.transporte_id && (() => {
                    const tr = transportesActivos.find(t => t.id === parseInt(manualEnvio.transporte_id, 10));
                    if (!tr) return null;
                    return (
                      <span className={styles.fieldHint}>
                        {[tr.direccion, tr.telefono, tr.horario].filter(Boolean).join(' — ')}
                      </span>
                    );
                  })()}
                </div>

                {/* Fila 3: Destinatario + Teléfono */}
                <div className={styles.formField}>
                  <label htmlFor="me-receiver">Destinatario</label>
                  <input
                    id="me-receiver"
                    type="text"
                    value={manualEnvio.receiver_name}
                    onChange={(ev) => handleManualEnvioChange('receiver_name', ev.target.value)}
                    placeholder="Nombre del destinatario"
                    autoComplete="one-time-code"
                    required
                  />
                </div>
                <div className={styles.formField}>
                  <label htmlFor="me-phone">Teléfono</label>
                  <input
                    id="me-phone"
                    type="tel"
                    value={manualEnvio.phone}
                    onChange={(ev) => handleManualEnvioChange('phone', ev.target.value)}
                    placeholder="Ej: 11 1234-5678"
                    autoComplete="one-time-code"
                  />
                </div>

                {/* Fila 4: Calle + Número */}
                <div className={styles.formField}>
                  <label htmlFor="me-street">Calle</label>
                  <input
                    id="me-street"
                    type="text"
                    value={manualEnvio.street_name}
                    onChange={(ev) => handleManualEnvioChange('street_name', ev.target.value)}
                    placeholder="Nombre de la calle"
                    autoComplete="one-time-code"
                    required
                  />
                </div>
                <div className={styles.formField}>
                  <label htmlFor="me-number">Número</label>
                  <input
                    id="me-number"
                    type="text"
                    value={manualEnvio.street_number}
                    onChange={(ev) => handleManualEnvioChange('street_number', ev.target.value)}
                    placeholder="N°"
                    autoComplete="one-time-code"
                  />
                </div>

                {/* Fila 5: CP + Ciudad */}
                <div className={styles.formField}>
                  <label htmlFor="me-zip">CP</label>
                  <input
                    id="me-zip"
                    type="text"
                    value={manualEnvio.zip_code}
                    onChange={(ev) => {
                      handleManualEnvioChange('zip_code', ev.target.value);
                      resolverCordonPorCP(ev.target.value);
                    }}
                    placeholder="1234"
                    autoComplete="one-time-code"
                    required
                  />
                  {manualEnvioCordon && (
                    <span className={styles.fieldHint}>{manualEnvioCordon}</span>
                  )}
                </div>
                <div className={styles.formField}>
                  <label htmlFor="me-city">Ciudad</label>
                  <input
                    id="me-city"
                    type="text"
                    value={manualEnvio.city_name}
                    onChange={(ev) => handleManualEnvioChange('city_name', ev.target.value)}
                    placeholder="Localidad"
                    autoComplete="one-time-code"
                  />
                </div>

                {/* Fila 6: Estado + N° Cliente */}
                <div className={styles.formField}>
                  <label htmlFor="me-status">Estado</label>
                  <select
                    id="me-status"
                    value={manualEnvio.status}
                    onChange={(ev) => handleManualEnvioChange('status', ev.target.value)}
                  >
                    <option value="ready_to_ship">Listo para enviar</option>
                    <option value="shipped">Enviado</option>
                    <option value="delivered">Entregado</option>
                  </select>
                </div>
                <div className={styles.formField}>
                  <label htmlFor="me-custid">N° Cliente (ERP)</label>
                  <div className={styles.inputWithAction}>
                    <input
                      id="me-custid"
                      type="number"
                      value={manualEnvio.cust_id}
                      onChange={(ev) => handleManualEnvioChange('cust_id', ev.target.value)}
                      placeholder="Ej: 12345"
                      onKeyDown={(ev) => ev.key === 'Enter' && buscarCliente()}
                    />
                    <button
                      className={styles.btnInputAction}
                      onClick={buscarCliente}
                      disabled={custLoading || !manualEnvio.cust_id}
                      title="Buscar cliente y autocompletar dirección"
                      aria-label="Buscar cliente"
                    >
                      {custLoading ? '...' : <Search size={14} />}
                    </button>
                  </div>
                  {custError && <span className={styles.fieldError}>{custError}</span>}
                </div>

                {/* Fila 7: Observaciones (span 2 cols) */}
                <div className={`${styles.formField} ${styles.formFieldSpan2}`}>
                  <label htmlFor="me-comment">Observaciones</label>
                  <textarea
                    id="me-comment"
                    value={manualEnvio.comment}
                    onChange={(ev) => handleManualEnvioChange('comment', ev.target.value)}
                    placeholder="Notas o instrucciones adicionales (opcional)"
                    rows={2}
                    className={styles.textarea}
                  />
                </div>
              </div>
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.btnCancelar}
                onClick={() => setShowManualEnvioModal(false)}
              >
                Cancelar
              </button>
              <button
                className={styles.btnCrear}
                onClick={guardarEnvioManual}
                disabled={manualEnvioLoading || !manualEnvio.receiver_name.trim() || !manualEnvio.zip_code.trim()}
              >
                <Truck size={16} />
                {manualEnvioLoading
                  ? (editandoManualId ? 'Guardando...' : 'Creando...')
                  : (editandoManualId ? 'Guardar cambios' : 'Crear envío')
                }
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Export */}
      {/* Modal Imprimir Etiqueta Manual */}
      {showPrintManualModal && printManualEnvio && (
        <div className={styles.modalOverlay} onClick={() => setShowPrintManualModal(false)}>
          <div className={styles.modalContent} onClick={(ev) => ev.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Imprimir etiqueta</h3>
              <button
                className={styles.modalClose}
                onClick={() => setShowPrintManualModal(false)}
                aria-label="Cerrar modal"
              >
                ×
              </button>
            </div>

            <div className={styles.modalBody}>
              <div className={styles.printPreview}>
                <div className={styles.printPreviewRow}>
                  <span className={styles.printPreviewLabel}>Destinatario</span>
                  <span className={styles.printPreviewValue}>{printManualEnvio.mlreceiver_name || '—'}</span>
                </div>
                <div className={styles.printPreviewRow}>
                  <span className={styles.printPreviewLabel}>Dirección</span>
                  <span className={styles.printPreviewValue}>
                    {printManualEnvio.mlstreet_name
                      ? `${printManualEnvio.mlstreet_name} ${printManualEnvio.mlstreet_number || ''}`
                      : '—'}
                  </span>
                </div>
                <div className={styles.printPreviewRow}>
                  <span className={styles.printPreviewLabel}>CP / Ciudad</span>
                  <span className={styles.printPreviewValue}>
                    {printManualEnvio.mlzip_code || '—'} — {printManualEnvio.mlcity_name || '—'}
                  </span>
                </div>
                {printManualEnvio.manual_comment && (
                  <div className={styles.printPreviewRow}>
                    <span className={styles.printPreviewLabel}>Observaciones</span>
                    <span className={styles.printPreviewValue}>{printManualEnvio.manual_comment}</span>
                  </div>
                )}
              </div>

              <div className={styles.formGrid}>
                <div className={styles.formField}>
                  <label htmlFor="pm-bultos">N° de bultos</label>
                  <input
                    id="pm-bultos"
                    type="number"
                    min={1}
                    value={printNumBultos}
                    onChange={(ev) => setPrintNumBultos(parseInt(ev.target.value, 10) || 1)}
                  />
                  <span className={styles.fieldHint}>
                    Se genera una etiqueta por bulto (1/{printNumBultos}, 2/{printNumBultos}...)
                  </span>
                </div>

                <div className={styles.formField}>
                  <label htmlFor="pm-domicilio">Tipo de domicilio</label>
                  <select
                    id="pm-domicilio"
                    value={printTipoDomicilio}
                    onChange={(ev) => setPrintTipoDomicilio(ev.target.value)}
                  >
                    <option value="Particular">Particular</option>
                    <option value="Comercial">Comercial</option>
                    <option value="Sucursal">Sucursal</option>
                  </select>
                  <span className={styles.fieldHint}>Aparece en el lateral derecho de la etiqueta</span>
                </div>

                <div className={`${styles.formField} ${styles.formFieldSpan2}`}>
                  <label htmlFor="pm-tipoenvio">Tipo de envío (opcional)</label>
                  <input
                    id="pm-tipoenvio"
                    type="text"
                    value={printTipoEnvio}
                    onChange={(ev) => setPrintTipoEnvio(ev.target.value)}
                    placeholder='Ej: Domicilio, Retiro en sucursal...'
                  />
                  <span className={styles.fieldHint}>Si no se completa, se usa &quot;Domicilio&quot;</span>
                </div>
              </div>
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.btnCancelar}
                onClick={() => setShowPrintManualModal(false)}
              >
                Cancelar
              </button>
              <button
                className={styles.btnCrear}
                onClick={imprimirEtiquetaManual}
                disabled={printManualLoading || printNumBultos < 1}
              >
                <Printer size={16} />
                {printManualLoading ? 'Generando...' : 'Imprimir'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Export */}
      {showExportModal && (
        <div className={styles.modalOverlay} onClick={() => setShowExportModal(false)}>
          <div className={styles.modalContent} onClick={(ev) => ev.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Exportar a Excel</h3>
              <button
                className={styles.modalClose}
                onClick={() => setShowExportModal(false)}
                aria-label="Cerrar modal"
              >
                ×
              </button>
            </div>

            <div className={styles.modalBody}>
              <p className={styles.exportInfo}>
                Rango: <strong>{fechaDesde}</strong> — <strong>{fechaHasta}</strong>
                {' · '}{etiquetasFiltradas.length} etiquetas en pantalla
              </p>

              <div className={styles.exportColumnsHeader}>
                <span className={styles.exportColumnsTitle}>Columnas a incluir</span>
                <button
                  className={styles.exportToggleAll}
                  onClick={() => {
                    const disponibles = Object.keys(EXPORT_COLUMNS).filter(k => k !== 'costo_envio' || puedeVerCostos);
                    if (exportColumns.length === disponibles.length) {
                      setExportColumns([]);
                    } else {
                      setExportColumns([...disponibles]);
                    }
                  }}
                >
                  {exportColumns.length === Object.keys(EXPORT_COLUMNS).filter(k => k !== 'costo_envio' || puedeVerCostos).length ? 'Ninguna' : 'Todas'}
                </button>
              </div>

              <div className={styles.exportColumnsList}>
                {Object.entries(EXPORT_COLUMNS)
                  .filter(([key]) => key !== 'costo_envio' || puedeVerCostos)
                  .map(([key, label]) => {
                    const idx = exportColumns.indexOf(key);
                    const isChecked = idx !== -1;
                    return (
                      <label key={key} className={`${styles.exportColumnItem} ${isChecked ? styles.exportColumnActive : ''}`}>
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => toggleExportColumn(key)}
                          className={styles.checkbox}
                        />
                        <span>{label}</span>
                        {isChecked && (
                          <span className={styles.exportColumnOrder}>({idx + 1})</span>
                        )}
                      </label>
                    );
                  })}
              </div>
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.btnCancelar}
                onClick={() => setShowExportModal(false)}
              >
                Cancelar
              </button>
              <button
                className={styles.btnExportConfirm}
                onClick={handleExport}
                disabled={exportColumns.length === 0 || exporting}
              >
                <Download size={16} />
                {exporting ? 'Exportando...' : 'Descargar XLSX'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Export Manuales */}
      {showExportManualesModal && (
        <div className={styles.modalOverlay} onClick={() => setShowExportManualesModal(false)}>
          <div className={`${styles.modalContent} ${styles.modalExportManuales}`} onClick={(ev) => ev.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Exportar envíos manuales</h3>
              <button
                className={styles.modalClose}
                onClick={() => setShowExportManualesModal(false)}
                aria-label="Cerrar modal"
              >
                ×
              </button>
            </div>

            <div className={styles.modalBody}>
              <p className={styles.exportInfo}>
                {exportManualesData.length} envío{exportManualesData.length !== 1 ? 's' : ''} manual{exportManualesData.length !== 1 ? 'es' : ''}
                {' · '}Los campos en blanco se pueden completar antes de exportar
              </p>

              <div className={styles.exportManualesTableWrap}>
                <table className={styles.exportManualesTable}>
                  <thead>
                    <tr>
                      <th>Numero de tracking</th>
                      <th>Fecha de venta</th>
                      <th>Valor declarado</th>
                      <th>Peso declarado</th>
                      <th>Destinatario</th>
                      <th>Teléfono de contacto</th>
                      <th>Dirección</th>
                      <th>Localidad</th>
                      <th>Código postal</th>
                      <th>Observaciones</th>
                      <th>4 Total a cobrar</th>
                      <th>1 Logistica Inversa</th>
                    </tr>
                  </thead>
                  <tbody>
                    {exportManualesData.map((row, idx) => (
                      <tr key={row.shipping_id}>
                        <td>
                          <input
                            type="text"
                            value={row.numero_tracking}
                            onChange={(ev) => handleExportManualesChange(idx, 'numero_tracking', ev.target.value)}
                            className={styles.exportManualesInput}
                          />
                        </td>
                        <td>
                          <input
                            type="date"
                            value={row.fecha_venta}
                            onChange={(ev) => handleExportManualesChange(idx, 'fecha_venta', ev.target.value)}
                            className={styles.exportManualesInput}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            value={row.valor_declarado}
                            onChange={(ev) => handleExportManualesChange(idx, 'valor_declarado', ev.target.value)}
                            className={styles.exportManualesInput}
                            placeholder="$"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            value={row.peso_declarado}
                            onChange={(ev) => handleExportManualesChange(idx, 'peso_declarado', ev.target.value)}
                            className={styles.exportManualesInput}
                            placeholder="kg"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            value={row.destinatario}
                            onChange={(ev) => handleExportManualesChange(idx, 'destinatario', ev.target.value)}
                            className={styles.exportManualesInput}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            value={row.telefono}
                            onChange={(ev) => handleExportManualesChange(idx, 'telefono', ev.target.value)}
                            className={styles.exportManualesInput}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            value={row.direccion}
                            onChange={(ev) => handleExportManualesChange(idx, 'direccion', ev.target.value)}
                            className={styles.exportManualesInput}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            value={row.localidad}
                            onChange={(ev) => handleExportManualesChange(idx, 'localidad', ev.target.value)}
                            className={styles.exportManualesInput}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            value={row.codigo_postal}
                            onChange={(ev) => handleExportManualesChange(idx, 'codigo_postal', ev.target.value)}
                            className={styles.exportManualesInput}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            value={row.observaciones}
                            onChange={(ev) => handleExportManualesChange(idx, 'observaciones', ev.target.value)}
                            className={styles.exportManualesInput}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            value={row.total_a_cobrar}
                            onChange={(ev) => handleExportManualesChange(idx, 'total_a_cobrar', ev.target.value)}
                            className={styles.exportManualesInput}
                            placeholder="$"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            value={row.logistica_inversa}
                            onChange={(ev) => handleExportManualesChange(idx, 'logistica_inversa', ev.target.value)}
                            className={styles.exportManualesInput}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.btnCancelar}
                onClick={() => setShowExportManualesModal(false)}
              >
                Cancelar
              </button>
              <button
                className={styles.btnExportConfirm}
                onClick={handleExportManuales}
                disabled={exportManualesData.length === 0 || exportingManuales}
              >
                <Download size={16} />
                {exportingManuales ? 'Exportando...' : 'Descargar XLSX'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Flag modal */}
      {showFlagModal && (
        <div className={styles.modalOverlay} onClick={() => setShowFlagModal(false)}>
          <div className={styles.modalContent} onClick={(ev) => ev.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Flaggear etiquetas</h3>
              <button
                className={styles.modalClose}
                onClick={() => setShowFlagModal(false)}
                aria-label="Cerrar modal"
              >
                ×
              </button>
            </div>

            <div className={styles.modalBody}>
              <p className={styles.flagModalInfo}>
                {selectedIds.size} etiqueta{selectedIds.size !== 1 ? 's' : ''} seleccionada{selectedIds.size !== 1 ? 's' : ''}
              </p>

              <div className={styles.flagFormGroup}>
                <label className={styles.flagLabel} htmlFor="flagType">Tipo de flag</label>
                <select
                  id="flagType"
                  value={flagType}
                  onChange={(ev) => setFlagType(ev.target.value)}
                  className={styles.flagSelect}
                >
                  {Object.entries(FLAG_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </div>

              <div className={styles.flagFormGroup}>
                <label className={styles.flagLabel} htmlFor="flagMotivo">Motivo / observación (opcional)</label>
                <textarea
                  id="flagMotivo"
                  value={flagMotivo}
                  onChange={(ev) => setFlagMotivo(ev.target.value)}
                  className={styles.flagTextarea}
                  placeholder="Ej: El cliente canceló la compra, se pasó doble..."
                  rows={3}
                />
              </div>
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.btnCancelar}
                onClick={() => setShowFlagModal(false)}
              >
                Cancelar
              </button>
              <button
                className={styles.btnFlag}
                onClick={aplicarFlag}
                disabled={flagLoading}
              >
                <Flag size={16} />
                {flagLoading ? 'Aplicando...' : 'Aplicar flag'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
