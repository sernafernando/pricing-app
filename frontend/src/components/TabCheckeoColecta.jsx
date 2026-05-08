import { Fragment, useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useDebounce } from '../hooks/useDebounce';
import {
  Upload, RefreshCw, Calendar, Table, ExternalLink,
  ScanBarcode, Trash2, X, CheckCircle, AlertCircle, ChevronRight,
  PackageCheck, RotateCcw, Eye, EyeOff, Move,
} from 'lucide-react';
import CalendarioEnvios from './CalendarioEnvios';
import api from '../services/api';
import { toLocalDateString } from '../utils/dateUtils';
import { usePermisos } from '../contexts/PermisosContext';
import SearchInput from './SearchInput';
import styles from './TabCheckeoColecta.module.css';

const ML_STATUS_LABELS = {
  ready_to_ship: 'Listo para enviar',
  shipped: 'Enviado',
  delivered: 'Entregado',
  cancelled: 'Cancelado',
  not_delivered: 'No entregado',
};

const ML_SUBSTATUS_LABELS = {
  out_for_delivery: 'En camino',
  soon_deliver: 'Próximo a entregar',
  waiting_for_withdrawal: 'Esperando retiro',
  in_hub: 'En centro de distribución',
  claimed_me: 'Reclamo',
  returning_to_sender: 'Devolviendo',
  delivery_behind_schedule: 'Con demora',
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

const todayStr = () => toLocalDateString();

const formatColectaTitle = (c) => {
  const f = new Date(`${c.fecha}T00:00:00`);
  const fechaLabel = f.toLocaleDateString('es-AR', { day: '2-digit', month: 'short' });
  return `${fechaLabel} #${c.numero}`;
};

// ── Calendar badge renderer for colecta ───────────────────────
const renderColectaDayBadges = (dia, calStyles) => (
  <>
    {dia.por_estado_erp && Object.keys(dia.por_estado_erp).length > 0 && (
      <div className={calStyles.badgeRow}>
        {Object.entries(dia.por_estado_erp).map(([name, count]) => (
          <span key={name} className={calStyles.badge} style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}>
            {name} {count}
          </span>
        ))}
      </div>
    )}
    {dia.por_estado_ml && Object.keys(dia.por_estado_ml).length > 0 && (
      <div className={calStyles.badgeRow}>
        {Object.entries(dia.por_estado_ml).map(([status, count]) => (
          <span key={status} className={calStyles.badge} style={{ background: 'var(--bg-tertiary)', color: 'var(--text-tertiary)' }}>
            {ML_STATUS_LABELS[status] || status} {count}
          </span>
        ))}
      </div>
    )}
  </>
);

