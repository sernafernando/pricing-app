import { Fragment, useState, useEffect, useCallback, useRef } from 'react';
import {
  Upload, RefreshCw, Calendar, Table, ExternalLink,
  ScanBarcode, Trash2, X, CheckCircle, AlertCircle, ChevronRight,
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
  const [estadisticas, setEstadisticas] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Upload
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const fileInputRef = useRef(null);

  // Scanner individual
  const scannerRef = useRef(null);
  const scanTimeoutRef = useRef(null);
  const [scanFeedback, setScanFeedback] = useState(null);

  // Filtros — date quick filters (copied from TabEnviosFlex)
  const [fechaDesde, setFechaDesde] = useState(todayStr());
  const [fechaHasta, setFechaHasta] = useState(todayStr());
  const [filtroRapidoActivo, setFiltroRapidoActivo] = useState('hoy');
  const [mostrarDropdownFecha, setMostrarDropdownFecha] = useState(false);
  const [fechaTemporal, setFechaTemporal] = useState({ desde: todayStr(), hasta: todayStr() });
  const [filtroMlStatus, setFiltroMlStatus] = useState('');
  const [filtroSsosId, setFiltroSsosId] = useState('');
  const [search, setSearch] = useState('');

  // Vista: tabla o calendario
  const [vista, setVista] = useState('tabla');

  // Selección múltiple
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [lastSelected, setLastSelected] = useState(null);

  // Delete confirmation (replaces window.confirm)
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Expanded rows (product details)
  const [expandedRows, setExpandedRows] = useState(new Set());
  const [rowItems, setRowItems] = useState({}); // { shipping_id: [items] | 'loading' | 'error' }

  // ── Date quick filter logic (copied from TabEnviosFlex) ──────

  const aplicarFiltroRapido = (filtro) => {
    const hoy = new Date();
    const fmt = (d) => d.toISOString().split('T')[0];
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

  // Cleanup scan timeout on unmount
  useEffect(() => {
    return () => {
      if (scanTimeoutRef.current) clearTimeout(scanTimeoutRef.current);
    };
  }, []);

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

    let qrJson = trimmed;
    if (!trimmed.startsWith('{')) {
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

    if (scannerRef.current) {
      scannerRef.current.value = '';
      scannerRef.current.focus();
    }

    // Auto-clear feedback with cleanup
    if (scanTimeoutRef.current) clearTimeout(scanTimeoutRef.current);
    scanTimeoutRef.current = setTimeout(() => setScanFeedback(null), 3000);
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
    setConfirmDelete(false);
  };

  // ── Borrar seleccionados (with inline confirm) ───────────────

  const borrarSeleccionados = async () => {
    if (selectedIds.size === 0) return;

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
    setConfirmDelete(false);
  };

  // ── Expandable rows (product details) ────────────────────────

  const toggleExpanded = async (shippingId) => {
    const newExpanded = new Set(expandedRows);

    if (newExpanded.has(shippingId)) {
      newExpanded.delete(shippingId);
      setExpandedRows(newExpanded);
      return;
    }

    newExpanded.add(shippingId);
    setExpandedRows(newExpanded);

    // Load items if not already loaded
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

  const erpStatesMap = new Map();
  const erpColorMap = new Map(); // name → ssos_color
  for (const e of etiquetas) {
    if (e.ssos_id && e.ssos_name && !erpStatesMap.has(e.ssos_id)) {
      erpStatesMap.set(e.ssos_id, e.ssos_name);
    }
    if (e.ssos_name && e.ssos_color && !erpColorMap.has(e.ssos_name)) {
      erpColorMap.set(e.ssos_name, e.ssos_color);
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
          {Object.entries(estadisticas.por_estado_erp || {}).map(([name, count]) => {
            const color = erpColorMap.get(name);
            return (
              <div
                key={name}
                className={styles.statCard}
                style={color ? { borderLeft: `4px solid ${color}` } : undefined}
              >
                <div className={styles.statValue} style={color ? { color } : undefined}>
                  {count}
                </div>
                <div className={styles.statLabel}>{name}</div>
              </div>
            );
          })}
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

      {/* Controls (flex pattern) */}
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

          {/* Search */}
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Shipping ID o destinatario..."
            className={styles.searchInput}
          />

          {/* ML Status filter */}
          <select
            value={filtroMlStatus}
            onChange={(e) => setFiltroMlStatus(e.target.value)}
            className={styles.selectSm}
          >
            <option value="">Estado ML</option>
            {mlStatuses.map((s) => (
              <option key={s} value={s}>{ML_STATUS_LABELS[s] || s}</option>
            ))}
          </select>

          {/* ERP Status filter */}
          {erpStatesMap.size > 0 && (
            <select
              value={filtroSsosId}
              onChange={(e) => setFiltroSsosId(e.target.value)}
              className={styles.selectSm}
            >
              <option value="">Estado ERP</option>
              {[...erpStatesMap.entries()]
                .sort(([, a], [, b]) => a.localeCompare(b))
                .map(([id, name]) => (
                  <option key={id} value={id}>{name}</option>
                ))}
            </select>
          )}
        </div>

        <div className={styles.actions}>
          {/* Vista toggle */}
          <div className={styles.vistaToggle}>
            <button
              type="button"
              className={`${styles.vistaBtn} ${vista === 'tabla' ? styles.vistaBtnActive : ''}`}
              onClick={() => setVista('tabla')}
              aria-label="Vista tabla"
            >
              <Table size={15} />
              Tabla
            </button>
            <button
              type="button"
              className={`${styles.vistaBtn} ${vista === 'calendario' ? styles.vistaBtnActive : ''}`}
              onClick={() => setVista('calendario')}
              aria-label="Vista calendario"
            >
              <Calendar size={15} />
              Calendario
            </button>
          </div>

          {/* Refresh */}
          <button onClick={cargarDatos} className={styles.btnRefresh} disabled={loading} aria-label="Actualizar lista">
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

      {/* Delete confirmation bar (replaces window.confirm) */}
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

      {/* Error */}
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
                    <th style={{ width: 24 }} />
                    <th>Shipping ID</th>
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

                        {/* Expanded row — product details */}
                        {isExpanded && (
                          <tr className={styles.expandedRow}>
                            <td colSpan={6}>
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

          {/* Footer count */}
          {!loading && etiquetas.length > 0 && (
            <div className={styles.footer}>
              <span>Mostrando {etiquetas.length} etiquetas</span>
            </div>
          )}
        </>
      )}

      {/* Selection bar (floating) */}
      {selectedIds.size > 0 && !confirmDelete && (
        <div className={styles.selectionBar}>
          <span className={styles.selectionCount}>
            {selectedIds.size} etiqueta{selectedIds.size !== 1 ? 's' : ''}
          </span>

          <div className={styles.selectionActions}>
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
