import { useState, useEffect } from 'react';
import api from '../services/api';
import styles from './Notificaciones.module.css';

export default function Notificaciones() {
  const [notificaciones, setNotificaciones] = useState([]);
  const [stats, setStats] = useState({ total: 0, no_leidas: 0, por_tipo: {} });
  const [loading, setLoading] = useState(false);
  const [filtroTipo, setFiltroTipo] = useState(null);
  const [filtroPM, setFiltroPM] = useState(null);
  const [filtroSeveridad, setFiltroSeveridad] = useState(null);
  const [ordenamiento, setOrdenamiento] = useState('severidad_desc'); // severidad_desc, fecha_desc, markup_asc
  const [soloNoLeidas, setSoloNoLeidas] = useState(false);
  const [paginaActual, setPaginaActual] = useState(0);
  const [expandedNotif, setExpandedNotif] = useState(null);

  const [preciosSeteados, setPreciosSeteados] = useState({});
  const [vistaAgrupada, setVistaAgrupada] = useState(true);
  const [expandedGrupo, setExpandedGrupo] = useState(null);

  const ITEMS_PER_PAGE = 20;

  const fetchNotificaciones = async () => {
    try {
      setLoading(true);
      const endpoint = vistaAgrupada ? '/notificaciones/agrupadas' : '/notificaciones';
      const params = vistaAgrupada
        ? { solo_no_leidas: soloNoLeidas, tipo: filtroTipo }
        : { limit: 100, offset: 0, solo_no_leidas: soloNoLeidas, tipo: filtroTipo };

      const [notifResponse, statsResponse] = await Promise.all([
        api.get(endpoint, { params }),
        api.get('/notificaciones/stats')
      ]);

      setNotificaciones(notifResponse.data);
      setStats(statsResponse.data);
    } catch (error) {
      console.error('Error al obtener notificaciones:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchNotificaciones();
    // fetchNotificaciones se recrea cada render — recargar solo cuando cambian los filtros
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [soloNoLeidas, filtroTipo, vistaAgrupada]);

  // Resetear página cuando cambien los filtros u ordenamiento
  useEffect(() => {
    setPaginaActual(0);
  }, [filtroPM, filtroSeveridad, ordenamiento]);

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
        params: { tipo: filtroTipo }
      });
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al marcar todas:', error);
    }
  };

  const marcarTodasNoLeidas = async () => {
    try {
      await api.post('/notificaciones/marcar-todas-no-leidas', null, {
        params: { tipo: filtroTipo }
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
  
  const descartarNotificacion = async (notifId) => {
    try {
      await api.patch(`/notificaciones/${notifId}/descartar`);
      
      // Mostrar mensaje informativo al usuario
      alert('✓ Notificación descartada.\n\n' +
            '🔕 Se creó una regla para ignorar futuras notificaciones similares:\n' +
            '• Mismo producto\n' +
            '• Mismo tipo\n' +
            '• Mismo markup\n\n' +
            'Podés gestionar estas reglas desde Admin → Notificaciones Ignoradas');
      
      // Actualizar localmente en vista agrupada
      if (vistaAgrupada) {
        setNotificaciones(notificaciones.map(grupo => {
          if (grupo.notificaciones_ids && grupo.notificaciones_ids.includes(notifId)) {
            return {
              ...grupo,
              notificacion_reciente: {
                ...grupo.notificacion_reciente,
                estado: 'DESCARTADA',
                fecha_descarte: new Date().toISOString()
              }
            };
          }
          return grupo;
        }));
      } else {
        setNotificaciones(notificaciones.map(n =>
          n.id === notifId ? { ...n, estado: 'DESCARTADA', fecha_descarte: new Date().toISOString() } : n
        ));
      }
    } catch (error) {
      console.error('Error al descartar notificación:', error);
      alert('Error al descartar notificación');
      await fetchNotificaciones();
    }
  };

  const revisarNotificacion = async (notifId) => {
    try {
      await api.patch(`/notificaciones/${notifId}/revisar`);
      // Actualizar localmente en vista agrupada
      if (vistaAgrupada) {
        setNotificaciones(notificaciones.map(grupo => {
          if (grupo.notificaciones_ids && grupo.notificaciones_ids.includes(notifId)) {
            return {
              ...grupo,
              notificacion_reciente: {
                ...grupo.notificacion_reciente,
                estado: 'REVISADA',
                fecha_revision: new Date().toISOString()
              }
            };
          }
          return grupo;
        }));
      } else {
        setNotificaciones(notificaciones.map(n =>
          n.id === notifId ? { ...n, estado: 'REVISADA', fecha_revision: new Date().toISOString() } : n
        ));
      }
    } catch (error) {
      console.error('Error al revisar notificación:', error);
      await fetchNotificaciones();
    }
  };

  const resolverNotificacion = async (notifId) => {
    try {
      await api.patch(`/notificaciones/${notifId}/resolver`);
      // Actualizar localmente en vista agrupada
      if (vistaAgrupada) {
        setNotificaciones(notificaciones.map(grupo => {
          if (grupo.notificaciones_ids && grupo.notificaciones_ids.includes(notifId)) {
            return {
              ...grupo,
              notificacion_reciente: {
                ...grupo.notificacion_reciente,
                estado: 'RESUELTA',
                fecha_resolucion: new Date().toISOString()
              }
            };
          }
          return grupo;
        }));
      } else {
        setNotificaciones(notificaciones.map(n =>
          n.id === notifId ? { ...n, estado: 'RESUELTA', fecha_resolucion: new Date().toISOString() } : n
        ));
      }
    } catch (error) {
      console.error('Error al resolver notificación:', error);
      await fetchNotificaciones();
    }
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
    if (!notif.item_id || preciosSeteados[notif.id]) return;

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

  const getTipoIcon = (tipo) => {
    switch (tipo) {
      case 'markup_bajo': return '⚠️';
      case 'stock_bajo': return '📦';
      case 'precio_desactualizado': return '💰';
      default: return '🔔';
    }
  };

  const formatearFecha = (fecha) => {
    const date = new Date(fecha);
    return date.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const abrirEnML = (notif) => {
    if (notif.ml_id) {
      window.open(`https://www.mercadolibre.com.ar/ventas/${notif.ml_id}/detalle`, '_blank');
    } else {
      alert('No se puede abrir la orden: ml_id no disponible');
    }
  };

  // Extraer PMs únicos para el filtro
  const pmsUnicos = [...new Set(
    notificaciones
      .map(n => vistaAgrupada ? n.notificacion_reciente?.pm : n.pm)
      .filter(pm => pm && pm.trim() !== '')
  )].sort();

  // Filtrar por PM y Severidad en el frontend
  let notificacionesFiltradas = notificaciones.filter(n => {
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

  notificacionesFiltradas = [...notificacionesFiltradas].sort((a, b) => {
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

  const notificacionesPaginadas = notificacionesFiltradas.slice(
    paginaActual * ITEMS_PER_PAGE,
    (paginaActual + 1) * ITEMS_PER_PAGE
  );

  const totalPaginas = Math.ceil(notificacionesFiltradas.length / ITEMS_PER_PAGE);

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

      <div className={styles.filters}>
        <div className={styles.filterGroup}>
          <span style={{ 
            fontSize: '0.85rem', 
            color: 'var(--text-secondary)',
            fontWeight: 500,
            padding: '0 8px'
          }}>
            📋 Mostrando: <strong style={{ color: 'var(--primary-color)' }}>
              {notificacionesFiltradas.length}
            </strong> de {notificaciones.length}
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
          <label>Tipo:</label>
          <select value={filtroTipo || ''} onChange={(e) => setFiltroTipo(e.target.value || null)}>
            <option value="">Todas</option>
            <option value="markup_bajo">⚠️ Markup Bajo</option>
            <option value="stock_bajo">📦 Stock Bajo</option>
            <option value="precio_desactualizado">💰 Precio Desactualizado</option>
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label>PM:</label>
          <select value={filtroPM || ''} onChange={(e) => setFiltroPM(e.target.value || null)}>
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
                      await Promise.all(grupo.notificaciones_ids.map(id =>
                        api.patch(`/notificaciones/${id}/marcar-leida`)
                      ));
                      await fetchNotificaciones();
                    }
                  }
                }}>
                  <div className={styles.notifIcon}>{getTipoIcon(grupo.tipo)}</div>
                  <div className={styles.grupoMain}>
                    <div className={styles.grupoProducto}>
                      {grupo.codigo_producto} - {grupo.descripcion_producto}
                    </div>
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
                      <span className={styles.grupoMarkup}>Markup Real: {grupo.markup_real}%</span>
                      <span className={styles.grupoCount}>({grupo.count} notificación{grupo.count > 1 ? 'es' : ''})</span>
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

                    <div className={styles.detalleActions}>
                      {/* Botones de Gestión */}
                      <div className="btn-group-tesla compact" style={{ marginBottom: '12px' }}>
                        <button
                          onClick={() => {
                            Promise.all(grupo.notificaciones_ids.map(id => revisarNotificacion(id)));
                          }}
                          className="btn-tesla outline-success sm"
                          title="Marcar como revisada (no desaparece)"
                        >
                          Revisada ({grupo.count})
                        </button>
                        <button
                          onClick={() => {
                            if (confirm(`¿Ignorar ${grupo.count} notificación${grupo.count > 1 ? 'es' : ''}?\n\nSe creará una regla para NO notificar futuras ventas del mismo producto con el mismo markup.`)) {
                              Promise.all(grupo.notificaciones_ids.map(id => descartarNotificacion(id)))
                                .then(() => setExpandedGrupo(null));
                            }
                          }}
                          className="btn-tesla outline-danger sm"
                          title="Ignorar (no volver a notificar para este producto/markup)"
                        >
                          Ignorar ({grupo.count})
                        </button>
                        <button
                          onClick={() => {
                            Promise.all(grupo.notificaciones_ids.map(id => resolverNotificacion(id)));
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
                              Promise.all(grupo.notificaciones_ids.map(id => marcarComoNoLeida(id)));
                            }}
                            className="btn-tesla secondary sm"
                          >
                            ○ Marcar no leídas ({grupo.count})
                          </button>
                        )}
                        <button
                          onClick={() => {
                            if (confirm(`¿Eliminar ${grupo.count} notificación${grupo.count > 1 ? 'es' : ''}?`)) {
                              Promise.all(grupo.notificaciones_ids.map(id => eliminarNotificacion(id)))
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
                  <div className={styles.notifIcon}>{getTipoIcon(notif.tipo)}</div>
                  <div className={styles.notifMain}>
                    <div className={styles.notifMensaje}>{notif.mensaje}</div>
                    {notif.codigo_producto && (
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