export default function TabCheckeoColecta() {
  const { tienePermiso } = usePermisos();
  const puedeSubir = tienePermiso('envios_flex.subir_etiquetas');
  const puedeEliminar = tienePermiso('envios_flex.eliminar');

  // Data
  const [etiquetas, setEtiquetas] = useState([]);
  const [colectas, setColectas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Upload dropdown
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [showUploadDropdown, setShowUploadDropdown] = useState(false);
  const [uploadFecha, setUploadFecha] = useState(todayStr());
  const [uploadNumero, setUploadNumero] = useState(1);
  const [siguienteSugerido, setSiguienteSugerido] = useState(1);
  const fileInputRef = useRef(null);

  // Scanner individual
  const scannerRef = useRef(null);
  const scanTimeoutRef = useRef(null);
  const [scanFeedback, setScanFeedback] = useState(null);

  // Filtros — date quick filters
  const [fechaDesde, setFechaDesde] = useState(todayStr());
  const [fechaHasta, setFechaHasta] = useState(todayStr());
  const [filtroRapidoActivo, setFiltroRapidoActivo] = useState('hoy');
  const [mostrarDropdownFecha, setMostrarDropdownFecha] = useState(false);
  const [fechaTemporal, setFechaTemporal] = useState({ desde: todayStr(), hasta: todayStr() });
  const [filtroMlStatus, setFiltroMlStatus] = useState('');
  const [filtroSsosId, setFiltroSsosId] = useState('');
  const [filtroColectaId, setFiltroColectaId] = useState(null);
  const [filtroBatchId, setFiltroBatchId] = useState(null);
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 400);
  const [verDespachadas, setVerDespachadas] = useState(false);

  // Lotes de carga
  const [lotes, setLotes] = useState([]);

  // Vista: tabla o calendario
  const [vista, setVista] = useState('tabla');

  // Selección múltiple
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [lastSelected, setLastSelected] = useState(null);

  // Delete confirmation (replaces window.confirm)
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Move (reasignar) dropdown
  const [showMoveDropdown, setShowMoveDropdown] = useState(false);
  const [moveFecha, setMoveFecha] = useState(todayStr());
  const [moveNumero, setMoveNumero] = useState(1);
  const [moveResult, setMoveResult] = useState(null);
  const [moving, setMoving] = useState(false);

  // Expanded rows (product details)
  const [expandedRows, setExpandedRows] = useState(new Set());
  const [rowItems, setRowItems] = useState({});

  // ── Date quick filter logic ──────────────────────────────────

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

  // ── Data fetching ────────────────────────────────────────────

  const cargarColectas = useCallback(async () => {
    try {
      const { data } = await api.get('/colectas', {
        params: {
          fecha_desde: fechaDesde,
          fecha_hasta: fechaHasta,
          incluir_despachadas: verDespachadas,
        },
      });
      setColectas(data);
    } catch {
      // No bloqueante: si falla colectas seguimos con etiquetas
    }
  }, [fechaDesde, fechaHasta, verDespachadas]);

  const cargarLotes = useCallback(async () => {
    try {
      const params = {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta,
        incluir_despachadas: verDespachadas,
      };
      if (filtroColectaId) params.colecta_id = filtroColectaId;
      const { data } = await api.get('/etiquetas-colecta/lotes', { params });
      setLotes(data);
    } catch (err) {
      console.error('Error cargando lotes de colecta:', err);
    }
  }, [fechaDesde, fechaHasta, filtroColectaId, verDespachadas]);

  const cargarEtiquetas = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta,
        incluir_despachadas: verDespachadas,
      };
      if (filtroMlStatus) params.mlstatus = filtroMlStatus;
      if (filtroSsosId) params.ssos_id = filtroSsosId;
      if (filtroColectaId) params.colecta_id = filtroColectaId;
      if (filtroBatchId) params.upload_batch_id = filtroBatchId;
      if (debouncedSearch) params.search = debouncedSearch;

      const { data } = await api.get('/etiquetas-colecta', { params });
      setEtiquetas(data);
    } catch {
      setError('Error cargando etiquetas de colecta');
    } finally {
      setLoading(false);
    }
  }, [fechaDesde, fechaHasta, filtroMlStatus, filtroSsosId, filtroColectaId, filtroBatchId, debouncedSearch, verDespachadas]);

  const cargarTodo = useCallback(async () => {
    await Promise.all([cargarColectas(), cargarLotes(), cargarEtiquetas()]);
  }, [cargarColectas, cargarLotes, cargarEtiquetas]);

  useEffect(() => { cargarTodo(); }, [cargarTodo]);

  // Sugerir siguiente número cuando se abre el dropdown o cambia la fecha
  useEffect(() => {
    if (!showUploadDropdown) return;
    let cancelled = false;
    api.get('/colectas/siguiente-numero', { params: { fecha: uploadFecha } })
      .then(({ data }) => {
        if (cancelled) return;
        setSiguienteSugerido(data.siguiente);
        setUploadNumero(data.siguiente);
      })
      .catch(() => { /* fallback al estado actual */ });
    return () => { cancelled = true; };
  }, [showUploadDropdown, uploadFecha]);

  // Cleanup scan timeout on unmount
  useEffect(() => {
    return () => {
      if (scanTimeoutRef.current) clearTimeout(scanTimeoutRef.current);
    };
  }, []);

  // ── Upload ZPL ───────────────────────────────────────────────

  const handleUpload = async (event) => {
    const fileList = event.target.files;
    if (!fileList || fileList.length === 0) return;

    setUploading(true);
    setUploadResult(null);
    setShowUploadDropdown(false);

    try {
      const formData = new FormData();
      for (const file of fileList) formData.append('files', file);
      formData.append('fecha', uploadFecha);
      formData.append('numero', String(uploadNumero));

      const { data } = await api.post('/etiquetas-colecta/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      setUploadResult(data);
      // Auto-filtrar por el lote recién cargado para que el operador vea exactamente lo que subió
      if (data.upload_batch_id) {
        setFiltroBatchId(data.upload_batch_id);
      }
      cargarTodo();
    } catch (err) {
      setUploadResult({
        errores: 1,
        detalle_errores: [err.response?.data?.detail || err.message],
      });
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // ── Scan individual ──────────────────────────────────────────

  const handleScan = async (value) => {
    const trimmed = value.trim();
    if (!trimmed) return;

    let qrJson = trimmed;
    if (!trimmed.startsWith('{')) {
      const match = trimmed.match(/\{[^}]+\}/);
      if (match) qrJson = match[0];
      else {
        setScanFeedback({ type: 'error', msg: 'No se encontró JSON en el escaneo' });
        return;
      }
    }

    try {
      const payload = { qr_json: qrJson };
      // Si hay una colecta filtrada, escaneo va ahí. Si no, backend resuelve por hoy.
      if (filtroColectaId) payload.colecta_id = filtroColectaId;

      const { data } = await api.post('/etiquetas-colecta/scan', payload);
      if (data.nueva) {
        setScanFeedback({ type: 'ok', msg: data.mensaje });
        cargarTodo();
      } else {
        setScanFeedback({ type: 'dup', msg: data.mensaje });
      }
    } catch (err) {
      setScanFeedback({
        type: 'error',
        msg: err.response?.data?.detail || err.message,
      });
    }

    if (scannerRef.current) {
      scannerRef.current.value = '';
      scannerRef.current.focus();
    }

    if (scanTimeoutRef.current) clearTimeout(scanTimeoutRef.current);
    scanTimeoutRef.current = setTimeout(() => setScanFeedback(null), 3000);
  };

  const handleScanKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleScan(e.target.value);
    }
  };

  // ── Acciones de colecta ──────────────────────────────────────

  const despacharColecta = async (colectaId) => {
    try {
      await api.patch(`/colectas/${colectaId}/despachar`, {});
      cargarTodo();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error despachando colecta');
    }
  };

  const reabrirColecta = async (colectaId) => {
    try {
      await api.patch(`/colectas/${colectaId}/reabrir`, {});
      cargarTodo();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error reabriendo colecta');
    }
  };

  // ── Selección ────────────────────────────────────────────────

  const toggleSeleccion = (shippingId, shiftKey) => {
    const nueva = new Set(selectedIds);

    if (shiftKey && lastSelected !== null) {
      const ids = etiquetas.map((e) => e.shipping_id);
      const idxActual = ids.indexOf(shippingId);
      const idxUltimo = ids.indexOf(lastSelected);
      const inicio = Math.min(idxActual, idxUltimo);
      const fin = Math.max(idxActual, idxUltimo);
      for (let i = inicio; i <= fin; i++) nueva.add(ids[i]);
    } else if (nueva.has(shippingId)) {
      nueva.delete(shippingId);
    } else {
      nueva.add(shippingId);
    }

    setSelectedIds(nueva);
    setLastSelected(shippingId);
  };

  const seleccionarTodos = () => {
    if (selectedIds.size === etiquetas.length && etiquetas.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(etiquetas.map((e) => e.shipping_id)));
    }
  };

  const limpiarSeleccion = () => {
    setSelectedIds(new Set());
    setLastSelected(null);
    setConfirmDelete(false);
  };

  // ── Mover seleccionados a otra colecta ───────────────────────

  const moverSeleccionados = async () => {
    if (selectedIds.size === 0) return;

    setMoving(true);
    setMoveResult(null);
    try {
      const { data } = await api.post('/etiquetas-colecta/reasignar', {
        shipping_ids: Array.from(selectedIds),
        fecha: moveFecha,
        numero: moveNumero,
      });
      setMoveResult({ ok: true, ...data });
      setShowMoveDropdown(false);
      limpiarSeleccion();
      cargarTodo();
      // Auto-clear feedback después de 4s
      setTimeout(() => setMoveResult(null), 4000);
    } catch (err) {
      setMoveResult({
        ok: false,
        error: err.response?.data?.detail || err.message,
      });
    } finally {
      setMoving(false);
    }
  };

  // ── Borrar seleccionados ─────────────────────────────────────

  const borrarSeleccionados = async () => {
    if (selectedIds.size === 0) return;

    try {
      await api.delete('/etiquetas-colecta', {
        data: { shipping_ids: Array.from(selectedIds) },
      });
      setEtiquetas((prev) => prev.filter((e) => !selectedIds.has(e.shipping_id)));
      limpiarSeleccion();
      cargarTodo();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error borrando etiquetas');
    }
    setConfirmDelete(false);
  };

  // ── Expandable rows ──────────────────────────────────────────

  const toggleExpanded = async (shippingId) => {
    const newExpanded = new Set(expandedRows);

    if (newExpanded.has(shippingId)) {
      newExpanded.delete(shippingId);
      setExpandedRows(newExpanded);
      return;
    }

    newExpanded.add(shippingId);
    setExpandedRows(newExpanded);

    if (!rowItems[shippingId]) {
      setRowItems((prev) => ({ ...prev, [shippingId]: 'loading' }));
      try {
        const { data } = await api.get(`/etiquetas-colecta/${shippingId}/items`);
        setRowItems((prev) => ({ ...prev, [shippingId]: data }));
      } catch {
        setRowItems((prev) => ({ ...prev, [shippingId]: 'error' }));
      }
    }
  };

  // ── Calendar day click ───────────────────────────────────────

  const handleDiaClick = (dateStr) => {
    setFechaDesde(dateStr);
    setFechaHasta(dateStr);
    setFiltroRapidoActivo('custom');
    setVista('tabla');
  };

  // ── Derived data ─────────────────────────────────────────────

  const colectaSeleccionada = useMemo(
    () => colectas.find((c) => c.id === filtroColectaId) || null,
    [colectas, filtroColectaId],
  );

  const loteSeleccionado = useMemo(
    () => lotes.find((l) => l.upload_batch_id === filtroBatchId) || null,
    [lotes, filtroBatchId],
  );

  const formatLoteLabel = (l) => {
    const ts = new Date(l.primer_carga_at);
    const hora = ts.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
    return `${hora} · ${l.total} etiqueta${l.total !== 1 ? 's' : ''} · #${l.colecta_numero}`;
  };

  const seleccionarTodoLote = () => {
    if (!filtroBatchId) return;
    setSelectedIds(new Set(etiquetas.map((e) => e.shipping_id)));
  };

  const erpStatesMap = useMemo(() => {
    const states = new Map();
    for (const e of etiquetas) {
      if (e.ssos_id && e.ssos_name && !states.has(e.ssos_id)) {
        states.set(e.ssos_id, e.ssos_name);
      }
    }
    return states;
  }, [etiquetas]);

  const mlStatuses = useMemo(
    () => [...new Set(etiquetas.map((e) => e.mlstatus).filter(Boolean))],
    [etiquetas],
  );

  // ── Render ───────────────────────────────────────────────────

  return (
    <div className={styles.container}>
      {/* Colectas grid */}
      {colectas.length > 0 && (
        <div className={styles.colectasGrid}>
          {colectas.map((c) => {
            const isActive = filtroColectaId === c.id;
            const isDespachada = c.estado === 'despachada';
            return (
              <div
                key={c.id}
                className={`${styles.colectaCard} ${isActive ? styles.colectaCardActive : ''} ${isDespachada ? styles.colectaCardDespachada : ''}`}
                onClick={() => setFiltroColectaId(isActive ? null : c.id)}
                onKeyDown={(ev) => {
                  if (ev.key === 'Enter' || ev.key === ' ') {
                    ev.preventDefault();
                    setFiltroColectaId(isActive ? null : c.id);
                  }
                }}
                role="button"
                tabIndex={0}
                aria-label={`Filtrar por colecta ${formatColectaTitle(c)}`}
              >
                <div className={styles.colectaHeader}>
                  <span className={styles.colectaTitle}>{formatColectaTitle(c)}</span>
                  <span className={isDespachada ? styles.colectaEstadoDespachada : styles.colectaEstadoPendiente}>
                    {isDespachada ? 'Despachada' : 'Pendiente'}
                  </span>
                </div>
                <div>
                  <div className={styles.colectaTotal}>{c.total_etiquetas}</div>
                  <div className={styles.colectaTotalLabel}>etiquetas</div>
                </div>

                {/* Breakdown ERP */}
                {c.por_estado_erp && c.por_estado_erp.length > 0 && (
                  <div className={styles.colectaBreakdown}>
                    {c.por_estado_erp.map((b) => (
                      <span
                        key={`erp-${b.nombre}`}
                        className={styles.colectaBreakdownBadge}
                        style={
                          b.color
                            ? { background: `${b.color}20`, color: b.color }
                            : undefined
                        }
                      >
                        {b.nombre} {b.cantidad}
                      </span>
                    ))}
                  </div>
                )}

                {/* Breakdown ML */}
                {c.por_estado_ml && c.por_estado_ml.length > 0 && (
                  <div className={styles.colectaBreakdown}>
                    {c.por_estado_ml.map((b) => (
                      <span key={`ml-${b.nombre}`} className={styles.colectaBreakdownBadge}>
                        {ML_STATUS_LABELS[b.nombre] || b.nombre} {b.cantidad}
                      </span>
                    ))}
                  </div>
                )}

                {puedeSubir && (
                  <div className={styles.colectaActions} onClick={(ev) => ev.stopPropagation()}>
                    {!isDespachada ? (
                      <button
                        type="button"
                        onClick={() => despacharColecta(c.id)}
                        className={styles.colectaBtnDespachar}
                        title="Marcar como despachada"
                      >
                        <PackageCheck size={13} />
                        Despachar
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => reabrirColecta(c.id)}
                        className={styles.colectaBtnReabrir}
                        title="Reabrir colecta"
                      >
                        <RotateCcw size={13} />
                        Reabrir
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Filtro de colecta activo */}
      {colectaSeleccionada && (
        <div className={styles.colectaFiltro}>
          Filtrando por colecta{' '}
          <span className={styles.colectaFiltroBadge}>
            {formatColectaTitle(colectaSeleccionada)}
          </span>
          <button
            type="button"
            onClick={() => setFiltroColectaId(null)}
            className={styles.colectaFiltroClear}
            aria-label="Limpiar filtro de colecta"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Filtro de lote activo */}
      {loteSeleccionado && (
        <div className={styles.colectaFiltro}>
          Lote de carga{' '}
          <span className={styles.colectaFiltroBadge}>
            {formatLoteLabel(loteSeleccionado)}
          </span>
          <button
            type="button"
            onClick={seleccionarTodoLote}
            className={styles.toggleDespachadas}
            title="Seleccionar todas las etiquetas del lote"
          >
            Seleccionar todo
          </button>
          <button
            type="button"
            onClick={() => setFiltroBatchId(null)}
            className={styles.colectaFiltroClear}
            aria-label="Limpiar filtro de lote"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Scanner individual */}
      {puedeSubir && (
        <div className={styles.scannerSection}>
          <ScanBarcode size={20} style={{ color: 'var(--text-tertiary)' }} />
          <input
            ref={scannerRef}
            type="text"
            className={styles.scannerInput}
            placeholder={
              colectaSeleccionada
                ? `Escaneá el QR (irá a colecta ${formatColectaTitle(colectaSeleccionada)})`
                : 'Escaneá el QR de la etiqueta...'
            }
            onKeyDown={handleScanKeyDown}
            autoComplete="off"
          />
          {scanFeedback && (
            <div className={`${styles.scanFeedback} ${
              scanFeedback.type === 'ok' ? styles.scanFeedbackOk
                : scanFeedback.type === 'dup' ? styles.scanFeedbackDup
                  : styles.scanFeedbackError
            }`}>
              {scanFeedback.type === 'ok' ? <CheckCircle size={16} />
                : scanFeedback.type === 'dup' ? <AlertCircle size={16} />
                  : <X size={16} />}
              {scanFeedback.msg}
            </div>
          )}
        </div>
      )}

      {/* Controls */}
      <div className={styles.controls}>
        <div className={styles.filtros}>
          {/* Date quick filters */}
          <div className={styles.dateQuickFilters}>
            <button
              type="button"
              onClick={() => setMostrarDropdownFecha(!mostrarDropdownFecha)}
              className={`${styles.btnDateQuick} ${styles.btnDateCalendar} ${filtroRapidoActivo === 'custom' ? styles.btnDateQuickActive : ''}`}
              title="Rango personalizado"
            >
              <Calendar size={14} />
            </button>
            <button type="button" onClick={() => aplicarFiltroRapido('hoy')} className={`${styles.btnDateQuick} ${filtroRapidoActivo === 'hoy' ? styles.btnDateQuickActive : ''}`}>Hoy</button>
            <button type="button" onClick={() => aplicarFiltroRapido('ayer')} className={`${styles.btnDateQuick} ${filtroRapidoActivo === 'ayer' ? styles.btnDateQuickActive : ''}`}>Ayer</button>
            <button type="button" onClick={() => aplicarFiltroRapido('3d')} className={`${styles.btnDateQuick} ${filtroRapidoActivo === '3d' ? styles.btnDateQuickActive : ''}`}>3d</button>
            <button type="button" onClick={() => aplicarFiltroRapido('7d')} className={`${styles.btnDateQuick} ${filtroRapidoActivo === '7d' ? styles.btnDateQuickActive : ''}`}>7d</button>

            {mostrarDropdownFecha && (
              <>
                <div className={styles.dateDropdownOverlay} onClick={() => setMostrarDropdownFecha(false)} />
                <div className={styles.dateDropdown}>
                  <div className={styles.dateDropdownField}>
                    <label>Desde</label>
                    <input type="date" value={fechaTemporal.desde} onChange={(e) => setFechaTemporal({ ...fechaTemporal, desde: e.target.value })} className={styles.dateDropdownInput} />
                  </div>
                  <div className={styles.dateDropdownField}>
                    <label>Hasta</label>
                    <input type="date" value={fechaTemporal.hasta} onChange={(e) => setFechaTemporal({ ...fechaTemporal, hasta: e.target.value })} className={styles.dateDropdownInput} />
                  </div>
                  <button type="button" onClick={aplicarFechaPersonalizada} className="btn-tesla outline-subtle-primary sm">Aplicar</button>
                </div>
              </>
            )}
          </div>

          <SearchInput value={search} onChange={setSearch} placeholder="Shipping ID o destinatario..." size="sm" className={styles.searchFilter} />

          <select value={filtroMlStatus} onChange={(e) => setFiltroMlStatus(e.target.value)} className={styles.selectSm}>
            <option value="">Estado ML</option>
            {mlStatuses.map((s) => (<option key={s} value={s}>{ML_STATUS_LABELS[s] || s}</option>))}
          </select>

          {erpStatesMap.size > 0 && (
            <select value={filtroSsosId} onChange={(e) => setFiltroSsosId(e.target.value)} className={styles.selectSm}>
              <option value="">Estado ERP</option>
              {[...erpStatesMap.entries()]
                .sort(([, a], [, b]) => a.localeCompare(b))
                .map(([id, name]) => (<option key={id} value={id}>{name}</option>))}
            </select>
          )}

          {/* Selector de lote — siempre visible para que el usuario sepa que existe */}
          <select
            value={filtroBatchId || ''}
            onChange={(e) => setFiltroBatchId(e.target.value || null)}
            className={styles.selectSm}
            title={
              lotes.length > 0
                ? 'Filtrar por lote de carga'
                : 'Sin lotes en este rango (subí ZPLs para crear uno)'
            }
            disabled={lotes.length === 0}
          >
            <option value="">
              {lotes.length > 0 ? `Lote (${lotes.length})` : 'Lote — sin lotes'}
            </option>
            {lotes.map((l) => (
              <option key={l.upload_batch_id} value={l.upload_batch_id}>
                {formatLoteLabel(l)}
              </option>
            ))}
          </select>

          {/* Toggle ver despachadas */}
          <button
            type="button"
            onClick={() => setVerDespachadas(!verDespachadas)}
            className={`${styles.toggleDespachadas} ${verDespachadas ? styles.toggleDespachadasActive : ''}`}
            title={verDespachadas ? 'Ocultar colectas despachadas' : 'Ver colectas despachadas'}
          >
            {verDespachadas ? <Eye size={14} /> : <EyeOff size={14} />}
            {verDespachadas ? 'Despachadas: ON' : 'Despachadas: OFF'}
          </button>
        </div>

        <div className={styles.actions}>
          <div className={styles.vistaToggle}>
            <button type="button" className={`${styles.vistaBtn} ${vista === 'tabla' ? styles.vistaBtnActive : ''}`} onClick={() => setVista('tabla')} aria-label="Vista tabla">
              <Table size={15} />
              Tabla
            </button>
            <button type="button" className={`${styles.vistaBtn} ${vista === 'calendario' ? styles.vistaBtnActive : ''}`} onClick={() => setVista('calendario')} aria-label="Vista calendario">
              <Calendar size={15} />
              Calendario
            </button>
          </div>

          <button onClick={cargarTodo} className={styles.btnRefresh} disabled={loading} aria-label="Actualizar lista">
            <RefreshCw size={16} className={loading ? styles.spin : ''} />
            Actualizar
          </button>

          {/* Upload dropdown */}
          {puedeSubir && (
            <div className={styles.uploadDropdownWrap}>
              <button
                type="button"
                onClick={() => setShowUploadDropdown(!showUploadDropdown)}
                className={`${styles.btnUpload} ${uploading ? styles.btnDisabled : ''}`}
                disabled={uploading}
              >
                <Upload size={16} />
                {uploading ? 'Subiendo...' : 'Subir ZPLs'}
              </button>

              {showUploadDropdown && (
                <>
                  <div className={styles.dateDropdownOverlay} onClick={() => setShowUploadDropdown(false)} />
                  <div className={styles.uploadDropdown}>
                    <div className={styles.uploadDropdownField}>
                      <label>Fecha de la colecta</label>
                      <input
                        type="date"
                        value={uploadFecha}
                        onChange={(e) => setUploadFecha(e.target.value)}
                        className={styles.uploadDropdownInput}
                      />
                    </div>
                    <div className={styles.uploadDropdownField}>
                      <label>Número de colecta del día</label>
                      <input
                        type="number"
                        min="1"
                        value={uploadNumero}
                        onChange={(e) => setUploadNumero(parseInt(e.target.value, 10) || 1)}
                        className={styles.uploadDropdownInput}
                      />
                      <span className={styles.uploadDropdownHint}>
                        Sugerido: #{siguienteSugerido} (próximo libre)
                      </span>
                    </div>
                    <div className={styles.uploadDropdownActions}>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".zip,.txt"
                        multiple
                        onChange={handleUpload}
                        className={styles.fileInputHidden}
                        id="colecta-zpl-upload"
                      />
                      <label
                        htmlFor="colecta-zpl-upload"
                        className={`${styles.btnUpload} ${styles.uploadDropdownBtnFile}`}
                      >
                        <Upload size={14} />
                        Elegir archivos
                      </label>
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Upload result */}
      {uploadResult && (
        <div className={uploadResult.errores > 0 && !uploadResult.nuevas ? styles.uploadError : styles.uploadSuccess}>
          {uploadResult.nuevas !== undefined && (
            <p>
              <strong>{uploadResult.total}</strong> etiquetas procesadas:{' '}
              {uploadResult.nuevas} nuevas, {uploadResult.duplicadas} duplicadas
              {uploadResult.errores > 0 && `, ${uploadResult.errores} errores`}
            </p>
          )}
          {uploadResult.detalle_errores?.length > 0 && (
            <ul className={styles.errorList}>
              {uploadResult.detalle_errores.slice(0, 5).map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Delete confirmation bar */}
      {confirmDelete && (
        <div className={styles.confirmBar}>
          <span className={styles.confirmMsg}>
            ¿Borrar {selectedIds.size} etiqueta{selectedIds.size !== 1 ? 's' : ''} de colecta? Esta acción no se puede deshacer.
          </span>
          <button onClick={borrarSeleccionados} className={styles.btnConfirmDelete}>
            <Trash2 size={14} />
            Confirmar
          </button>
          <button onClick={() => setConfirmDelete(false)} className={styles.btnConfirmCancel}>
            Cancelar
          </button>
        </div>
      )}

      {error && <div className={styles.errorMsg}>{error}</div>}

      {/* Calendar view */}
      {vista === 'calendario' && (
        <CalendarioEnvios
          onDiaClick={handleDiaClick}
          endpointUrl="/etiquetas-colecta/estadisticas-por-dia"
          renderDayBadges={renderColectaDayBadges}
        />
      )}

      {/* Table view */}
      {vista === 'tabla' && (
        <>
          {loading ? (
            <div className={styles.loadingMsg}>Cargando etiquetas...</div>
          ) : etiquetas.length === 0 ? (
            <div className={styles.emptyMsg}>
              {colectas.length === 0
                ? 'No hay colectas en este rango. Subí ZPLs para crear una.'
                : 'No hay etiquetas para los filtros aplicados.'}
            </div>
          ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th style={{ width: 40 }}>
                      <input
                        type="checkbox"
                        checked={selectedIds.size === etiquetas.length && etiquetas.length > 0}
                        onChange={seleccionarTodos}
                      />
                    </th>
                    <th style={{ width: 24 }} />
                    <th>Shipping ID</th>
                    <th>Colecta</th>
                    <th>Destinatario</th>
                    <th>Estado ERP</th>
                    <th>Estado ML</th>
                  </tr>
                </thead>
                <tbody>
                  {etiquetas.map((e) => {
                    const isExpanded = expandedRows.has(e.shipping_id);
                    const items = rowItems[e.shipping_id];

                    return (
                      <Fragment key={e.shipping_id}>
                        <tr
                          className={`${selectedIds.has(e.shipping_id) ? styles.rowSelected : ''} ${styles.rowClickable}`}
                          onClick={() => toggleExpanded(e.shipping_id)}
                        >
                          <td onClick={(ev) => ev.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={selectedIds.has(e.shipping_id)}
                              onChange={(ev) => toggleSeleccion(e.shipping_id, ev.nativeEvent.shiftKey)}
                            />
                          </td>
                          <td>
                            <ChevronRight
                              size={14}
                              className={`${styles.expandIcon} ${isExpanded ? styles.expandIconOpen : ''}`}
                            />
                          </td>
                          <td className={styles.shippingCell}>
                            {e.ml_order_id ? (
                              <a
                                href={`https://www.mercadolibre.com.ar/ventas/${e.ml_order_id}/detalle`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className={styles.shippingLink}
                                onClick={(ev) => ev.stopPropagation()}
                              >
                                {e.shipping_id}
                                <ExternalLink size={12} className={styles.externalIcon} />
                              </a>
                            ) : (
                              <span>{e.shipping_id}</span>
                            )}
                          </td>
                          <td>
                            <span className={styles.colectaNumero}>
                              #{e.colecta_numero}
                              {e.colecta_estado === 'despachada' && (
                                <PackageCheck
                                  size={12}
                                  style={{ marginLeft: 4, verticalAlign: 'middle' }}
                                  aria-label="Despachada"
                                />
                              )}
                            </span>
                          </td>
                          <td>{e.mlreceiver_name || <span className={styles.cellMuted}>—</span>}</td>
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
                                {e.mlsubstatus && ML_SUBSTATUS_LABELS[e.mlsubstatus] && (
                                  <span className={styles.substatus}>
                                    {' '}({ML_SUBSTATUS_LABELS[e.mlsubstatus]})
                                  </span>
                                )}
                              </span>
                            ) : (
                              <span className={styles.cellMuted}>—</span>
                            )}
                          </td>
                        </tr>

                        {isExpanded && (
                          <tr className={styles.expandedRow}>
                            <td colSpan={7}>
                              {items === 'loading' && (
                                <div className={styles.expandedLoading}>Cargando productos...</div>
                              )}
                              {items === 'error' && (
                                <div className={styles.expandedEmpty}>Error cargando productos</div>
                              )}
                              {Array.isArray(items) && items.length === 0 && (
                                <div className={styles.expandedEmpty}>Sin productos vinculados</div>
                              )}
                              {Array.isArray(items) && items.length > 0 && (
                                <div className={styles.expandedContent}>
                                  <div className={styles.itemsList}>
                                    {items.map((item, idx) => (
                                      <div key={idx} className={styles.itemRow}>
                                        {item.item_code && (
                                          <span className={styles.itemCode}>{item.item_code}</span>
                                        )}
                                        <span className={styles.itemDesc}>{item.descripcion}</span>
                                        <span className={styles.itemQty}>x{item.cantidad}</span>
                                        {item.precio_unitario != null && (
                                          <span className={styles.itemPrice}>
                                            ${item.precio_unitario.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                                          </span>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {!loading && etiquetas.length > 0 && (
            <div className={styles.footer}>
              <span>Mostrando {etiquetas.length} etiquetas</span>
            </div>
          )}
        </>
      )}

      {/* Move result feedback */}
      {moveResult && (
        <div className={moveResult.ok ? styles.uploadSuccess : styles.uploadError}>
          {moveResult.ok ? (
            <p>
              <strong>{moveResult.movidas}</strong> etiqueta{moveResult.movidas !== 1 ? 's' : ''} movida
              {moveResult.movidas !== 1 ? 's' : ''} a colecta {moveResult.colecta_destino_fecha} #
              {moveResult.colecta_destino_numero}
              {moveResult.no_encontradas?.length > 0 && (
                <> · {moveResult.no_encontradas.length} no encontrada{moveResult.no_encontradas.length !== 1 ? 's' : ''}</>
              )}
            </p>
          ) : (
            <p>Error al mover: {moveResult.error}</p>
          )}
        </div>
      )}

      {/* Selection bar */}
      {selectedIds.size > 0 && !confirmDelete && (
        <div className={styles.selectionBar}>
          <span className={styles.selectionCount}>
            {selectedIds.size} etiqueta{selectedIds.size !== 1 ? 's' : ''}
          </span>

          <div className={styles.selectionActions}>
            {puedeSubir && (
              <div className={styles.uploadDropdownWrap}>
                <button
                  onClick={() => setShowMoveDropdown(!showMoveDropdown)}
                  className={styles.colectaBtnDespachar}
                  title="Mover a otra colecta"
                  aria-label="Mover etiquetas seleccionadas a otra colecta"
                  disabled={moving}
                >
                  <Move size={16} />
                  {moving ? 'Moviendo...' : 'Mover'}
                </button>

                {showMoveDropdown && (
                  <>
                    <div className={styles.dateDropdownOverlay} onClick={() => setShowMoveDropdown(false)} />
                    <div className={`${styles.uploadDropdown} ${styles.uploadDropdownAbove}`}>
                      <div className={styles.uploadDropdownField}>
                        <label>Fecha colecta destino</label>
                        <input
                          type="date"
                          value={moveFecha}
                          onChange={(e) => setMoveFecha(e.target.value)}
                          className={styles.uploadDropdownInput}
                        />
                      </div>
                      <div className={styles.uploadDropdownField}>
                        <label>Número de colecta</label>
                        <input
                          type="number"
                          min="1"
                          value={moveNumero}
                          onChange={(e) => setMoveNumero(parseInt(e.target.value, 10) || 1)}
                          className={styles.uploadDropdownInput}
                        />
                        <span className={styles.uploadDropdownHint}>
                          Si no existe, se crea. Debe estar pendiente.
                        </span>
                      </div>
                      <div className={styles.uploadDropdownActions}>
                        <button
                          type="button"
                          onClick={moverSeleccionados}
                          className={`${styles.btnUpload} ${styles.uploadDropdownBtnFile}`}
                          disabled={moving}
                        >
                          <Move size={14} />
                          Mover {selectedIds.size}
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {puedeEliminar && (
              <button
                onClick={() => setConfirmDelete(true)}
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
        </div>
      )}
    </div>
  );
}
