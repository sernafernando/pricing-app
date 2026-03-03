import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Upload, RefreshCw, Search, Calendar, Table as TableIcon,
  CheckCircle, AlertCircle,
} from 'lucide-react';
import CalendarioEnvios from './CalendarioEnvios';
import api from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';
import { useToast } from '../hooks/useToast';
import Toast from './Toast';
import styles from './TabCheckeoColecta.module.css';

const ML_STATUS_LABELS = {
  ready_to_ship: 'Listo para enviar',
  shipped: 'Enviado',
  delivered: 'Entregado',
  cancelled: 'Cancelado',
  not_delivered: 'No entregado',
};

const todayStr = () => new Date().toISOString().split('T')[0];

// ── Helper: badge classes ───────────────────────────────────────

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

export default function TabCheckeoColecta() {
  const { tienePermiso } = usePermisos();

  const puedeSubir = tienePermiso('envios_flex.subir_etiquetas');

  // Data
  const [etiquetas, setEtiquetas] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filtros
  const [fechaDesde, setFechaDesde] = useState(todayStr());
  const [fechaHasta, setFechaHasta] = useState(todayStr());
  const [filtroRapidoActivo, setFiltroRapidoActivo] = useState('hoy');
  const [mostrarDropdownFecha, setMostrarDropdownFecha] = useState(false);
  const [fechaTemporal, setFechaTemporal] = useState({ desde: todayStr(), hasta: todayStr() });
  const [filtroMlStatus, setFiltroMlStatus] = useState('');
  const [filtroSsosId, setFiltroSsosId] = useState('');
  const [search, setSearch] = useState('');

  // Upload
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const fileInputRef = useRef(null);

  // Vista: tabla o calendario
  const [vistaActiva, setVistaActiva] = useState('tabla');

  // Toast
  const { toast, hideToast } = useToast(5000);

  // ── Filtros rápidos de fecha ────────────────────────────────

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

  // ── Data loading ────────────────────────────────────────────

  const buildFilterParams = useCallback(() => {
    const p = new URLSearchParams();
    if (fechaDesde) p.append('fecha_desde', fechaDesde);
    if (fechaHasta) p.append('fecha_hasta', fechaHasta);
    if (filtroMlStatus) p.append('mlstatus', filtroMlStatus);
    if (filtroSsosId) p.append('ssos_id', filtroSsosId);
    if (search) p.append('search', search);
    return p;
  }, [fechaDesde, fechaHasta, filtroMlStatus, filtroSsosId, search]);

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = buildFilterParams();

      const [etiqResponse, statsResponse] = await Promise.all([
        api.get(`/etiquetas-envio?${params}`),
        api.get(`/etiquetas-envio/estadisticas?${params}`),
      ]);

      setEtiquetas(etiqResponse.data);
      setEstadisticas(statsResponse.data);
    } catch {
      setError('Error cargando etiquetas');
    } finally {
      setLoading(false);
    }
  }, [buildFilterParams]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  // ── File Upload ─────────────────────────────────────────────

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

  // ── Calendar day click ──────────────────────────────────────

  const handleDiaClick = (dateStr) => {
    setFiltroRapidoActivo('custom');
    setFechaDesde(dateStr);
    setFechaHasta(dateStr);
    setVistaActiva('tabla');
  };

  // ── Build ERP filter options dynamically from data ──────────

  const erpOptions = [];
  const seen = new Set();
  for (const e of etiquetas) {
    if (e.ssos_id != null && !seen.has(e.ssos_id)) {
      seen.add(e.ssos_id);
      erpOptions.push({ id: e.ssos_id, name: e.ssos_name || `Estado ${e.ssos_id}` });
    }
  }

  // ── Render ──────────────────────────────────────────────────

  return (
    <div className={styles.container}>
      {/* Estadísticas */}
      {estadisticas && (
        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{estadisticas.total}</div>
            <div className={styles.statLabel}>Etiquetas</div>
          </div>
        </div>
      )}

      {/* Upload ZPL */}
      {puedeSubir && (
        <div className={styles.uploadSection}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip,.txt"
            onChange={handleUpload}
            style={{ display: 'none' }}
            id="upload-zpl-colecta"
          />
          <button
            type="button"
            className="btn-tesla outline-subtle-primary sm"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            aria-label="Subir archivo ZPL"
          >
            <Upload size={16} />
            {uploading ? 'Subiendo...' : 'Subir ZPL'}
          </button>

          {uploadResult && (
            <div className={uploadResult.errores > 0 ? styles.uploadError : styles.uploadSuccess}>
              {uploadResult.errores > 0 ? (
                <>
                  <AlertCircle size={16} />
                  {uploadResult.detalle_errores?.[0] || 'Error al procesar archivo'}
                </>
              ) : (
                <>
                  <CheckCircle size={16} />
                  {uploadResult.nuevas} nueva{uploadResult.nuevas !== 1 ? 's' : ''}
                  {uploadResult.duplicadas > 0 && ` · ${uploadResult.duplicadas} duplicada${uploadResult.duplicadas !== 1 ? 's' : ''}`}
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Controls */}
      <div className={styles.controls}>
        <div className={styles.filtros}>
          {/* Filtros rápidos de fecha */}
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
            placeholder="Buscar shipping ID..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className={styles.searchInput}
          />

          {/* Filtro Estado ML */}
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

          {/* Filtro Estado ERP (dinámico desde datos) */}
          <select
            value={filtroSsosId}
            onChange={(e) => setFiltroSsosId(e.target.value)}
            className={styles.selectSm}
          >
            <option value="">Estado ERP</option>
            {erpOptions.map((opt) => (
              <option key={opt.id} value={opt.id}>{opt.name}</option>
            ))}
          </select>
        </div>

        {/* Actions row */}
        <div className={styles.actions}>
          <div className={styles.vistaToggle}>
            <button
              type="button"
              className={vistaActiva === 'tabla' ? styles.vistaBtnActive : styles.vistaBtn}
              onClick={() => setVistaActiva('tabla')}
            >
              <TableIcon size={14} /> Tabla
            </button>
            <button
              type="button"
              className={vistaActiva === 'calendario' ? styles.vistaBtnActive : styles.vistaBtn}
              onClick={() => setVistaActiva('calendario')}
            >
              <Calendar size={14} /> Calendario
            </button>
          </div>

          <button
            type="button"
            className="btn-tesla outline-subtle-primary sm"
            onClick={cargarDatos}
            disabled={loading}
            aria-label="Refrescar datos"
          >
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
            Refrescar
          </button>
        </div>
      </div>

      {/* Vista: Calendario */}
      {vistaActiva === 'calendario' && (
        <CalendarioEnvios onDiaClick={handleDiaClick} />
      )}

      {/* Vista: Tabla */}
      {vistaActiva === 'tabla' && (
        <>
          {loading ? (
            <div className={styles.loading}>Cargando etiquetas...</div>
          ) : error ? (
            <div className={styles.error}>{error}</div>
          ) : (
            <div className={styles.tableContainer}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Shipping ID</th>
                    <th>Destinatario</th>
                    <th>Estado ERP</th>
                    <th>Estado ML</th>
                  </tr>
                </thead>
                <tbody>
                  {etiquetas.length === 0 ? (
                    <tr>
                      <td colSpan={4} className={styles.empty}>
                        No hay etiquetas para la fecha seleccionada
                      </td>
                    </tr>
                  ) : (
                    etiquetas.map((e) => (
                      <tr key={e.shipping_id}>
                        <td>
                          {e.ml_order_id ? (
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
                        </td>
                        <td>{e.mlreceiver_name || '—'}</td>
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
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* Footer count */}
          {!loading && !error && etiquetas.length > 0 && (
            <div className={styles.footer}>
              {etiquetas.length} etiqueta{etiquetas.length !== 1 ? 's' : ''}
            </div>
          )}
        </>
      )}

      {/* Toast */}
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={hideToast}
        />
      )}
    </div>
  );
}
