import { useState, useEffect } from 'react';
import api from '../services/api';
import styles from './Notificaciones.module.css';
import NotificacionFamiliaTabs from '../components/NotificacionFamiliaTabs';
import NotificacionIcono from '../components/NotificacionIcono';
import { esNotificacionMarkup, tituloDeTipo } from '../utils/notificacionFamilias';

const ITEMS_PER_PAGE = 20;

/** Drop null/empty filters so the request only carries the active ones. */
const soloFiltrosActivos = (params) =>
  Object.fromEntries(Object.entries(params).filter(([, valor]) => valor !== null && valor !== undefined && valor !== ''));

export default function Notificaciones() {
  const [notificaciones, setNotificaciones] = useState([]);
  const [stats, setStats] = useState({ total: 0, no_leidas: 0, por_tipo: {} });
  const [loading, setLoading] = useState(false);
  const [familia, setFamilia] = useState(null);
  const [totalServidor, setTotalServidor] = useState(0);
  const [pmsServidor, setPmsServidor] = useState([]);
  const [filtroPM, setFiltroPM] = useState(null);
  const [filtroSeveridad, setFiltroSeveridad] = useState(null);
  const [ordenamiento, setOrdenamiento] = useState('severidad_desc'); // severidad_desc, fecha_desc, markup_asc
  const [soloNoLeidas, setSoloNoLeidas] = useState(false);
  const [paginaActual, setPaginaActual] = useState(0);
  const [expandedNotif, setExpandedNotif] = useState(null);

  const [preciosSeteados, setPreciosSeteados] = useState({});
  const [vistaAgrupada, setVistaAgrupada] = useState(true);
  const [expandedGrupo, setExpandedGrupo] = useState(null);

  const fetchNotificaciones = async () => {
    try {
      setLoading(true);
      if (vistaAgrupada) {
        const [notifResponse, statsResponse] = await Promise.all([
          api.get('/notificaciones/agrupadas', {
            params: soloFiltrosActivos({ solo_no_leidas: soloNoLeidas, familia }),
          }),
          api.get('/notificaciones/stats'),
        ]);
        setNotificaciones(notifResponse.data);
        setStats(statsResponse.data);
        return;
      }

      // Lista plana: paginada en el servidor, así se llega a todas las notificaciones.
      const filtros = soloFiltrosActivos({
        solo_no_leidas: soloNoLeidas,
        familia,
        pm: filtroPM,
        severidad: filtroSeveridad,
      });
      const [notifResponse, totalResponse, statsResponse] = await Promise.all([
        api.get('/notificaciones', {
          params: {
            ...filtros,
            limit: ITEMS_PER_PAGE,
            offset: paginaActual * ITEMS_PER_PAGE,
            orden: ordenamiento,
          },
        }),
        api.get('/notificaciones/total', { params: filtros }),
        api.get('/notificaciones/stats'),
      ]);
      setNotificaciones(notifResponse.data);
      setTotalServidor(totalResponse.data.total);
      setPmsServidor(totalResponse.data.pms ?? []);
      setStats(statsResponse.data);
    } catch (error) {
      console.error('Error al obtener notificaciones:', error);
    } finally {
      setLoading(false);
    }
  };

  // La lista plana pide cada página, orden y filtro al servidor; la agrupada filtra y ordena en el cliente.
  const [paginaServidor, ordenServidor, pmServidor, severidadServidor] = vistaAgrupada
    ? [null, null, null, null]
    : [paginaActual, ordenamiento, filtroPM, filtroSeveridad];

  useEffect(() => {
    fetchNotificaciones();
    // fetchNotificaciones se recrea cada render — recargar solo cuando cambian los filtros
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [soloNoLeidas, familia, vistaAgrupada, paginaServidor, ordenServidor, pmServidor, severidadServidor]);

  // Resetear página cuando cambien los filtros u ordenamiento
  useEffect(() => {
    setPaginaActual(0);
  }, [filtroPM, filtroSeveridad, ordenamiento, familia, soloNoLeidas, vistaAgrupada]);

  const marcarComoLeida = async (notifId) => {
    try {
      await api.patch(`/notificaciones/${notifId}/marcar-leida`);

      // Actualizar estado local en lugar de recargar todo
      setNotificaciones(notificaciones.map(n =>
        n.id === notifId ? { ...n, leida: true, fecha_lectura: new Date().toISOString() } : n
      ));

      // Actualizar stats
      setStats(prev => ({
        ...prev,
        no_leidas: Math.max(0, prev.no_leidas - 1)
      }));
    } catch (error) {
      console.error('Error al marcar notificación:', error);
    }
  };

  const marcarTodasLeidas = async () => {
    try {
      await api.post('/notificaciones/marcar-todas-leidas', null, {
        params: soloFiltrosActivos({ familia })
      });
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al marcar todas:', error);
    }
  };

  const marcarTodasNoLeidas = async () => {
    try {
      await api.post('/notificaciones/marcar-todas-no-leidas', null, {
        params: soloFiltrosActivos({ familia })
      });
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al marcar todas como no leídas:', error);
    }
  };

  const marcarComoNoLeida = async (notifId) => {
    try {
      await api.patch(`/notificaciones/${notifId}/marcar-no-leida`);
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al marcar como no leída:', error);
    }
  };

  const eliminarNotificacion = async (notifId) => {
    try {
      const notif = notificaciones.find(n => n.id === notifId);
      await api.delete(`/notificaciones/${notifId}`);

      // Actualizar estado local
      setNotificaciones(notificaciones.filter(n => n.id !== notifId));

      // Actualizar stats
      setStats(prev => ({
        ...prev,
        total: Math.max(0, prev.total - 1),
        no_leidas: notif && !notif.leida ? Math.max(0, prev.no_leidas - 1) : prev.no_leidas
      }));

      // Cerrar expandido si es la misma
      if (expandedNotif === notifId) {
        setExpandedNotif(null);
      }
    } catch (error) {
      console.error('Error al eliminar notificación:', error);
    }
  };

  const limpiarLeidas = async () => {
    if (!confirm('¿Eliminar todas las notificaciones leídas?')) return;
    try {
      await api.delete('/notificaciones/limpiar');
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al limpiar:', error);
    }
  };

  // ===== NUEVAS FUNCIONES DE GESTIÓN =====
  
  const tipoNotificacionById = (notifId) => {
    for (const row of notificaciones) {
      if (row?.id === notifId) return row.tipo;
      if (row?.notificaciones_ids?.includes(notifId)) {
        return row.tipo || row.notificacion_reciente?.tipo;
      }
    }
    return null;
  };

  // Single gate: compras.faltantes only clears when the PM resolves (not dismiss).
  const puedeDescartarNotificacion = (notifId) => tipoNotificacionById(notifId) !== 'compras.faltantes';

  // Group actions go in ONE request: one per notification took the API down
  // when a group of 1411 was ignored (prod incident 2026-11-18).
  const accionGrupo = async (ids, accion) => {
    try {
      await api.post('/notificaciones/bulk', { ids, accion });
    } catch (error) {
      console.error(`Error en acción "${accion}" sobre el grupo:`, error);
      alert('No se pudo aplicar la acción al grupo');
    }
    await fetchNotificaciones();
  };

  const getSeveridadBadge = (severidad) => {
    const badges = {
      'URGENT': { icon: '🔴', text: 'Urgente', class: 'urgent' },
      'CRITICAL': { icon: '🟠', text: 'Crítico', class: 'critical' },
      'WARNING': { icon: '🟡', text: 'Advertencia', class: 'warning' },
      'INFO': { icon: '🟢', text: 'Info', class: 'info' }
    };
    return badges[severidad] || badges['INFO'];
  };

  const getEstadoBadge = (estado) => {
    const badges = {
      'PENDIENTE': { text: 'Pendiente', class: 'pendiente' },
      'REVISADA': { text: 'Revisada', class: 'revisada' },
      'DESCARTADA': { text: 'Descartada', class: 'descartada' },
      'EN_GESTION': { text: 'En Gestión', class: 'en-gestion' },
      'RESUELTA': { text: 'Resuelta', class: 'resuelta' }
    };
    return badges[estado] || badges['PENDIENTE'];
  };

  const fetchPrecioSeteado = async (notif) => {
    if (!esNotificacionMarkup(notif.tipo) || !notif.item_id || preciosSeteados[notif.id]) return;

    try {
      const response = await api.get(`/productos/${notif.item_id}/pricing-stored`);
      if (response.data && response.data.precio_lista_ml) {
        setPreciosSeteados(prev => ({ ...prev, [notif.id]: response.data.precio_lista_ml }));
      }
    } catch (error) {
      console.error('Error al obtener precio seteado:', error);
    }
  };

  const toggleExpand = async (notif) => {
    if (expandedNotif === notif.id) {
      setExpandedNotif(null);
    } else {
      setExpandedNotif(notif.id);
      // Obtener precio seteado del producto
      await fetchPrecioSeteado(notif);
      if (!notif.leida) {
        await marcarComoLeida(notif.id);
        await fetchNotificaciones();
      }
    }
  };

  const formatearFecha = (fecha) => {
    const date = new Date(fecha);
    return date.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  };

  const abrirEnML = (notif) => {
    if (notif.ml_id) {
      window.open(`https://www.mercadolibre.com.ar/ventas/${notif.ml_id}/detalle`, '_blank');
    } else {
      alert('No se puede abrir la orden: ml_id no disponible');
    }
  };

  // PMs para el filtro: en la lista plana vienen del servidor (todas las páginas), en la agrupada de los grupos
  const pmsUnicos = !vistaAgrupada ? pmsServidor : [...new Set(
    notificaciones
      .map(n => n.notificacion_reciente?.pm)
      .filter(pm => pm && pm.trim() !== '')
  )].sort();

  // Vista agrupada: filtrar por PM y Severidad en el frontend (la lista plana ya viene filtrada del servidor)
  let notificacionesFiltradas = !vistaAgrupada ? notificaciones : notificaciones.filter(n => {
    // Extraer datos según vista
    const pm = vistaAgrupada ? n.notificacion_reciente?.pm : n.pm;
    const severidad = vistaAgrupada ? n.notificacion_reciente?.severidad : n.severidad;

    // Filtro PM
    if (filtroPM && pm !== filtroPM) return false;
    
    // Filtro Severidad
    if (filtroSeveridad && severidad !== filtroSeveridad) return false;

    return true;
  });

  // Ordenar notificaciones
  const getSeveridadValue = (sev) => {
    const valores = { 'URGENT': 4, 'CRITICAL': 3, 'WARNING': 2, 'INFO': 1 };
    return valores[sev] || 0;
  };

  if (vistaAgrupada) notificacionesFiltradas = [...notificacionesFiltradas].sort((a, b) => {
    const aSev = vistaAgrupada ? a.notificacion_reciente?.severidad : a.severidad;
    const bSev = vistaAgrupada ? b.notificacion_reciente?.severidad : b.severidad;
    const aFecha = vistaAgrupada ? a.ultima_fecha : a.fecha_creacion;
    const bFecha = vistaAgrupada ? b.ultima_fecha : b.fecha_creacion;
    const aMarkup = vistaAgrupada ? a.markup_real : a.markup_real;
    const bMarkup = vistaAgrupada ? b.markup_real : b.markup_real;

    switch (ordenamiento) {
      case 'severidad_desc': {
        // Urgente → Info, luego más recientes
        const sevDiffDesc = getSeveridadValue(bSev) - getSeveridadValue(aSev);
        if (sevDiffDesc !== 0) return sevDiffDesc;
        return new Date(bFecha) - new Date(aFecha);
      }
      
      case 'severidad_asc': {
        // Info → Urgente, luego más recientes
        const sevDiffAsc = getSeveridadValue(aSev) - getSeveridadValue(bSev);
        if (sevDiffAsc !== 0) return sevDiffAsc;
        return new Date(bFecha) - new Date(aFecha);
      }
      
      case 'fecha_desc':
        return new Date(bFecha) - new Date(aFecha);
      
      case 'fecha_asc':
        return new Date(aFecha) - new Date(bFecha);
      
      case 'markup_asc':
        // Markup ascendente (más negativo primero)
        if (aMarkup === null) return 1;
        if (bMarkup === null) return -1;
        return aMarkup - bMarkup;
      
      case 'markup_desc':
        // Markup descendente (más positivo primero)
        if (aMarkup === null) return 1;
        if (bMarkup === null) return -1;
        return bMarkup - aMarkup;
      
      default:
        return 0;
    }
  });

  const notificacionesPaginadas = vistaAgrupada
    ? notificacionesFiltradas.slice(paginaActual * ITEMS_PER_PAGE, (paginaActual + 1) * ITEMS_PER_PAGE)
    : notificacionesFiltradas;

  const totalPaginas = Math.ceil(
    (vistaAgrupada ? notificacionesFiltradas.length : totalServidor) / ITEMS_PER_PAGE
  );

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>📬 Notificaciones</h1>
        <div className={styles.stats}>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>Total</span>
            <span className={styles.statValue}>{stats.total}</span>
          </div>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>No leídas</span>
            <span className={styles.statValue}>{stats.no_leidas}</span>
          </div>
        </div>
      </div>

      <NotificacionFamiliaTabs familia={familia} onChange={setFamilia} stats={stats} />

      <div className={styles.filters}>
        <div className={styles.filterGroup}>
          <span style={{ 
            fontSize: '0.85rem', 
            color: 'var(--text-secondary)',
            fontWeight: 500,
            padding: '0 8px'
          }}>
            📋 Mostrando: <strong style={{ color: 'var(--primary-color)' }}>
              {notificacionesPaginadas.length}
            </strong> de {vistaAgrupada ? notificaciones.length : totalServidor}
          </span>
        </div>

        <div className={styles.filterGroup}>
          <label>
            <input
              type="checkbox"
              checked={soloNoLeidas}
              onChange={(e) => setSoloNoLeidas(e.target.checked)}
            />
            Solo no leídas
          </label>
        </div>

        <div className={styles.filterGroup}>
          <label>
            <input
              type="checkbox"
              checked={vistaAgrupada}
              onChange={(e) => setVistaAgrupada(e.target.checked)}
            />
            Agrupar por producto/markup
          </label>
        </div>

        <div className={styles.filterGroup}>
          <label htmlFor="notif-filtro-pm">PM:</label>
          <select id="notif-filtro-pm" value={filtroPM || ''} onChange={(e) => setFiltroPM(e.target.value || null)}>
            <option value="">Todos</option>
            {pmsUnicos.map(pm => (
              <option key={pm} value={pm}>{pm}</option>
            ))}
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label>Urgencia:</label>
          <select value={filtroSeveridad || ''} onChange={(e) => setFiltroSeveridad(e.target.value || null)}>
            <option value="">Todas</option>
            <option value="URGENT">🔴 Urgente</option>
            <option value="CRITICAL">🟠 Crítico</option>
            <option value="WARNING">🟡 Advertencia</option>
            <option value="INFO">🟢 Info</option>
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label>Ordenar:</label>
          <select value={ordenamiento} onChange={(e) => setOrdenamiento(e.target.value)}>
            <option value="severidad_desc">🚨 Urgente → Info</option>
            <option value="severidad_asc">🟢 Info → Urgente</option>
            <option value="fecha_desc">📅 Más recientes</option>
            <option value="fecha_asc">📅 Más antiguas</option>
            <option value="markup_asc">📉 Markup peor → mejor</option>
            <option value="markup_desc">📈 Markup mejor → peor</option>
          </select>
        </div>

        <div className={styles.actions}>
          {stats.no_leidas > 0 && (
            <button onClick={marcarTodasLeidas} className="btn-tesla secondary sm">
              ✓ Marcar todas leídas
            </button>
          )}
          {stats.leidas > 0 && (
            <button onClick={marcarTodasNoLeidas} className="btn-tesla secondary sm">
              ○ Marcar todas no leídas
            </button>
          )}
          <button onClick={limpiarLeidas} className="btn-tesla ghost sm" style={{ color: 'var(--error)' }}>
            🗑️ Limpiar leídas
          </button>
        </div>
      </div>

      {loading ? (
        <div className={styles.loading}>Cargando...</div>
      ) : notificaciones.length === 0 ? (
        <div className={styles.empty}>
          <p>📭 No hay notificaciones</p>
        </div>
      ) : vistaAgrupada ? (
        <>
          <div className={styles.notifList}>
            {notificacionesPaginadas.map((grupo) => (
              <div
                key={`${grupo.item_id}-${grupo.tipo}-${grupo.markup_real}`}
                data-testid="notif-grupo"
                className={`${styles.grupoCard} ${!grupo.notificacion_reciente.leida ? styles.noLeida : ''}`}
              >
                <div className={styles.grupoHeader} onClick={async () => {
                  if (expandedGrupo === grupo) {
                    setExpandedGrupo(null);
                  } else {
                    setExpandedGrupo(grupo);
                    await fetchPrecioSeteado(grupo.notificacion_reciente);
                    // Marcar todas las del grupo como leídas si no lo están
                    if (!grupo.notificacion_reciente.leida) {
                      await accionGrupo(grupo.notificaciones_ids, 'leida');
                    }
                  }
                }}>
                  <div className={styles.notifIcon}><NotificacionIcono tipo={grupo.tipo} /></div>
                  <div className={styles.grupoMain}>
                    {esNotificacionMarkup(grupo.tipo) ? (
                      <div className={styles.grupoProducto}>
                        {grupo.codigo_producto} - {grupo.descripcion_producto}
                      </div>
                    ) : (
                      <>
                        <div className={styles.grupoProducto}>{tituloDeTipo(grupo.tipo)}</div>
                        <div className={styles.grupoMensaje}>{grupo.notificacion_reciente.mensaje}</div>
                      </>
                    )}
                    <div className={styles.grupoInfo}>
                      {/* Badge de severidad */}
                      {grupo.notificacion_reciente.severidad && (
                        <span className={`${styles.severidadBadge} ${styles[getSeveridadBadge(grupo.notificacion_reciente.severidad).class]}`}>
                          {getSeveridadBadge(grupo.notificacion_reciente.severidad).icon} {getSeveridadBadge(grupo.notificacion_reciente.severidad).text}
                        </span>
                      )}
                      {/* Badge de estado */}
                      {grupo.notificacion_reciente.estado && (
                        <span className={`${styles.estadoBadge} ${styles[getEstadoBadge(grupo.notificacion_reciente.estado).class]}`}>
                          {getEstadoBadge(grupo.notificacion_reciente.estado).text}
                        </span>
                      )}
                      {esNotificacionMarkup(grupo.tipo) && (
                        <span className={styles.grupoMarkup}>Markup Real: {grupo.markup_real}%</span>
                      )}
                      <span className={styles.grupoCount}>({grupo.count} {grupo.count > 1 ? 'notificaciones' : 'notificación'})</span>
                      {grupo.pm && <span className={styles.pmTag}>PM: {grupo.pm}</span>}
                    </div>
                    <div className={styles.grupoFechas}>
                      {grupo.count > 1 ? (
                        <span>{formatearFecha(grupo.primera_fecha)} → {formatearFecha(grupo.ultima_fecha)}</span>
                      ) : (
                        <span>{formatearFecha(grupo.ultima_fecha)}</span>
                      )}
                    </div>
                  </div>
                  <div className={styles.expandIcon}>
                    {expandedGrupo === grupo ? '▼' : '▶'}
                  </div>
                </div>

                {expandedGrupo === grupo && (
                  <div className={styles.grupoDetalle}>
                    {esNotificacionMarkup(grupo.tipo) ? (
                      <>
                        {/* Mostrar detalles de la notificación más reciente */}
                        <h4 className={styles.seccionTitulo}>📊 Operación Más Reciente</h4>
                        <div className={styles.detalleGrid}>
                          <div className={styles.detalleItem}>
                            <strong>Markup Real:</strong>
                            <span className={grupo.notificacion_reciente.markup_real < 0 ? styles.negativo : ''}>
                              {grupo.notificacion_reciente.markup_real}%
                            </span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Monto de la Venta:</strong>
                            <span>${parseFloat(grupo.notificacion_reciente.monto_venta).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Costo de la Venta:</strong>
                            <span>${grupo.notificacion_reciente.costo_operacion ? parseFloat(grupo.notificacion_reciente.costo_operacion).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'N/A'}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Costo Envío s/IVA:</strong>
                            <span>${grupo.notificacion_reciente.costo_envio ? parseFloat(grupo.notificacion_reciente.costo_envio).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '0,00'}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Fecha Venta:</strong>
                            <span>{formatearFecha(grupo.notificacion_reciente.fecha_venta)}</span>
                          </div>
                        </div>

                        {/* Sección 2: Configuración ML */}
                        <h4 className={styles.seccionTitulo}>🛒 Configuración ML</h4>
                        <div className={styles.detalleGrid}>
                          <div className={styles.detalleItem}>
                            <strong>Cantidad:</strong>
                            <span>{grupo.notificacion_reciente.cantidad || 1} unidad{grupo.notificacion_reciente.cantidad > 1 ? 'es' : ''}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Lista de Precios:</strong>
                            <span>{grupo.notificacion_reciente.tipo_publicacion || 'N/A'}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Comisión ML:</strong>
                            <span>{grupo.notificacion_reciente.comision_ml ? `${parseFloat(grupo.notificacion_reciente.comision_ml).toFixed(2)}%` : 'N/A'}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>IVA:</strong>
                            <span>{grupo.notificacion_reciente.iva_porcentaje || 21}%</span>
                          </div>
                        </div>

                        {/* Sección 3: Configuración del Producto */}
                        <h4 className={styles.seccionTitulo}>⚙️ Configuración Producto</h4>
                        <div className={styles.detalleGrid}>
                          <div className={styles.detalleItem}>
                            <strong>Precio Venta Seteado:</strong>
                            <span>${preciosSeteados[grupo.notificacion_reciente.id] ? parseFloat(preciosSeteados[grupo.notificacion_reciente.id]).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'Cargando...'}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Markup Esperado:</strong>
                            <span>{grupo.notificacion_reciente.markup_objetivo}%</span>
                          </div>
                          {grupo.notificacion_reciente.pm && (
                            <div className={styles.detalleItem}>
                              <strong>Product Manager:</strong>
                              <span>{grupo.notificacion_reciente.pm}</span>
                            </div>
                          )}
                          <div className={styles.detalleItem}>
                            <strong>Costo Actual:</strong>
                            <span>${grupo.notificacion_reciente.costo_actual ? parseFloat(grupo.notificacion_reciente.costo_actual).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'N/A'}</span>
                          </div>
                        </div>
                      </>
                    ) : (
                      <p className={styles.detalleMensaje}>{grupo.notificacion_reciente.mensaje}</p>
                    )}

                    <div className={styles.detalleActions}>
                      {/* Botones de Gestión */}
                      <div className="btn-group-tesla compact" style={{ marginBottom: '12px' }}>
                        <button
                          onClick={() => {
                            accionGrupo(grupo.notificaciones_ids, 'revisada');
                          }}
                          className="btn-tesla outline-success sm"
                          title="Marcar como revisada (no desaparece)"
                        >
                          Revisada ({grupo.count})
                        </button>
                        {puedeDescartarNotificacion(grupo.notificaciones_ids?.[0]) && (
                        <button
                          onClick={() => {
                            if (confirm(`¿Ignorar ${grupo.count} notificación${grupo.count > 1 ? 'es' : ''}?\n\nSe creará una regla para NO notificar futuras ventas del mismo producto con el mismo markup.`)) {
                              accionGrupo(grupo.notificaciones_ids, 'descartada')
                                .then(() => setExpandedGrupo(null));
                            }
                          }}
                          className="btn-tesla outline-danger sm"
                          title="Ignorar (no volver a notificar para este producto/markup)"
                        >
                          Ignorar ({grupo.count})
                        </button>
                        )}
                        <button
                          onClick={() => {
                            accionGrupo(grupo.notificaciones_ids, 'resuelta');
                          }}
                          className="btn-tesla outline sm"
                          title="Marcar como resuelta"
                        >
                          Resuelta ({grupo.count})
                        </button>
                      </div>

                      {/* Separador */}
                      <hr style={{ margin: '12px 0', border: 'none', borderTop: '1px solid var(--border-color)', opacity: 0.3 }} />

                      {/* Botones de Acción */}
                      <div className="btn-group-tesla compact">
                        {grupo.notificacion_reciente.ml_id && (
                          <button
                            onClick={() => abrirEnML(grupo.notificacion_reciente)}
                            className="btn-tesla outline-subtle-primary sm"
                          >
                            🔗 Ver última en ML
                          </button>
                        )}
                        {grupo.notificacion_reciente.leida && (
                          <button
                            onClick={() => {
                              accionGrupo(grupo.notificaciones_ids, 'no_leida');
                            }}
                            className="btn-tesla secondary sm"
                          >
                            ○ Marcar no leídas ({grupo.count})
                          </button>
                        )}
                        <button
                          onClick={() => {
                            if (confirm(`¿Eliminar ${grupo.count} notificación${grupo.count > 1 ? 'es' : ''}?`)) {
                              accionGrupo(grupo.notificaciones_ids, 'eliminar')
                                .then(() => setExpandedGrupo(null));
                            }
                          }}
                          className="btn-tesla ghost sm"
                          style={{ color: 'var(--error)' }}
                        >
                          🗑️ Eliminar ({grupo.count})
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          {totalPaginas > 1 && (
            <div className={styles.pagination}>
              <button
                onClick={() => setPaginaActual(paginaActual - 1)}
                disabled={paginaActual === 0}
                className={styles.paginationBtn}
              >
                ← Anterior
              </button>
              <span className={styles.paginationInfo}>
                Página {paginaActual + 1} de {totalPaginas}
              </span>
              <button
                onClick={() => setPaginaActual(paginaActual + 1)}
                disabled={paginaActual >= totalPaginas - 1}
                className={styles.paginationBtn}
              >
                Siguiente →
              </button>
            </div>
          )}
        </>
      ) : (
        <>
          <div className={styles.notifList}>
            {notificacionesPaginadas.map((notif) => (
              <div
                key={notif.id}
                className={`${styles.notifCard} ${!notif.leida ? styles.noLeida : ''}`}
              >
                <div className={styles.notifHeader} onClick={() => toggleExpand(notif)}>
                  <div className={styles.notifIcon}><NotificacionIcono tipo={notif.tipo} /></div>
                  <div className={styles.notifMain}>
                    {!esNotificacionMarkup(notif.tipo) && (
                      <div className={styles.notifTitulo}>{tituloDeTipo(notif.tipo)}</div>
                    )}
                    <div className={styles.notifMensaje}>{notif.mensaje}</div>
                    {esNotificacionMarkup(notif.tipo) && notif.codigo_producto && (
                      <div className={styles.notifProducto}>
                        {notif.codigo_producto} - {notif.descripcion_producto}
                      </div>
                    )}
                    {notif.pm && (
                      <div className={styles.pmTag}>PM: {notif.pm}</div>
                    )}
                  </div>
                  <div className={styles.notifMeta}>
                    <span className={styles.notifFecha}>{formatearFecha(notif.fecha_creacion)}</span>
                    {!notif.leida && <span className={styles.badgeNoLeida}>Nueva</span>}
                  </div>
                  <div className={styles.expandIcon}>
                    {expandedNotif === notif.id ? '▼' : '▶'}
                  </div>
                </div>

                {expandedNotif === notif.id && (
                  <div className={styles.notifDetalle}>
                    {esNotificacionMarkup(notif.tipo) ? (
                      <>
                        {/* Sección 1: Datos de la Operación */}
                        <h4 className={styles.seccionTitulo}>📊 Operación</h4>
                        <div className={styles.detalleGrid}>
                          <div className={styles.detalleItem}>
                            <strong>Markup Real:</strong>
                            <span className={notif.markup_real < 0 ? styles.negativo : ''}>
                              {notif.markup_real}%
                            </span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Monto de la Venta:</strong>
                            <span>${parseFloat(notif.monto_venta).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Costo de la Venta:</strong>
                            <span>${notif.costo_operacion ? parseFloat(notif.costo_operacion).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'N/A'}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Costo Envío s/IVA:</strong>
                            <span>${notif.costo_envio ? parseFloat(notif.costo_envio).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '0,00'}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Fecha Venta:</strong>
                            <span>{formatearFecha(notif.fecha_venta)}</span>
                          </div>
                        </div>

                        {/* Sección 2: Configuración ML */}
                        <h4 className={styles.seccionTitulo}>🛒 Configuración ML</h4>
                        <div className={styles.detalleGrid}>
                          <div className={styles.detalleItem}>
                            <strong>Cantidad:</strong>
                            <span>{notif.cantidad || 1} unidad{notif.cantidad > 1 ? 'es' : ''}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Lista de Precios:</strong>
                            <span>{notif.tipo_publicacion || 'N/A'}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Comisión ML:</strong>
                            <span>{notif.comision_ml ? `${parseFloat(notif.comision_ml).toFixed(2)}%` : 'N/A'}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>IVA:</strong>
                            <span>{notif.iva_porcentaje || 21}%</span>
                          </div>
                        </div>

                        {/* Sección 3: Configuración del Producto */}
                        <h4 className={styles.seccionTitulo}>⚙️ Configuración Producto</h4>
                        <div className={styles.detalleGrid}>
                          <div className={styles.detalleItem}>
                            <strong>Precio Venta Seteado:</strong>
                            <span>${preciosSeteados[notif.id] ? parseFloat(preciosSeteados[notif.id]).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'Cargando...'}</span>
                          </div>
                          <div className={styles.detalleItem}>
                            <strong>Markup Esperado:</strong>
                            <span>{notif.markup_objetivo}%</span>
                          </div>
                          {notif.pm && (
                            <div className={styles.detalleItem}>
                              <strong>Product Manager:</strong>
                              <span>{notif.pm}</span>
                            </div>
                          )}
                          <div className={styles.detalleItem}>
                            <strong>Costo Actual:</strong>
                            <span>${notif.costo_actual ? parseFloat(notif.costo_actual).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'N/A'}</span>
                          </div>
                        </div>
                      </>
                    ) : (
                      <p className={styles.detalleMensaje}>{notif.mensaje}</p>
                    )}

                    <div className={styles.detalleActions}>
                      {notif.ml_id && (
                        <button
                          onClick={() => abrirEnML(notif)}
                          className={styles.btnPrimary}
                        >
                          🔗 Ver en MercadoLibre
                        </button>
                      )}
                      {notif.leida && (
                        <button
                          onClick={() => marcarComoNoLeida(notif.id)}
                          className={styles.btnSecondary}
                        >
                          ○ Marcar no leída
                        </button>
                      )}
                      <button
                        onClick={() => eliminarNotificacion(notif.id)}
                        className={styles.btnDanger}
                      >
                        🗑️ Eliminar
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          {totalPaginas > 1 && (
            <div className={styles.pagination}>
              <button
                onClick={() => setPaginaActual(paginaActual - 1)}
                disabled={paginaActual === 0}
                className={styles.paginationBtn}
              >
                ← Anterior
              </button>
              <span className={styles.paginationInfo}>
                Página {paginaActual + 1} de {totalPaginas}
              </span>
              <button
                onClick={() => setPaginaActual(paginaActual + 1)}
                disabled={paginaActual >= totalPaginas - 1}
                className={styles.paginationBtn}
              >
                Siguiente →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
