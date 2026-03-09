import { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw, Calendar, ExternalLink, Flag, Search, X,
} from 'lucide-react';
import api from '../services/api';
import { toLocalDateString } from '../utils/dateUtils';
import styles from './EnviosVistaFlag.module.css';

const FLAG_LABELS = {
  mal_pasado: 'Mal pasado',
  envio_cancelado: 'Envío cancelado',
  duplicado: 'Duplicado',
  otro: 'Otro',
};

const ML_STATUS_LABELS = {
  ready_to_ship: 'Listo',
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

const todayStr = () => toLocalDateString();

export default function EnviosVistaFlag() {
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
  const [search, setSearch] = useState('');
  const [soloFlag, setSoloFlag] = useState(false);

  // Selección
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [lastSelected, setLastSelected] = useState(null);

  // Flag modal
  const [showFlagModal, setShowFlagModal] = useState(false);
  const [flagType, setFlagType] = useState('mal_pasado');
  const [flagMotivo, setFlagMotivo] = useState('');
  const [flagLoading, setFlagLoading] = useState(false);
  const [bulkActualizando, setBulkActualizando] = useState(false);

  // Toast (inline error feedback)
  const [errorMsg, setErrorMsg] = useState(null);

  // Filtro client-side por flag
  const etiquetasFiltradas = soloFlag
    ? etiquetas.filter(e => e.flag_envio)
    : etiquetas;

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

  const buildFilterParams = useCallback(() => {
    const p = new URLSearchParams();
    if (fechaDesde) p.append('fecha_desde', fechaDesde);
    if (fechaHasta) p.append('fecha_hasta', fechaHasta);
    if (search) p.append('search', search);
    if (filtroMlStatus) p.append('ml_status', filtroMlStatus);
    return p.toString();
  }, [fechaDesde, fechaHasta, search, filtroMlStatus]);

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = buildFilterParams();
      const [etiqRes, statsRes] = await Promise.allSettled([
        api.get(`/etiquetas-envio?${params}`),
        api.get(`/etiquetas-envio/estadisticas?${params}`),
      ]);

      if (etiqRes.status === 'fulfilled') {
        setEtiquetas(etiqRes.value.data);
      } else {
        setError('Error cargando etiquetas');
      }

      if (statsRes.status === 'fulfilled') {
        setEstadisticas(statsRes.value.data);
      }
    } catch {
      setError('Error cargando datos');
    } finally {
      setLoading(false);
    }
  }, [buildFilterParams]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  // ── Error feedback ───────────────────────────────────────────

  const mostrarError = (err) => {
    const msg = err.response?.data?.detail || err.message || 'Error inesperado';
    setErrorMsg(msg);
    setTimeout(() => setErrorMsg(null), 5000);
  };

  // ── Selección ────────────────────────────────────────────────

  const toggleSeleccion = (shippingId, shiftKey) => {
    const nueva = new Set(selectedIds);

    if (shiftKey && lastSelected !== null) {
      const ids = etiquetasFiltradas.map(e => e.shipping_id);
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
    if (selectedIds.size === etiquetasFiltradas.length && etiquetasFiltradas.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(etiquetasFiltradas.map(e => e.shipping_id)));
    }
  };

  const limpiarSeleccion = () => {
    setSelectedIds(new Set());
    setLastSelected(null);
  };

  // ── Flag envío ───────────────────────────────────────────────

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
      try {
        const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${buildFilterParams()}`);
        setEstadisticas(statsData);
      } catch {
        // silencioso
      }
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

      setEtiquetas(prev =>
        prev.map(e =>
          selectedIds.has(e.shipping_id)
            ? { ...e, flag_envio: null, flag_envio_motivo: null }
            : e
        )
      );

      limpiarSeleccion();

      // Refresh stats
      try {
        const { data: statsData } = await api.get(`/etiquetas-envio/estadisticas?${buildFilterParams()}`);
        setEstadisticas(statsData);
      } catch {
        // silencioso
      }
    } catch (err) {
      mostrarError(err);
    } finally {
      setBulkActualizando(false);
    }
  };

  // ── Derived data ─────────────────────────────────────────────

  const mlStatuses = [...new Set(etiquetas.map(e => e.mlstatus).filter(Boolean))];

  // ── Render ───────────────────────────────────────────────────

  return (
    <div className={styles.container}>
      {/* Stats */}
      {estadisticas && (
        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{estadisticas.total}</div>
            <div className={styles.statLabel}>Etiquetas</div>
          </div>
          {estadisticas.flagged > 0 && (
            <button
              type="button"
              className={`${styles.statCard} ${styles.statCardClickable} ${soloFlag ? styles.statCardActive : ''}`}
              onClick={() => setSoloFlag(prev => !prev)}
            >
              <div className={`${styles.statValue} ${styles.statValueFlag}`}>
                {estadisticas.flagged}
              </div>
              <div className={styles.statLabel}>Flaggeadas</div>
            </button>
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
            {['hoy', 'ayer', '3d', '7d'].map(f => (
              <button
                key={f}
                type="button"
                onClick={() => aplicarFiltroRapido(f)}
                className={`${styles.btnDateQuick} ${filtroRapidoActivo === f ? styles.btnDateQuickActive : ''}`}
              >
                {f === 'hoy' ? 'Hoy' : f === 'ayer' ? 'Ayer' : f.toUpperCase()}
              </button>
            ))}

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
          <div className={styles.searchWrapper}>
            <Search size={14} className={styles.searchIcon} />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Shipping ID o destinatario..."
              className={styles.searchInput}
            />
          </div>

          {/* ML Status filter */}
          {mlStatuses.length > 0 && (
            <select
              value={filtroMlStatus}
              onChange={(e) => setFiltroMlStatus(e.target.value)}
              className={styles.selectSm}
            >
              <option value="">Estado ML</option>
              {mlStatuses.map(s => (
                <option key={s} value={s}>{ML_STATUS_LABELS[s] || s}</option>
              ))}
            </select>
          )}
        </div>

        <div className={styles.actions}>
          <button
            onClick={cargarDatos}
            className={styles.btnRefresh}
            disabled={loading}
            aria-label="Actualizar lista"
          >
            <RefreshCw size={16} className={loading ? styles.spin : ''} />
            Actualizar
          </button>
        </div>
      </div>

      {/* Error */}
      {error && <div className={styles.errorMsg}>{error}</div>}
      {errorMsg && <div className={styles.errorMsg}>{errorMsg}</div>}

      {/* Table */}
      {loading ? (
        <div className={styles.loadingMsg}>Cargando etiquetas...</div>
      ) : etiquetasFiltradas.length === 0 ? (
        <div className={styles.emptyMsg}>
          {soloFlag ? 'No hay etiquetas flaggeadas' : 'No hay etiquetas para la fecha seleccionada'}
        </div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th style={{ width: 40 }}>
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
                <th>Estado ML</th>
                <th>Fecha</th>
                <th>Flag</th>
              </tr>
            </thead>
            <tbody>
              {etiquetasFiltradas.map((e) => (
                <tr
                  key={e.shipping_id}
                  className={`${selectedIds.has(e.shipping_id) ? styles.rowSelected : ''} ${e.flag_envio ? styles.rowFlagged : ''}`}
                >
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(e.shipping_id)}
                      onChange={(ev) => toggleSeleccion(e.shipping_id, ev.nativeEvent.shiftKey)}
                      className={styles.checkbox}
                      aria-label={`Seleccionar envío ${e.shipping_id}`}
                    />
                  </td>
                  <td className={styles.shippingCell}>
                    {!e.es_manual && e.ml_order_id ? (
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
                  <td className={styles.direccionCell}>
                    {e.mlstreet_name ? `${e.mlstreet_name} ${e.mlstreet_number || ''}`.trim() : '—'}
                  </td>
                  <td>{e.mlzip_code || '—'}</td>
                  <td>{e.mlcity_name || '—'}</td>
                  <td>
                    {e.mlstatus ? (
                      <span className={`${styles.badge} ${getMlStatusClass(e.mlstatus)}`}>
                        {ML_STATUS_LABELS[e.mlstatus] || e.mlstatus}
                      </span>
                    ) : (
                      <span className={styles.cellMuted}>—</span>
                    )}
                  </td>
                  <td className={styles.fechaCell}>{e.fecha_envio || '—'}</td>
                  <td>
                    {e.flag_envio ? (
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

      {/* Footer */}
      {!loading && etiquetasFiltradas.length > 0 && (
        <div className={styles.footer}>
          <span>Mostrando {etiquetasFiltradas.length} etiquetas{soloFlag ? ' (flaggeadas)' : ''}</span>
        </div>
      )}

      {/* Selection bar */}
      {selectedIds.size > 0 && (
        <div className={styles.selectionBar}>
          <span className={styles.selectionCount}>
            {selectedIds.size} etiqueta{selectedIds.size !== 1 ? 's' : ''}
          </span>

          <div className={styles.selectionActions}>
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

            {(() => {
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
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <p className={styles.flagModalInfo}>
                {selectedIds.size} etiqueta{selectedIds.size !== 1 ? 's' : ''} seleccionada{selectedIds.size !== 1 ? 's' : ''}
              </p>

              <div className={styles.flagFormGroup}>
                <label className={styles.flagLabel} htmlFor="flagTypeVista">Tipo de flag</label>
                <select
                  id="flagTypeVista"
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
                <label className={styles.flagLabel} htmlFor="flagMotivoVista">Motivo / observación (opcional)</label>
                <textarea
                  id="flagMotivoVista"
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
