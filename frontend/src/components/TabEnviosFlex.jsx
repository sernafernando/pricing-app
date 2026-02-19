import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Upload, RefreshCw, MapPin, CheckCircle, AlertCircle, Settings,
  ScanBarcode, Plus, Trash2, ToggleLeft, ToggleRight, X, Download,
  Truck, Search,
} from 'lucide-react';
import api from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';
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
};

const ML_STATUS_LABELS = {
  ready_to_ship: 'Listo para enviar',
  shipped: 'Enviado',
  delivered: 'Entregado',
  cancelled: 'Cancelado',
  not_delivered: 'No entregado',
};

const todayStr = () => new Date().toISOString().split('T')[0];

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

  // Data
  const [etiquetas, setEtiquetas] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [logisticas, setLogisticas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filtros
  const [fechaDesde, setFechaDesde] = useState(todayStr());
  const [fechaHasta, setFechaHasta] = useState(todayStr());
  const [filtroCordon, setFiltroCordon] = useState('');
  const [filtroLogistica, setFiltroLogistica] = useState('');
  const [filtroMlStatus, setFiltroMlStatus] = useState('');
  // eslint-disable-next-line no-unused-vars
  const [filtroSsosId, setFiltroSsosId] = useState('');
  const [sinLogistica, setSinLogistica] = useState(false);
  const [search, setSearch] = useState('');

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

  // Inline editing
  const [actualizando, setActualizando] = useState(new Set());

  // Costo override inline editing
  const [editandoCosto, setEditandoCosto] = useState(null); // shipping_id que se está editando
  const [costoInputValue, setCostoInputValue] = useState('');
  const costoInputRef = useRef(null);

  // Selección múltiple
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [lastSelected, setLastSelected] = useState(null);
  const [bulkLogisticaId, setBulkLogisticaId] = useState('');
  const [bulkActualizando, setBulkActualizando] = useState(false);

  // Error inline (reemplaza alert())
  const [errorMsg, setErrorMsg] = useState(null);
  const errorTimerRef = useRef(null);

  // Export — array ordenado: el orden de tildado = orden de columnas en el XLSX
  const [showExportModal, setShowExportModal] = useState(false);
  const [exportColumns, setExportColumns] = useState([...Object.keys(EXPORT_COLUMNS)]);
  const [exporting, setExporting] = useState(false);

  // Modal envío manual
  const [showManualEnvioModal, setShowManualEnvioModal] = useState(false);
  const [manualEnvio, setManualEnvio] = useState({
    receiver_name: '',
    street_name: '',
    street_number: '',
    zip_code: '',
    city_name: '',
    status: 'ready_to_ship',
    cust_id: '',
    bra_id: '',
    logistica_id: '',
    comment: '',
    fecha_envio: todayStr(),
  });
  const [manualEnvioLoading, setManualEnvioLoading] = useState(false);
  const [manualEnvioCordon, setManualEnvioCordon] = useState(null);
  const [sucursales, setSucursales] = useState([]);
  const [custLoading, setCustLoading] = useState(false);
  const [custError, setCustError] = useState(null);

  // Confirm modal (reemplaza confirm())
  const [confirmDialog, setConfirmDialog] = useState(null); // { title, message, onConfirm, challengeWord?, showComment? }
  const [confirmInput, setConfirmInput] = useState('');
  const [confirmComment, setConfirmComment] = useState('');

  // ── Error feedback (reemplaza alert()) ──────────────────────

  const mostrarError = (err) => {
    const msg = err?.response?.data?.detail || err?.message || String(err);
    setErrorMsg(msg);
    if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
    errorTimerRef.current = setTimeout(() => setErrorMsg(null), 5000);
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

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (fechaDesde) params.append('fecha_desde', fechaDesde);
      if (fechaHasta) params.append('fecha_hasta', fechaHasta);
      if (filtroCordon) params.append('cordon', filtroCordon);
      if (filtroLogistica) params.append('logistica_id', filtroLogistica);
      if (sinLogistica) params.append('sin_logistica', 'true');
      if (filtroMlStatus) params.append('mlstatus', filtroMlStatus);
      if (filtroSsosId) params.append('ssos_id', filtroSsosId);
      if (search) params.append('search', search);

      const statsParams = new URLSearchParams();
      if (fechaDesde) statsParams.append('fecha_desde', fechaDesde);
      if (fechaHasta) statsParams.append('fecha_hasta', fechaHasta);

      const [etiqResponse, statsResponse] = await Promise.all([
        api.get(`/etiquetas-envio?${params}`),
        api.get(`/etiquetas-envio/estadisticas?${statsParams}`),
      ]);

      setEtiquetas(etiqResponse.data);
      setEstadisticas(statsResponse.data);
    } catch (err) {
      setError('Error cargando etiquetas');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [fechaDesde, fechaHasta, filtroCordon, filtroLogistica, sinLogistica, filtroMlStatus, filtroSsosId, search]);

  useEffect(() => {
    cargarLogisticas();
  }, [cargarLogisticas]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

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
      const statsParams = new URLSearchParams();
      if (fechaDesde) statsParams.append('fecha_desde', fechaDesde);
      if (fechaHasta) statsParams.append('fecha_hasta', fechaHasta);
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${statsParams}`);
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

  // ── Selección múltiple ─────────────────────────────────────

  const toggleSeleccion = (shippingId, shiftKey) => {
    const nueva = new Set(selectedIds);

    if (shiftKey && lastSelected !== null) {
      // Shift+click: seleccionar rango
      const ids = etiquetas.map(e => e.shipping_id);
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
    if (selectedIds.size === etiquetas.length && etiquetas.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(etiquetas.map(e => e.shipping_id)));
    }
  };

  const limpiarSeleccion = () => {
    setSelectedIds(new Set());
    setLastSelected(null);
    setBulkLogisticaId('');
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
      const statsParams = new URLSearchParams();
      if (fechaDesde) statsParams.append('fecha_desde', fechaDesde);
      if (fechaHasta) statsParams.append('fecha_hasta', fechaHasta);
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${statsParams}`);
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
    const seleccionadas = etiquetas.filter(e => selectedIds.has(e.shipping_id));
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
      const statsParams = new URLSearchParams();
      if (fechaDesde) statsParams.append('fecha_desde', fechaDesde);
      if (fechaHasta) statsParams.append('fecha_hasta', fechaHasta);
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${statsParams}`);
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
      if (filtroMlStatus) params.append('mlstatus', filtroMlStatus);
      if (search) params.append('search', search);

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

  // ── Envío manual ───────────────────────────────────────────

  const abrirModalManualEnvio = async () => {
    setManualEnvio({
      receiver_name: '',
      street_name: '',
      street_number: '',
      zip_code: '',
      city_name: '',
      status: 'ready_to_ship',
      cust_id: '',
      bra_id: '',
      logistica_id: '',
      comment: '',
      fecha_envio: todayStr(),
    });
    setManualEnvioCordon(null);
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

  const buscarCliente = async () => {
    const custId = manualEnvio.cust_id?.toString().trim();
    if (!custId) return;

    setCustLoading(true);
    setCustError(null);
    try {
      const { data } = await api.get(`/clientes/${custId}?comp_id=1`);
      // Auto-fill address fields from ERP customer data
      // cust_address is combined (e.g. "Av. Corrientes 1234"), try to split
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
      setManualEnvio(prev => ({
        ...prev,
        receiver_name: data.cust_name || prev.receiver_name,
        street_name: streetName || prev.street_name,
        street_number: streetNumber || prev.street_number,
        zip_code: data.cust_zip || prev.zip_code,
        city_name: data.cust_city || prev.city_name,
      }));
      // Resolver cordón del CP auto-completado
      if (data.cust_zip) {
        resolverCordonPorCP(data.cust_zip);
      }
    } catch (err) {
      setCustError(err.response?.data?.detail || 'Cliente no encontrado');
    } finally {
      setCustLoading(false);
    }
  };

  const crearEnvioManual = async () => {
    // Validaciones básicas
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
        logistica_id: manualEnvio.logistica_id ? parseInt(manualEnvio.logistica_id, 10) : null,
        comment: manualEnvio.comment.trim() || null,
        operador_id: operador?.operadorActivo?.id,
      };

      await api.post('/etiquetas-envio/manual-envio', payload);
      setShowManualEnvioModal(false);
      cargarDatos();
    } catch (err) {
      mostrarError(err);
    } finally {
      setManualEnvioLoading(false);
    }
  };

  // ── Render ───────────────────────────────────────────────────

  const logisticasActivas = logisticas.filter(l => l.activa);

  return (
    <div className={styles.container}>
      {/* Estadísticas */}
      {estadisticas && (
        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{estadisticas.total}</div>
            <div className={styles.statLabel}>Etiquetas</div>
          </div>
          <div className={styles.statCard}>
            <div className={`${styles.statValue} ${styles.statSecondary}`}>
              {estadisticas.sin_logistica}
            </div>
            <div className={styles.statLabel}>Sin logística</div>
          </div>
          {Object.entries(estadisticas.por_cordon).map(([cordon, qty]) => (
            <div key={cordon} className={styles.statCard}>
              <div className={styles.statValue}>{qty}</div>
              <div className={styles.statLabel}>{cordon}</div>
            </div>
          ))}
          {estadisticas.sin_cordon > 0 && (
            <div className={styles.statCard}>
              <div className={`${styles.statValue} ${styles.statSecondary}`}>
                {estadisticas.sin_cordon}
              </div>
              <div className={styles.statLabel}>Sin cordón</div>
            </div>
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
          <input
            type="date"
            value={fechaDesde}
            onChange={(e) => setFechaDesde(e.target.value)}
            className={styles.dateInput}
            title="Desde"
          />
          <span className={styles.dateRangeSep}>—</span>
          <input
            type="date"
            value={fechaHasta}
            onChange={(e) => setFechaHasta(e.target.value)}
            className={styles.dateInput}
            title="Hasta"
          />

          <input
            type="text"
            placeholder="Buscar..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={styles.searchInput}
          />

          <select
            value={filtroCordon}
            onChange={(e) => setFiltroCordon(e.target.value)}
            className={styles.select}
          >
            <option value="">Todos cordones</option>
            {CORDONES.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          <select
            value={filtroLogistica}
            onChange={(e) => setFiltroLogistica(e.target.value)}
            className={styles.select}
          >
            <option value="">Todas logísticas</option>
            {logisticasActivas.map(l => (
              <option key={l.id} value={l.id}>{l.nombre}</option>
            ))}
          </select>

          <select
            value={filtroMlStatus}
            onChange={(e) => setFiltroMlStatus(e.target.value)}
            className={styles.select}
          >
            <option value="">Todo estado ML</option>
            {Object.entries(ML_STATUS_LABELS).map(([val, label]) => (
              <option key={val} value={val}>{label}</option>
            ))}
          </select>

          <button
            onClick={() => setSinLogistica(!sinLogistica)}
            className={`btn-tesla sm ${sinLogistica ? 'outline-subtle-primary toggle-active' : 'secondary'}`}
          >
            {sinLogistica ? '✓ ' : ''}Sin logística
          </button>
        </div>

        <div className={styles.actions}>
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

          {puedeVerCostos && (
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
              disabled={etiquetas.length === 0}
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

      {/* Table */}
      {loading ? (
        <div className={styles.loading}>Cargando etiquetas...</div>
      ) : error ? (
        <div className={styles.error}>{error}</div>
      ) : (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.thCheckbox}>
                  <input
                    type="checkbox"
                    checked={selectedIds.size === etiquetas.length && etiquetas.length > 0}
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
                {puedeVerCostos && <th className={styles.thCosto}>Costo</th>}
                <th>Pistoleado</th>
                <th>Caja</th>
              </tr>
            </thead>
            <tbody>
              {etiquetas.length === 0 ? (
                <tr>
                  <td colSpan={puedeVerCostos ? 14 : 13} className={styles.empty}>
                    No hay etiquetas para la fecha seleccionada
                  </td>
                </tr>
              ) : (
                etiquetas.map((e) => (
                  <tr
                    key={e.shipping_id}
                    className={selectedIds.has(e.shipping_id) ? styles.rowSelected : ''}
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
                      <span className={styles.shippingId}>{e.shipping_id}</span>
                    </td>
                    <td className={styles.destinatario}>
                      {e.mlreceiver_name || '—'}
                    </td>
                    <td className={styles.direccion} title={e.direccion_completa || `${e.mlstreet_name || ''} ${e.mlstreet_number || ''}`}>
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
                      {e.mlstatus ? (
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
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer */}
      <div className={styles.footer}>
        <span>Mostrando {etiquetas.length} etiquetas</span>
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
      {errorMsg && (
        <div className={styles.errorToast}>
          <AlertCircle size={16} />
          <span>{errorMsg}</span>
          <button
            className={styles.errorToastClose}
            onClick={() => setErrorMsg(null)}
            aria-label="Cerrar mensaje de error"
          >
            <X size={14} />
          </button>
        </div>
      )}

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
                      <div
                        className={styles.logisticaColor}
                        style={{ background: l.color || '#94a3b8' }}
                      />
                      <span className={styles.logisticaNombre}>{l.nombre}</span>
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

      {/* Modal Envío Manual */}
      {showManualEnvioModal && (
        <div className={styles.modalOverlay} onClick={() => setShowManualEnvioModal(false)}>
          <div className={`${styles.modalContent} ${styles.modalWide}`} onClick={(ev) => ev.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Agregar envío manual</h3>
              <button
                className={styles.modalClose}
                onClick={() => setShowManualEnvioModal(false)}
                aria-label="Cerrar modal"
              >
                ×
              </button>
            </div>

            <div className={styles.modalBody}>
              {/* Fila 1: Fecha + Sucursal + Cliente */}
              <div className={styles.formRow}>
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
                    <option value="">— Sin asignar —</option>
                    {sucursales.map(s => (
                      <option key={s.bra_id} value={s.bra_id}>{s.bra_desc}</option>
                    ))}
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
              </div>

              {/* Fila 2: Destinatario */}
              <div className={styles.formRow}>
                <div className={`${styles.formField} ${styles.formFieldFull}`}>
                  <label htmlFor="me-receiver">Destinatario</label>
                  <input
                    id="me-receiver"
                    type="text"
                    value={manualEnvio.receiver_name}
                    onChange={(ev) => handleManualEnvioChange('receiver_name', ev.target.value)}
                    placeholder="Nombre del destinatario"
                    required
                  />
                </div>
              </div>

              {/* Fila 3: Calle + Número + CP + Ciudad */}
              <div className={styles.formRow}>
                <div className={styles.formField} style={{ flex: 2 }}>
                  <label htmlFor="me-street">Calle</label>
                  <input
                    id="me-street"
                    type="text"
                    value={manualEnvio.street_name}
                    onChange={(ev) => handleManualEnvioChange('street_name', ev.target.value)}
                    placeholder="Nombre de la calle"
                    required
                  />
                </div>
                <div className={styles.formField} style={{ flex: 0.5 }}>
                  <label htmlFor="me-number">Número</label>
                  <input
                    id="me-number"
                    type="text"
                    value={manualEnvio.street_number}
                    onChange={(ev) => handleManualEnvioChange('street_number', ev.target.value)}
                    placeholder="N°"
                  />
                </div>
                <div className={styles.formField} style={{ flex: 0.7 }}>
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
                    required
                  />
                  {manualEnvioCordon && (
                    <span className={styles.fieldHint}>{manualEnvioCordon}</span>
                  )}
                </div>
                <div className={styles.formField} style={{ flex: 1.5 }}>
                  <label htmlFor="me-city">Ciudad</label>
                  <input
                    id="me-city"
                    type="text"
                    value={manualEnvio.city_name}
                    onChange={(ev) => handleManualEnvioChange('city_name', ev.target.value)}
                    placeholder="Localidad"
                  />
                </div>
              </div>

              {/* Fila 4: Estado + Logística */}
              <div className={styles.formRow}>
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
              </div>

              {/* Fila 5: Comentario */}
              <div className={styles.formRow}>
                <div className={`${styles.formField} ${styles.formFieldFull}`}>
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
                onClick={crearEnvioManual}
                disabled={manualEnvioLoading || !manualEnvio.receiver_name.trim() || !manualEnvio.zip_code.trim()}
              >
                <Truck size={16} />
                {manualEnvioLoading ? 'Creando...' : 'Crear envío'}
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
                {' · '}{etiquetas.length} etiquetas en pantalla
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
    </div>
  );
}
