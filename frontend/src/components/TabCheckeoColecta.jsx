import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Upload, RefreshCw, Search, Calendar, Table, ExternalLink,
  ScanBarcode, Trash2, X, CheckCircle, AlertCircle,
} from 'lucide-react';
import CalendarioEnvios from './CalendarioEnvios';
import api from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';
import styles from './TabCheckeoColecta.module.css';

const ML_STATUS_LABELS = {
  ready_to_ship: 'Listo para enviar',
  shipped: 'Enviado',
  delivered: 'Entregado',
  cancelled: 'Cancelado',
  not_delivered: 'No entregado',
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

const todayStr = () => new Date().toISOString().split('T')[0];

export default function TabCheckeoColecta() {
  const { tienePermiso } = usePermisos();
  const puedeSubir = tienePermiso('envios_flex.subir_etiquetas');
  const puedeEliminar = tienePermiso('envios_flex.eliminar');

  // Data
  const [etiquetas, setEtiquetas] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Upload
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const fileInputRef = useRef(null);

  // Scanner individual
  const scannerRef = useRef(null);
  const [scanFeedback, setScanFeedback] = useState(null); // { type: 'ok'|'dup'|'error', msg }

  // Filtros
  const [fechaDesde, setFechaDesde] = useState(todayStr());
  const [fechaHasta, setFechaHasta] = useState(todayStr());
  const [filtroMlStatus, setFiltroMlStatus] = useState('');
  const [filtroSsosId, setFiltroSsosId] = useState('');
  const [search, setSearch] = useState('');

  // Vista: tabla o calendario
  const [vista, setVista] = useState('tabla');

  // Selección múltiple
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [lastSelected, setLastSelected] = useState(null);

  // ── Data fetching ────────────────────────────────────────────

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta,
      };
      if (filtroMlStatus) params.mlstatus = filtroMlStatus;
      if (filtroSsosId) params.ssos_id = filtroSsosId;
      if (search) params.search = search;

      const [etiqRes, statsRes] = await Promise.all([
        api.get('/etiquetas-colecta', { params }),
        api.get('/etiquetas-colecta/estadisticas', { params }),
      ]);

      setEtiquetas(etiqRes.data);
      setEstadisticas(statsRes.data);
    } catch {
      setError('Error cargando etiquetas de colecta');
    } finally {
      setLoading(false);
    }
  }, [fechaDesde, fechaHasta, filtroMlStatus, filtroSsosId, search]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  // ── Upload ZPL ───────────────────────────────────────────────

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadResult(null);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const { data } = await api.post('/etiquetas-colecta/upload', formData, {
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

  // ── Scan individual (pistola / QR) ───────────────────────────

  const handleScan = async (value) => {
    const trimmed = value.trim();
    if (!trimmed) return;

    // Extraer JSON del QR — puede venir como JSON directo o como texto con JSON embebido
    let qrJson = trimmed;
    if (!trimmed.startsWith('{')) {
      // Intentar extraer un JSON del texto
      const match = trimmed.match(/\{[^}]+\}/);
      if (match) {
        qrJson = match[0];
      } else {
        setScanFeedback({ type: 'error', msg: 'No se encontró JSON en el escaneo' });
        return;
      }
    }

    try {
      const { data } = await api.post('/etiquetas-colecta/scan', { qr_json: qrJson });
      if (data.nueva) {
        setScanFeedback({ type: 'ok', msg: data.mensaje });
        cargarDatos();
      } else {
        setScanFeedback({ type: 'dup', msg: data.mensaje });
      }
    } catch (err) {
      setScanFeedback({
        type: 'error',
        msg: err.response?.data?.detail || err.message,
      });
    }

    // Limpiar input y re-focus para siguiente escaneo
    if (scannerRef.current) {
      scannerRef.current.value = '';
      scannerRef.current.focus();
    }

    // Auto-ocultar feedback
    setTimeout(() => setScanFeedback(null), 3000);
  };

  const handleScanKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleScan(e.target.value);
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
      for (let i = inicio; i <= fin; i++) {
        nueva.add(ids[i]);
      }
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
  };

  // ── Borrar seleccionados ─────────────────────────────────────

  const borrarSeleccionados = async () => {
    if (selectedIds.size === 0) return;
    const n = selectedIds.size;

    const ok = window.confirm(`¿Borrar ${n} etiqueta${n !== 1 ? 's' : ''} de colecta? Esta acción no se puede deshacer.`);
    if (!ok) return;

    try {
      await api.delete('/etiquetas-colecta', {
        data: { shipping_ids: Array.from(selectedIds) },
      });
      setEtiquetas((prev) => prev.filter((e) => !selectedIds.has(e.shipping_id)));
      limpiarSeleccion();
      cargarDatos();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error borrando etiquetas');
    }
  };

  // ── Calendar day click ───────────────────────────────────────

  const handleDiaClick = (dateStr) => {
    setFechaDesde(dateStr);
    setFechaHasta(dateStr);
    setVista('tabla');
  };

  // ── Derived data ─────────────────────────────────────────────

  const erpStatesMap = new Map();
  for (const e of etiquetas) {
    if (e.ssos_id && e.ssos_name && !erpStatesMap.has(e.ssos_id)) {
      erpStatesMap.set(e.ssos_id, e.ssos_name);
    }
  }

  const mlStatuses = [...new Set(etiquetas.map((e) => e.mlstatus).filter(Boolean))];

  // ── Render ───────────────────────────────────────────────────

  return (
    <div className={styles.container}>
      {/* Stats */}
      {estadisticas && (
        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{estadisticas.total}</div>
            <div className={styles.statLabel}>Total</div>
          </div>
          {Object.entries(estadisticas.por_estado_erp || {}).map(([name, count]) => (
            <div key={name} className={styles.statCard}>
              <div className={styles.statValue}>{count}</div>
              <div className={styles.statLabel}>{name}</div>
            </div>
          ))}
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
            placeholder="Escaneá el QR de la etiqueta..."
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

      {/* Toolbar */}
      <div className={styles.toolbar}>
        {/* Refresh */}
        <button onClick={cargarDatos} className={styles.btnRefresh} disabled={loading}>
          <RefreshCw size={16} className={loading ? styles.spin : ''} />
          Actualizar
        </button>

        {/* Upload ZPL */}
        {puedeSubir && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip,.txt"
              onChange={handleUpload}
              className={styles.fileInputHidden}
              id="colecta-zpl-upload"
            />
            <label
              htmlFor="colecta-zpl-upload"
              className={`${styles.btnUpload} ${uploading ? styles.btnDisabled : ''}`}
            >
              <Upload size={16} />
              {uploading ? 'Subiendo...' : 'Subir ZPL'}
            </label>
          </>
        )}

        {/* Date filters */}
        <div className={styles.dateGroup}>
          <input
            type="date"
            value={fechaDesde}
            onChange={(e) => setFechaDesde(e.target.value)}
            className={styles.dateInput}
          />
          <span className={styles.dateSeparator}>a</span>
          <input
            type="date"
            value={fechaHasta}
            onChange={(e) => setFechaHasta(e.target.value)}
            className={styles.dateInput}
          />
        </div>

        {/* ML Status filter */}
        <select
          value={filtroMlStatus}
          onChange={(e) => setFiltroMlStatus(e.target.value)}
          className={styles.filterSelect}
        >
          <option value="">Estado ML</option>
          {mlStatuses.map((s) => (
            <option key={s} value={s}>{ML_STATUS_LABELS[s] || s}</option>
          ))}
        </select>

        {/* ERP Status filter */}
        <select
          value={filtroSsosId}
          onChange={(e) => setFiltroSsosId(e.target.value)}
          className={styles.filterSelect}
        >
          <option value="">Estado ERP</option>
          {[...erpStatesMap.entries()].map(([id, name]) => (
            <option key={id} value={id}>{name}</option>
          ))}
        </select>

        {/* Search */}
        <div className={styles.searchBox}>
          <Search size={16} className={styles.searchIcon} />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Shipping ID o destinatario..."
            className={styles.searchInput}
          />
        </div>

        {/* Vista toggle */}
        <div className={styles.vistaToggle}>
          <button
            className={`${styles.vistaBtn} ${vista === 'tabla' ? styles.vistaBtnActive : ''}`}
            onClick={() => setVista('tabla')}
            title="Vista tabla"
          >
            <Table size={16} />
          </button>
          <button
            className={`${styles.vistaBtn} ${vista === 'calendario' ? styles.vistaBtnActive : ''}`}
            onClick={() => setVista('calendario')}
            title="Vista calendario"
          >
            <Calendar size={16} />
          </button>
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

      {/* Error */}
      {error && <div className={styles.errorMsg}>{error}</div>}

      {/* Calendar view */}
      {vista === 'calendario' && (
        <CalendarioEnvios
          onDiaClick={handleDiaClick}
          endpointUrl="/etiquetas-colecta/estadisticas-por-dia"
        />
      )}

      {/* Table view */}
      {vista === 'tabla' && (
        <>
          {loading ? (
            <div className={styles.loadingMsg}>Cargando etiquetas...</div>
          ) : etiquetas.length === 0 ? (
            <div className={styles.emptyMsg}>No hay etiquetas de colecta para este rango de fechas</div>
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
                    <th>Shipping ID</th>
                    <th>Destinatario</th>
                    <th>Estado ERP</th>
                    <th>Estado ML</th>
                  </tr>
                </thead>
                <tbody>
                  {etiquetas.map((e) => (
                    <tr
                      key={e.shipping_id}
                      className={selectedIds.has(e.shipping_id) ? styles.rowSelected : ''}
                    >
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedIds.has(e.shipping_id)}
                          onChange={(ev) => toggleSeleccion(e.shipping_id, ev.nativeEvent.shiftKey)}
                        />
                      </td>
                      <td className={styles.shippingCell}>
                        {e.ml_order_id ? (
                          <a
                            href={`https://www.mercadolibre.com.ar/ventas/${e.ml_order_id}/detalle`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={styles.shippingLink}
                          >
                            {e.shipping_id}
                            <ExternalLink size={12} className={styles.externalIcon} />
                          </a>
                        ) : (
                          <span>{e.shipping_id}</span>
                        )}
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
                          </span>
                        ) : (
                          <span className={styles.cellMuted}>—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Footer count */}
          {!loading && etiquetas.length > 0 && (
            <div className={styles.footer}>
              <span>Mostrando {etiquetas.length} etiquetas</span>
            </div>
          )}
        </>
      )}

      {/* Selection bar (floating) */}
      {selectedIds.size > 0 && (
        <div className={styles.selectionBar}>
          <span className={styles.selectionCount}>
            {selectedIds.size} etiqueta{selectedIds.size !== 1 ? 's' : ''}
          </span>

          <div className={styles.selectionActions}>
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
        </div>
      )}
    </div>
  );
}
