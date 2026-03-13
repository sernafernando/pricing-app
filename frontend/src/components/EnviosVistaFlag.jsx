import { useState, useEffect, useCallback, useRef } from 'react';
import { useDebounce } from '../hooks/useDebounce';
import {
  RefreshCw, MapPin, Calendar, Flag, Search, X, Building,
} from 'lucide-react';
import api from '../services/api';
import { toLocalDateString } from '../utils/dateUtils';
import { useSSEChannel } from '../hooks/useSSEChannel';
import { useSSE } from '../contexts/SSEContext';
import styles from './EnviosVistaFlag.module.css';

const CORDONES = ['CABA', 'Cordón 1', 'Cordón 2', 'Cordón 3'];

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
  const [filtroCordon, setFiltroCordon] = useState('');
  const [filtroMlStatus, setFiltroMlStatus] = useState('');
  const [filtroSsosId, setFiltroSsosId] = useState('');
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 400);
  const [soloFlag, setSoloFlag] = useState(false);
  const [sinCordon, setSinCordon] = useState(false);

  // Selección
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [lastSelected, setLastSelected] = useState(null);

  // Flag modal
  const [showFlagModal, setShowFlagModal] = useState(false);
  const [flagType, setFlagType] = useState('mal_pasado');
  const [flagMotivo, setFlagMotivo] = useState('');
  const [flagLoading, setFlagLoading] = useState(false);
  const [bulkActualizando, setBulkActualizando] = useState(false);

  // Error feedback
  const [errorMsg, setErrorMsg] = useState(null);

  // Smart polling ref
  const pollingRef = useRef({ count: null, lastUpdated: null });

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
    if (filtroCordon) p.append('cordon', filtroCordon);
    if (sinCordon) p.append('sin_cordon', 'true');
    if (filtroMlStatus) p.append('mlstatus', filtroMlStatus);
    if (filtroSsosId) p.append('ssos_id', filtroSsosId);
    if (debouncedSearch) p.append('search', debouncedSearch);
    return p;
  }, [fechaDesde, fechaHasta, filtroCordon, sinCordon, filtroMlStatus, filtroSsosId, debouncedSearch]);

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = buildFilterParams();

      const etiqPromise = api.get(`/etiquetas-envio?${params}`);
      const statsPromise = api.get(`/etiquetas-envio/estadisticas?${params}`);

      const etiqResponse = await etiqPromise;
      setEtiquetas(etiqResponse.data);

      try {
        const statsResponse = await statsPromise;
        setEstadisticas(statsResponse.data);
      } catch {
        // Stats best-effort
      }
      pollingRef.current = { count: null, lastUpdated: null };
    } catch {
      setError('Error cargando etiquetas');
    } finally {
      setLoading(false);
    }
  }, [buildFilterParams]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  // ── SSE-driven reload: replace 60s polling with event-driven updates ──

  const { isDegraded } = useSSE();

  const silentReload = useCallback(async () => {
    if (document.hidden || showFlagModal) return;

    try {
      const params = buildFilterParams();
      const etiqResponse = await api.get(`/etiquetas-envio?${params}`);
      setEtiquetas(etiqResponse.data);
      setError(null);

      try {
        const statsResponse = await api.get(`/etiquetas-envio/estadisticas?${params}`);
        setEstadisticas(statsResponse.data);
      } catch {
        // Stats best-effort
      }
    } catch {
      // Silencioso
    }
  }, [showFlagModal, buildFilterParams]);

  useSSEChannel('etiquetas:changed', silentReload);
  useSSEChannel('shipments:webhook', silentReload);

  // Fallback polling: re-activate 60s polling when SSE is degraded
  useEffect(() => {
    if (!isDegraded()) return;

    const POLL_INTERVAL = 60_000;
    const checkForUpdates = async () => {
      if (document.hidden || showFlagModal) return;

      try {
        const p = new URLSearchParams();
        if (fechaDesde) p.append('fecha_desde', fechaDesde);
        if (fechaHasta) p.append('fecha_hasta', fechaHasta);

        const { data } = await api.get(`/etiquetas-envio/check-updates?${p}`);
        const prev = pollingRef.current;

        if (prev.count === null) {
          pollingRef.current = { count: data.count, lastUpdated: data.last_updated };
          if (!error) return;
        }

        if (data.count !== prev.count || data.last_updated !== prev.lastUpdated) {
          pollingRef.current = { count: data.count, lastUpdated: data.last_updated };
          await silentReload();
        }
      } catch {
        // Silencioso
      }
    };

    const intervalId = setInterval(checkForUpdates, POLL_INTERVAL);
    pollingRef.current = { count: null, lastUpdated: null };

    return () => clearInterval(intervalId);
  }, [isDegraded, fechaDesde, fechaHasta, showFlagModal, buildFilterParams, error, silentReload]);

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

  // ── Render ───────────────────────────────────────────────────

  return (
    <div className={styles.container}>
      {/* Estadísticas — same layout as TabEnviosFlex */}
      {estadisticas && (
        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{estadisticas.total}</div>
            <div className={styles.statLabel}>Etiquetas</div>
          </div>
          {Object.entries(estadisticas.por_cordon || {}).map(([cordonName, qty]) => (
            <button
              key={cordonName}
              type="button"
              className={`${styles.statCard} ${styles.statCardClickable} ${filtroCordon === cordonName && !sinCordon ? styles.statCardActive : ''}`}
              onClick={() => { setFiltroCordon(prev => prev === cordonName ? '' : cordonName); setSinCordon(false); }}
            >
              <div className={styles.statValue}>{qty}</div>
              <div className={styles.statLabel}>{cordonName}</div>
            </button>
          ))}
          {estadisticas.sin_cordon > 0 && (
            <button
              type="button"
              className={`${styles.statCard} ${styles.statCardClickable} ${sinCordon ? styles.statCardActive : ''}`}
              onClick={() => { setSinCordon(prev => !prev); setFiltroCordon(''); }}
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

      {/* Controls — same layout as TabEnviosFlex */}
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
            placeholder="Buscar (shipping ID, destinatario)..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
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
            value={filtroMlStatus}
            onChange={(e) => setFiltroMlStatus(e.target.value)}
            className={styles.selectSm}
          >
            <option value="">Estado ML</option>
            {Object.entries(ML_STATUS_LABELS).map(([val, label]) => (
              <option key={val} value={val}>{label}</option>
            ))}
          </select>

          {/* Estado ERP filter — built from data */}
          {(() => {
            const erpOptions = [];
            const seen = new Set();
            for (const e of etiquetas) {
              const ssosId = e.ssos_id;
              const ssosName = e.ssos_name;
              if (!ssosName) continue;
              if (ssosId == null) continue;
              const ssosKey = String(ssosId);
              if (!seen.has(ssosKey)) {
                seen.add(ssosKey);
                erpOptions.push({ id: ssosKey, name: ssosName });
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
        </div>
      </div>

      {/* Error */}
      {error && <div className={styles.error}>{error}</div>}
      {errorMsg && <div className={styles.error}>{errorMsg}</div>}

      {/* Table */}
      {loading ? (
        <div className={styles.loading}>Cargando etiquetas...</div>
      ) : (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
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
                <th>Pistoleado</th>
                <th>Caja</th>
              </tr>
            </thead>
            <tbody>
              {etiquetasFiltradas.length === 0 ? (
                <tr>
                  <td colSpan={14} className={styles.empty}>
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
                    {/* Shipping ID + badges */}
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
                    {/* Destinatario + nickname + comment */}
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
                    {/* Dirección — full layout like original */}
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
                    {/* CP — map link like original */}
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
                              ? 'Ver ubicación exacta en Google Maps'
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
                    {/* Localidad */}
                    <td className={styles.direccion}>{e.mlcity_name || '—'}</td>
                    {/* Cordón */}
                    <td>
                      <span className={`${styles.badge} ${getCordonBadgeClass(e.cordon)}`}>
                        {e.cordon || 'Sin asignar'}
                      </span>
                    </td>
                    {/* Estado ERP */}
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
                    {/* Estado ML — readonly badge */}
                    <td>
                      {e.mlstatus ? (
                        <span className={`${styles.badge} ${getMlStatusClass(e.mlstatus)}`}>
                          {ML_STATUS_LABELS[e.mlstatus] || e.mlstatus}
                        </span>
                      ) : (
                        <span className={styles.cellMuted}>—</span>
                      )}
                    </td>
                    {/* Fecha — readonly */}
                    <td className={styles.fechaReadonly}>{e.fecha_envio || '—'}</td>
                    {/* Logística — readonly badge */}
                    <td>
                      {e.logistica_nombre ? (
                        <span
                          className={styles.logisticaBadge}
                          style={
                            e.logistica_color
                              ? { background: `${e.logistica_color}20`, color: e.logistica_color }
                              : undefined
                          }
                        >
                          {e.logistica_nombre}
                        </span>
                      ) : (
                        <span className={styles.cellMuted}>—</span>
                      )}
                    </td>
                    {/* Transporte — readonly badge */}
                    <td>
                      {e.transporte_nombre ? (
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
                      )}
                    </td>
                    {/* Pistoleado — readonly */}
                    <td className={e.pistoleado_at ? styles.cellSuccess : styles.cellMuted}>
                      {e.pistoleado_at
                        ? `${new Date(e.pistoleado_at).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })} — ${e.pistoleado_operador_nombre || ''}`
                        : '—'}
                    </td>
                    {/* Caja — readonly */}
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
