import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Upload, RefreshCw, MapPin, CheckCircle, AlertCircle, Settings,
  ScanBarcode, Plus, Trash2, ToggleLeft, ToggleRight, X,
} from 'lucide-react';
import api from '../services/api';
import styles from './TabEnviosFlex.module.css';

const CORDONES = ['CABA', 'Cordón 1', 'Cordón 2', 'Cordón 3'];

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

// eslint-disable-next-line no-unused-vars
export default function TabEnviosFlex({ operador = null }) {
  // Data
  const [etiquetas, setEtiquetas] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [logisticas, setLogisticas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filtros
  const [fechaEnvio, setFechaEnvio] = useState(todayStr());
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

  // Selección múltiple
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [lastSelected, setLastSelected] = useState(null);
  const [bulkLogisticaId, setBulkLogisticaId] = useState('');
  const [bulkActualizando, setBulkActualizando] = useState(false);

  // Error inline (reemplaza alert())
  const [errorMsg, setErrorMsg] = useState(null);
  const errorTimerRef = useRef(null);

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
      if (fechaEnvio) params.append('fecha_envio', fechaEnvio);
      if (filtroCordon) params.append('cordon', filtroCordon);
      if (filtroLogistica) params.append('logistica_id', filtroLogistica);
      if (sinLogistica) params.append('sin_logistica', 'true');
      if (filtroMlStatus) params.append('mlstatus', filtroMlStatus);
      if (filtroSsosId) params.append('ssos_id', filtroSsosId);
      if (search) params.append('search', search);

      const statsParams = new URLSearchParams();
      if (fechaEnvio) statsParams.append('fecha_envio', fechaEnvio);

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
  }, [fechaEnvio, filtroCordon, filtroLogistica, sinLogistica, filtroMlStatus, filtroSsosId, search]);

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
      if (fechaEnvio) statsParams.append('fecha_envio', fechaEnvio);
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
      if (fechaEnvio) statsParams.append('fecha_envio', fechaEnvio);
      const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${statsParams}`);
      setEstadisticas(statsData);
    } catch (err) {
      mostrarError(err);
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
        </div>
      )}

      {/* Scanner */}
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

      {/* Controls */}
      <div className={styles.controls}>
        <div className={styles.filtros}>
          <input
            type="date"
            value={fechaEnvio}
            onChange={(e) => setFechaEnvio(e.target.value)}
            className={styles.dateInput}
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

          <button
            onClick={() => setShowLogisticasModal(true)}
            className={styles.btnLogisticas}
            aria-label="Gestionar logísticas"
          >
            <Settings size={16} />
            Logísticas
          </button>
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
                <th>Pistoleado</th>
                <th>Caja</th>
              </tr>
            </thead>
            <tbody>
              {etiquetas.length === 0 ? (
                <tr>
                  <td colSpan={13} className={styles.empty}>
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
                        disabled={actualizando.has(e.shipping_id)}
                        className={styles.fechaInput}
                      />
                    </td>
                    <td>
                      <select
                        value={e.logistica_id || ''}
                        onChange={(ev) => cambiarLogistica(e.shipping_id, ev.target.value)}
                        disabled={actualizando.has(e.shipping_id)}
                        className={styles.logisticaSelect}
                      >
                        <option value="">— Sin asignar —</option>
                        {logisticasActivas.map(l => (
                          <option key={l.id} value={l.id}>{l.nombre}</option>
                        ))}
                      </select>
                    </td>
                    <td className={styles.cellMuted}>—</td>
                    <td className={styles.cellMuted}>—</td>
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

          <button
            onClick={borrarSeleccionados}
            className={styles.selectionBtnBorrar}
            title="Borrar etiquetas seleccionadas (requiere permisos)"
            aria-label="Borrar etiquetas seleccionadas"
          >
            <Trash2 size={16} />
            Borrar
          </button>

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
    </div>
  );
}
