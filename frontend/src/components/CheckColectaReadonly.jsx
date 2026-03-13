import { Fragment, useState, useEffect, useCallback } from 'react';
import { useDebounce } from '../hooks/useDebounce';
import {
  RefreshCw, Calendar, Table, ExternalLink, ChevronRight,
} from 'lucide-react';
import CalendarioEnvios from './CalendarioEnvios';
import api from '../services/api';
import { toLocalDateString } from '../utils/dateUtils';
import styles from './CheckColectaReadonly.module.css';

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

const todayStr = () => toLocalDateString();

// ── Calendar badge renderer for colecta ───────────────────────
const renderColectaDayBadges = (dia, calStyles) => (
  <>
    {dia.por_estado_erp && Object.keys(dia.por_estado_erp).length > 0 && (
      <div className={calStyles.badgeRow}>
        {Object.entries(dia.por_estado_erp).map(([name, count]) => (
          <span key={name} className={`${calStyles.badge} ${styles.calBadgeErp}`}>
            {name} {count}
          </span>
        ))}
      </div>
    )}
    {dia.por_estado_ml && Object.keys(dia.por_estado_ml).length > 0 && (
      <div className={calStyles.badgeRow}>
        {Object.entries(dia.por_estado_ml).map(([status, count]) => (
          <span key={status} className={`${calStyles.badge} ${styles.calBadgeMl}`}>
            {ML_STATUS_LABELS[status] || status} {count}
          </span>
        ))}
      </div>
    )}
  </>
);

export default function CheckColectaReadonly() {
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
  const debouncedSearch = useDebounce(search, 400);

  // Vista
  const [vista, setVista] = useState('tabla');

  // Expanded rows
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
      if (debouncedSearch) params.search = debouncedSearch;

      const { data } = await api.get('/etiquetas-colecta', { params });

      setEtiquetas(data);

      // Compute stats in frontend
      const porEstadoErp = {};
      const porEstadoMl = {};
      for (const e of data) {
        if (e.ssos_name) porEstadoErp[e.ssos_name] = (porEstadoErp[e.ssos_name] || 0) + 1;
        if (e.mlstatus) porEstadoMl[e.mlstatus] = (porEstadoMl[e.mlstatus] || 0) + 1;
      }
      setEstadisticas({ total: data.length, por_estado_erp: porEstadoErp, por_estado_ml: porEstadoMl });
    } catch {
      setError('Error cargando etiquetas de colecta');
    } finally {
      setLoading(false);
    }
  }, [fechaDesde, fechaHasta, filtroMlStatus, filtroSsosId, debouncedSearch]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

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
      setRowItems(prev => ({ ...prev, [shippingId]: 'loading' }));
      try {
        const { data } = await api.get(`/etiquetas-colecta/${shippingId}/items`);
        setRowItems(prev => ({ ...prev, [shippingId]: data }));
      } catch {
        setRowItems(prev => ({ ...prev, [shippingId]: 'error' }));
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
  const erpColorMap = new Map();
  for (const e of etiquetas) {
    if (e.ssos_id != null && e.ssos_name && !erpStatesMap.has(e.ssos_id)) {
      erpStatesMap.set(e.ssos_id, e.ssos_name);
    }
    if (e.ssos_name && e.ssos_color && !erpColorMap.has(e.ssos_name)) {
      erpColorMap.set(e.ssos_name, e.ssos_color);
    }
  }

  const mlStatuses = [...new Set(etiquetas.map(e => e.mlstatus).filter(Boolean))];

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
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Shipping ID o destinatario..."
            className={styles.searchInput}
          />

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
                          className={styles.rowClickable}
                          onClick={() => toggleExpanded(e.shipping_id)}
                        >
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
                            <td colSpan={5}>
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
    </div>
  );
}
